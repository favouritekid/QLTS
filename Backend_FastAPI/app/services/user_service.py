# app/services/user_service.py
import hashlib
from app.core.log_redaction import chu_loi_an_toan  # V6 vòng 5: lỗi CSDL ra ngoài log ⇒ tóm tắt
import io
import csv
from typing import AsyncGenerator
import structlog
from typing import Any, Callable, Dict, List, Optional, Tuple  # ✅ ADD Callable for transaction pattern
from datetime import datetime, timezone
# ✅ REMOVED: UploadFile import (Issue #3 - Service Layer Purity)
# Service layer should only use pure Python types (bytes, str, int, etc.)
# Router layer handles FastAPI-specific types (UploadFile, Request, etc.)
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import casbin  # ← PHASE 1: Import casbin

from .. import models, schemas
from ..config import settings
from ..utils.csv_helpers import sanitize_csv_row  # ✅ SECURITY FIX: CSV Injection Prevention
from ..utils.exceptions import (  # ✅ PHASE 1: Custom exceptions (protocol-independent)
    BadRequest,
    BaseAppException,
    BusinessRuleViolation,
    CacheServiceError,
    DuplicateResourceError,
    InvalidCredentials,
    InvalidToken,
    ResourceNotFoundError,
    UserServiceError,
)
from ..core.constants import UserRole

# ✅ 1. SỬA LỖI: Thêm import `safe_redis_pipeline` (sửa NameError)
from ..database import (
    redis_client,
    safe_redis_delete,
    safe_redis_pipeline,
    safe_redis_set,
    safe_redis_get
)
from ..security import (
    create_password_reset_token,
    get_password_hash,
    verify_password,
    verify_password_reset_token,
)
from ..security.hibp import check_password_breached

# ✅ 2. Event Dispatcher Pattern (replaces direct Socket.IO dependency)
from ..core.events import dispatcher, TransportEvents
from ..socket_metrics import socket_emit_failures_total, socket_events_emitted_total
from ..utils import file_helpers
from ..utils.token_logging import token_fingerprint
from . import activity_service

# ✅ SỬA LỖI: Chuyển log sang đồng bộ (tương thích với main.py V5)
log = structlog.get_logger(__name__)


# =============================================================================
# REAL-TIME DATA SYNC HELPER
# =============================================================================

def _co_avatar_duoc_gui(
    avatar_content: Optional[bytes], avatar_filename: Optional[str]
) -> bool:
    """Có avatar được GỬI LÊN hay không — quyết định gọi validator hay bỏ qua.

    ⚠️ KHÔNG dùng ``if avatar_content and avatar_filename``. Một tệp RỖNG có tên
    hợp lệ cho ``avatar_content = b""``, thứ falsy: cả khối bị bỏ qua, không
    validator nào chạy, không lỗi nào được nêu, và endpoint trả THÀNH CÔNG trong
    khi không lưu gì. Người dùng thấy 2xx rồi không thấy avatar — hỏng im lặng.

    Router chỉ đọc khi ``avatar and avatar.filename`` và để cả hai là ``None``
    nếu không có tệp, nên ``is not None`` phân biệt sạch "không gửi gì" với "gửi
    một tệp rỗng". Mọi thứ ĐÃ GỬI đều đi qua ``save_avatar``, nơi tên rỗng, nội
    dung rỗng, sai đuôi, quá cỡ và sai MIME đều có 400/413 riêng.

    Ba đường gọi dùng CHUNG hàm này: cùng một vị từ chép ba bản là cách chắc
    chắn để sửa một chỗ rồi bỏ sót hai chỗ kia.
    """
    return avatar_content is not None or avatar_filename is not None


async def emit_data_updated(
    resource_type: str,
    operation: str,
    resource_id: Optional[int] = None,
    data: Optional[Dict[str, Any]] = None
):
    """
    ✅ REAL-TIME DATA SYNC (v16):
    Emit 'data_updated' event to ALL connected admin clients for real-time sync.

    This solves the stale data problem where:
    - Admin A updates User C
    - Admin B still sees old data until manual refresh

    Args:
        resource_type: Type of resource (e.g., "user", "lead", "organization")
        operation: Operation performed (e.g., "create", "update", "delete")
        resource_id: ID of the affected resource
        data: Optional payload with updated data (e.g., updated user object)

    Example:
        await emit_data_updated("user", "update", resource_id=5, data={"full_name": "Johnny"})

    Frontend will:
    - Receive this event
    - Invalidate React Query cache
    - Automatically refetch fresh data
    - Show toast notification
    """
    try:
        event_data = {
            "resource_type": resource_type,
            "operation": operation,
            "resource_id": resource_id,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Dispatch event (Event Dispatcher Pattern - transport-agnostic)
        # Broadcast to ALL connected clients via registered handlers
        await dispatcher.dispatch(
            "data.updated",  # Domain event
            event_data=event_data
        )

        socket_events_emitted_total.labels(event_type="data_updated").inc()
        log.info(
            "Dispatched data_updated event",
            resource_type=resource_type,
            operation=operation,
            resource_id=resource_id,
        )
    except Exception as e:
        # Don't fail the main operation if socket emit fails
        socket_emit_failures_total.labels(event_type="data_updated").inc()
        log.error(
            "Failed to emit data_updated event (non-critical)",
            resource_type=resource_type,
            operation=operation,
            error=str(e),
        )


# --- Các hàm lấy User (Read-only, không cần rollback) ---


async def get_user_by_username(
    db: AsyncSession, username: str
) -> Optional[models.User]:
    """
    Get user by username.

    ✅ PHASE 2 - WEEK 2: Refactored to use UserRepository
    """
    from app.repositories import UserRepository

    repo = UserRepository(db)
    return await repo.get_by_username(username)


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[models.User]:
    """
    Get user by email address.

    ✅ PHASE 2 - WEEK 2: Refactored to use UserRepository
    """
    from app.repositories import UserRepository

    repo = UserRepository(db)
    return await repo.get_by_email(email)


async def get_user_by_id(db: AsyncSession, user_id: int) -> models.User:
    """
    Get user by ID.

    ✅ PHASE 2 - WEEK 2: Refactored to use UserRepository
    """
    from app.repositories import UserRepository

    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if not user:
        raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")
    return user


async def get_user_for_refresh(
    db: AsyncSession, username: str
) -> Optional[models.User]:
    """
    Get user by username with pessimistic lock for refresh token flow.

    ✅ PHASE 2: Added for auth module refactor.

    Uses SELECT ... FOR UPDATE to prevent race conditions during token refresh.
    This is called from the /refresh endpoint to atomically lock the user
    record before issuing new tokens.

    Args:
        db: Database session
        username: Username to search and lock

    Returns:
        Locked User instance or None if not found
    """
    from app.repositories import UserRepository

    repo = UserRepository(db)
    return await repo.get_by_username_for_update(username)


# ← PHASE 2: Helper function to get highest priority role from Casbin
async def get_highest_priority_role_from_casbin(
    enforcer: casbin.AsyncEnforcer,
    user_id: int
) -> str:
    """
    Lấy role có độ ưu tiên cao nhất từ Casbin cho user (đọc BỘ NHỚ enforcer của worker này — chỉ dùng cho báo cáo đọc;
    đường GHI vai CSDL dùng :func:`highest_priority_role` trên dòng ``casbin_rule``, PR-B lượt 4).
    Returns: "admin" | "manager" | "officer" | "user"
    """
    user_subject = f"user:{user_id}"
    return highest_priority_role(await enforcer.get_roles_for_user(user_subject))


def highest_priority_role(casbin_roles) -> str:
    """Vai ưu tiên cao nhất trong một danh sách vai Casbin (``role:<tên>``), bỏ tiền tố; rỗng ⇒ ``"user"``. Bảng ưu tiên
    GIỮ NGUYÊN bản của module này (thiếu ``role:accountant`` — khác ``role_service.ROLE_PRIORITY``: việc riêng, ngoài PR-B)."""
    ROLE_PRIORITY = {
        "role:admin": 4,
        "role:manager": 3,
        "role:officer": 2,
        "role:user": 1
    }

    if not casbin_roles:
        return "user"  # Default fallback

    highest_role = max(casbin_roles, key=lambda r: ROLE_PRIORITY.get(r, 0))
    return highest_role.replace("role:", "")  # Return "admin", not "role:admin"


# =============================================================================
# PHASE 2: TEMPORAL ARCHITECTURE - USER ASSIGNMENT MANAGEMENT
# =============================================================================

async def _create_or_update_user_assignment(
    db: AsyncSession,
    user: models.User,
    new_role: str,
    new_unit_id: Optional[int],
    assigned_by_user_id: Optional[int] = None,
    enforcer: Optional[casbin.AsyncEnforcer] = None  # ✅ ADDED enforcer
) -> Optional[models.UserUnitAssignment]:
    """
    ✅ PHASE 2: Temporal Architecture Helper

    Create or update user assignment with temporal history tracking.

    This function implements the atomic transaction pattern for user role/unit changes:
    1. Find old active assignment (if exists)
    2. Deactivate old assignment (set is_active=false, end_date=now())
    3. Create new assignment (with is_active=true)
    4. Update user cache fields (role, unit_id, current_assignment_id)
    5. Sync Casbin grouping policies (g-rules) if enforcer provided

    Args:
        db: Database session
        user: User object to update
        new_role: New role to assign
        new_unit_id: New unit ID (can be None for non-unit users)
        assigned_by_user_id: ID of admin who made the assignment (None = system/migration)
        enforcer: Casbin enforcer for g-rule sync

    Returns:
        New UserUnitAssignment object if assignment was created, None if skipped

    Note:
        - If user has no unit (new_unit_id is None), we don't create assignment — but the old active one IS still
          closed (step 2 runs first; PR-B lượt 5, Codex 22-11 P1: gỡ đơn vị của Quản lý mà để bản ghi cũ hiệu lực ⇒ bộ chọn
          người nhận vẫn chọn người ấy làm Quản lý đơn vị cũ)
        - This function must be called INSIDE a transaction
        - Caller is responsible for commit/rollback
    """
    now = datetime.now(timezone.utc)

    # ✅ CASBIN SYNC (Phase 7): Ensure g-rules are updated even if no unit assignment
    # This fixes the issue where user has "officer" role in DB but "user" in Casbin
    if enforcer:
        try:
            from app.services.casbin_service import CasbinPolicyService
            casbin_service = CasbinPolicyService(db, enforcer)
            
            # Remove old roles and assign new one
            await casbin_service.remove_user_roles(user.id)
            await casbin_service.assign_role_to_user(user.id, new_role)
            
            log.info(
                "Synced Casbin g-rules for user",
                user_id=user.id,
                new_role=new_role
            )
        except Exception as e:
            # Don't fail the whole transaction if Casbin sync fails, but log critical error
            log.error(
                "Failed to sync Casbin g-rules",
                user_id=user.id,
                role=new_role,
                error=str(e),
                exc_info=True
            )

    # ✅ SPRINT 5: Use Repository for active assignment lookup
    from app.repositories import UserRepository
    user_repo = UserRepository(db)

    # 1. Find and deactivate old active assignment (if exists)
    # PR-B lượt 5 (Codex 22-11 P1): đóng bản ghi đang hiệu lực TRƯỚC nhánh "không đơn vị" — bản cũ trả về sớm ở nhánh ấy
    # (xoá ``user.unit_id`` + ``current_assignment_id``) mà KHÔNG đóng bản ghi ⇒ Quản lý vừa bị gỡ đơn vị vẫn được bộ chọn
    # người nhận (đọc ``user_unit_assignment``) chọn làm Quản lý của đơn vị cũ.
    old_assignment = await user_repo.get_active_assignment_by_user(user.id)

    if old_assignment:
        log.debug(
            "Deactivating old assignment",
            user_id=user.id,
            old_assignment_id=old_assignment.id,
            old_role=old_assignment.role,
            old_unit_id=old_assignment.unit_id
        )
        old_assignment.is_active = False
        old_assignment.end_date = now
        old_assignment.updated_at = now
        db.add(old_assignment)

    # Skip if user has no unit (regular users without unit assignment) — SAU khi đã đóng bản ghi cũ (bước 1).
    if new_unit_id is None:
        log.debug(
            "Skipping assignment creation - user has no unit",
            user_id=user.id,
            role=new_role
        )
        # Still update cache fields
        user.role = new_role
        user.unit_id = None
        user.current_assignment_id = None
        return None

    # 2. Create new active assignment
    new_assignment = models.UserUnitAssignment(
        user_id=user.id,
        unit_id=new_unit_id,
        role=new_role,
        assigned_by_user_id=assigned_by_user_id,
        start_date=now,
        end_date=None,
        is_active=True,
        created_at=now,
        updated_at=now
    )
    db.add(new_assignment)
    await db.flush()  # Get new_assignment.id

    log.info(
        "Created new user assignment",
        user_id=user.id,
        assignment_id=new_assignment.id,
        role=new_role,
        unit_id=new_unit_id,
        assigned_by=assigned_by_user_id
    )

    # 3. Update user cache fields (for Casbin performance)
    user.role = new_role
    user.unit_id = new_unit_id
    user.current_assignment_id = new_assignment.id
    db.add(user)

    return new_assignment


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> models.User:
    """
    Xác thực người dùng.
    ✅ FIXED: Chống Timing Attack bằng cách luôn thực hiện hash comparison.
    """
    user = await get_user_by_username(db, username)

    # (Giữ nguyên logic Timing Attack Fix)
    dummy_hash = "$2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62"
    hash_to_check = user.password_hash if user else dummy_hash
    is_password_valid = verify_password(password, hash_to_check)

    if not user or not is_password_valid:
        # ✅ SỬA LỖI: Xóa `await`
        log.warning(
            "Authentication failed",
            username=username,
            reason="Invalid user or password",
        )
        raise InvalidCredentials()

    # await db.refresh(user)
    log.info("Authentication successful", username=username)  # ✅ SỬA LỖI: Xóa `await`
    return user


# --- Hàm Tạo User ---


async def create_user(db: AsyncSession, user_in: schemas.UserCreate) -> Tuple[models.User, Callable]:
    """
    Create a new user.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (user, post_commit_callback)
    """
    try:
        # ✅ OWASP ASVS §2.1.7: Check password against known breaches
        is_breached, breach_count = await check_password_breached(user_in.password)
        if is_breached:
            raise BadRequest(
                detail=f"This password has appeared in {breach_count:,} data breaches. "
                "Please choose a different password."
            )

        hashed_password = get_password_hash(user_in.password)
        # ✅ SỬA: Dữ liệu đã sạch, chỉ cần model_dump
        db_user = models.User(
            **user_in.model_dump(exclude={"password"}),  # Dùng model_dump cho an toàn
            password_hash=hashed_password,
            role="user",
            status="active",
        )
        db.add(db_user)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_user)

        # ✅ Create post-commit callback (empty - no post-commit actions needed)
        async def _post_commit():
            """Execute after router commits the transaction."""
            pass

        return db_user, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to create user",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


async def create_user_by_admin(
    db: AsyncSession,
    user_in: schemas.AdminUserCreate,
    enforcer: Optional[casbin.AsyncEnforcer] = None,
    avatar_content: Optional[bytes] = None,  # ✅ REFACTORED: bytes instead of UploadFile
    avatar_filename: Optional[str] = None,   # ✅ REFACTORED: filename for validation
    assigned_by_user_id: Optional[int] = None,  # ✅ PHASE 2: Add assigner tracking
) -> Tuple[models.User, Callable]:
    """
    ✅ ATOMIC TRANSACTION (v17 + PHASE 2):
    Create user with atomic DB + Casbin + UserUnitAssignment transaction.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    PHASE 2 Enhancement:
    - Automatically creates UserUnitAssignment if user has unit_id
    - Tracks assignment history from the moment of user creation
    - Maintains temporal data integrity

    Uses nested transaction (savepoint) to ensure all operations
    (DB, Casbin, Assignment) succeed or fail together.

    Returns:
        Tuple of (user, post_commit_callback)
    """
    try:
        hashed_password = get_password_hash(user_in.password)

        # ✅ ATOMIC FIX: Begin nested transaction (savepoint)
        async with db.begin_nested():
            # (1) Create user in DB (with initial cache values)
            db_user = models.User(
                **user_in.model_dump(exclude={"password"}),  # Dùng model_dump
                password_hash=hashed_password,
                avatar_url=None,
                current_assignment_id=None,  # Will be set by helper function
            )

            # ✅ REFACTORED: Use avatar_content + avatar_filename (Issue #3)
            if _co_avatar_duoc_gui(avatar_content, avatar_filename):
                log.debug(
                    "Processing avatar for new admin-created user",
                    filename=avatar_filename,
                )
                new_avatar_url = await file_helpers.save_avatar(
                    content=avatar_content,
                    filename=avatar_filename
                )
                db_user.avatar_url = new_avatar_url
                log.info(
                    "Avatar saved for new user",
                    user=user_in.username,
                    url=new_avatar_url
                )

            db.add(db_user)
            await db.flush()  # Flush to get user.id
            await db.refresh(db_user)

            # (2) ✅ PHASE 2: Create UserUnitAssignment if user has unit
            if db_user.unit_id is not None:
                await _create_or_update_user_assignment(
                    db=db,
                    user=db_user,
                    new_role=db_user.role,
                    new_unit_id=db_user.unit_id,
                    assigned_by_user_id=assigned_by_user_id
                )
                log.info(
                    "UserUnitAssignment created for new user",
                    user_id=db_user.id,
                    role=db_user.role,
                    unit_id=db_user.unit_id
                )

            # (3) Add Casbin grouping policy INSIDE the same transaction
            if enforcer:
                role_name = f"role:{db_user.role}"
                user_subject = f"user:{db_user.id}"

                from app.services.casbin_service import khoa_enforcer

                async with khoa_enforcer(enforcer):
                    added = await enforcer.add_grouping_policy(
                        user_subject, role_name
                    )
                log.debug("Added Casbin grouping policy for new user", added=added)

                # KHÔNG `save_policy()`: `auto_save` đã ghi hàng xuống bảng, còn
                # `save_policy()` là `DELETE FROM casbin_rule` rồi ghi lại toàn
                # bộ model. Chú thích cũ "in SAME transaction" cũng sai: adapter
                # mở session RIÊNG.

                log.info(
                    "Casbin grouping policy added for admin-created user (in transaction)",
                    user_id=db_user.id,
                    role=db_user.role,
                )

            # ✅ If we reach here, all operations succeeded
            # Nested transaction will commit on exit from 'async with' block

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "User created successfully with atomic DB+Assignment+Casbin transaction",
                user_id=db_user.id,
                username=db_user.username,
                role=db_user.role,
                has_assignment=db_user.current_assignment_id is not None
            )

            # ✅ REAL-TIME SYNC: Notify all connected clients
            await emit_data_updated(
                resource_type="user",
                operation="create",
                resource_id=db_user.id,
                data={"username": db_user.username, "role": db_user.role}
            )

        return db_user, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to create user by admin (rolled back atomic transaction)",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Lấy danh sách User (Read-only) ---


async def get_users(
    db: AsyncSession, params: Dict[str, Any], skip: int = 0, limit: int = 100
) -> Tuple[int, List[models.User]]:
    """
    Get users with filtering, sorting, and pagination.

    ✅ SPRINT 2 REFACTORED: Now uses UserRepository for data access.
    
    Supports:
    - Hierarchical unit filter (with include_children)
    - Full-text search (using search_vector)
    - Multi-value filters (role, status)
    - Eager loading for N+1 prevention
    """
    from app.repositories import UserRepository
    
    repo = UserRepository(db)
    
    # Extract params
    unit_id = None
    if "unit_id" in params and params["unit_id"]:
        try:
            unit_id = int(params["unit_id"])
        except ValueError:
            log.warning(f"Invalid unit_id value: {params['unit_id']}")
    
    include_children = str(params.get("include_children", "")).lower() == "true"
    
    return await repo.search_with_hierarchy(
        skip=skip,
        limit=limit,
        role=params.get("role"),
        status=params.get("status"),
        unit_id=unit_id,
        include_children=include_children,
        search=params.get("search"),
        sort_by=params.get("sort", "id"),
        order=params.get("order", "asc"),
    )


async def get_all_users(db: AsyncSession) -> List[models.User]:
    """
    Get all users (for admin sync status).
    Wraps UserRepository.get_all()
    """
    from app.repositories import UserRepository
    repo = UserRepository(db)
    return await repo.get_all()


async def list_users(
    db: AsyncSession,
    unit_id: Optional[int] = None,
    include_children: bool = False,
    is_active: Optional[int] = None,  # Note: Router might pass bool, but Repo uses str/None
    skip: int = 0,
    limit: int = 100,
) -> List[models.User]:
    """
    Get list of users with hierarchical filtering (Router-friendly wrapper).
    Returns just the list of users (ignoring total count).
    """
    from app.repositories import UserRepository
    repo = UserRepository(db)

    # Convert is_active bool to status string if needed, or pass strict params
    # Repo search_with_hierarchy takes 'status' string (active/inactive)
    status_filter = None
    if is_active is not None:
        status_filter = "active" if is_active else "inactive"

    _, users = await repo.search_with_hierarchy(
        skip=skip,
        limit=limit,
        unit_id=unit_id,
        include_children=include_children,
        status=status_filter,
    )
    return users


# --- Hàm Cập nhật User ---


def deactivates_account(status_transition: Optional[Dict[str, Any]]) -> bool:
    """MỘT vị từ "lần cập nhật này đưa tài khoản sang trạng thái KHÔNG hoạt động" cho bước ngắt truy cập của
    ``PUT /api/admin/users/{id}`` (thu hồi mọi phiên + ngắt socket): trạng thái THỰC SỰ đổi và trạng thái mới khác
    ``active``. ``status_transition`` = ``{"old", "new"}`` do :func:`update_user` điền từ giá trị đọc DƯỚI khoá dòng người
    (PR-B lượt 3, Codex lượt 2 điểm chặn 6) — bản nạp từ đầu yêu cầu có thể đã cũ (đọc lúc ``inactive`` → được mở lại →
    bị khoá lại: so với bản cũ là "không đổi" ⇒ bỏ qua ngắt truy cập)."""
    if not status_transition:
        return False
    return status_transition["new"] != status_transition["old"] and status_transition["new"] != "active"


async def update_user(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    enforcer: Optional[casbin.AsyncEnforcer] = None,
    avatar_content: Optional[bytes] = None,  # ✅ REFACTORED: bytes instead of UploadFile
    avatar_filename: Optional[str] = None,   # ✅ REFACTORED: filename for validation
    assigned_by_user_id: Optional[int] = None,  # ✅ PHASE 2: Track who made the assignment
    request_meta: Optional[Any] = None,  # PR-B Q4: IP / User-Agent cho nhật ký tự thu hồi quyền duyệt chéo
    status_transition_out: Optional[Dict[str, Any]] = None,  # PR-B lượt 3: chuyển trạng thái THỰC TẾ (đọc dưới khoá)
) -> Tuple[models.User, Callable]:
    """
    ``status_transition_out`` (PR-B lượt 3, Codex lượt 2 điểm chặn 6): khi yêu cầu có ``status``, hàm điền
    ``{"old": <trạng thái đọc DƯỚI khoá dòng người>, "new": <trạng thái mới>}`` — router quyết thu hồi phiên + ngắt socket
    bằng :func:`deactivates_account` trên CHÍNH giá trị này, không bằng bản nạp từ đầu yêu cầu.

    ✅ ATOMIC TRANSACTION (v17 + PHASE 2):
    Update user with atomic DB + Casbin + UserUnitAssignment transaction.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    PHASE 2 Enhancement:
    - Detects role/unit_id changes and creates temporal history
    - Deactivates old UserUnitAssignment and creates new one
    - Maintains cache fields (user.role, user.unit_id) for Casbin performance
    - Tracks who made the assignment (assigned_by_user_id)

    This implements the 6-step atomic transaction pattern:
    1. Find old UserUnitAssignment (is_active=true)
    2. Set is_active=false, end_date=now() for old assignment
    3. CREATE new UserUnitAssignment with new role/unit
    4. Get new assignment ID
    5. UPDATE user cache fields (role, unit_id, current_assignment_id)
    6. Sync Casbin grouping policies

    Uses nested transaction (savepoint) to ensure all operations
    succeed or fail together, preventing inconsistency.

    Returns:
        Tuple of (user, post_commit_callback)
    """
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        if "email" in update_data and update_data["email"] != db_user.email:
            existing_user = await get_user_by_email(db, update_data["email"])
            if existing_user and existing_user.id != user_id_for_logging:
                raise DuplicateResourceError(
                    detail="Email already registered by another user"
                )

        # GĐ1b PR-B Q4 (owner 20-11 / 21-11): đổi vai khỏi Cán bộ / khoá tài khoản ⇒ tự thu hồi MỌI quyền duyệt chéo chưa hết
        # hạn, CÙNG giao dịch (router commit một lần). Đặt TRƯỚC đồng bộ Casbin (adapter ghi bằng phiên RIÊNG, không rollback
        # được): lỗi ghi nhật ký thu hồi ⇒ ném ra trước khi Casbin bị đụng ⇒ rollback cả đổi vai / khoá lẫn thu hồi.
        # Vai / trạng thái CŨ đọc DƯỚI khoá dòng người trong hàm (không dùng ``db_user`` nạp từ đầu yêu cầu).
        from app.services.document_cross_review_service import revoke_grants_on_account_change

        # PR-B lượt 4 (rà nhánh "CHỈ đổi đơn vị"): khoá dòng người ``FOR NO KEY UPDATE`` cho MỌI lần cập nhật, không chỉ
        # khi đổi vai / trạng thái. Đổi đơn vị đi qua ``_create_or_update_user_assignment`` — hàm ấy tạo bản ghi phân công
        # MỚI mang ``role`` = vai hiện hành mà hàm này tính ⇒ tính từ bản nạp đầu yêu cầu thì một lệnh đổi vai đã commit trong
        # lúc ấy để lại bản ghi phân công còn hiệu lực mang vai CŨ (``user.role`` thì không bị ghi đè — ORM bỏ UPDATE khi gán
        # trùng giá trị đã nạp; đo bằng kiểm ngược l4_m7b 22-11).
        # PR-B lượt 5 (Codex 22-11 P2): khoá CÙNG người thao tác (khoá ngoại phân công / thu hồi / nhật ký của router) theo
        # id TĂNG, TRƯỚC mọi câu ghi — cùng chiều K4 (``user_deletion_policy.lock_users_in_id_order``).
        from app.services.user_deletion_policy import changes_user_key_columns, lock_users_in_id_order

        # PR-B lượt 6 (Codex 22-11 H1): đổi THẬT cột khoá (email) ⇒ ``UPDATE`` sẽ cần ``FOR UPDATE`` lúc flush ⇒ khoá
        # người đích ``FOR UPDATE`` ngay từ đầu (vẫn theo id tăng), không để PostgreSQL nâng khoá giữa chừng.
        doi_cot_khoa = changes_user_key_columns(db_user, update_data)
        await lock_users_in_id_order(
            db,
            target_ids=[db_user.id],
            referenced_ids=[assigned_by_user_id],
            key_update_ids=[db_user.id] if doi_cot_khoa else [],
        )
        await revoke_grants_on_account_change(
            db,
            user_id=db_user.id,
            new_role=update_data.get("role"),
            new_status=update_data.get("status"),
            actor_id=assigned_by_user_id,
            request_meta=request_meta,
        )
        # PR-B lượt 2 + 4: đọc lại vai / đơn vị / trạng thái HIỆN HÀNH (dòng đã khoá ở trên) — quyết "vai / đơn vị có đổi
        # không" bên dưới bằng cùng giá trị với quyết định thu hồi; bản nạp từ đầu yêu cầu có thể đã cũ.
        await db.refresh(db_user, attribute_names=["role", "unit_id", "status"])
        if "status" in update_data and status_transition_out is not None:
            # PR-B lượt 3: trạng thái CŨ = giá trị vừa đọc lại dưới khoá dòng người (khoá giữ tới commit).
            status_transition_out.update(old=db_user.status, new=update_data["status"])

        # ✅ PHASE 2: Track role AND unit_id changes BEFORE updating
        old_db_role = db_user.role
        old_db_unit_id = db_user.unit_id
        new_db_role = update_data.get("role", old_db_role)  # Default to current if not changing
        new_db_unit_id = update_data.get("unit_id", old_db_unit_id)  # Default to current

        user_subject = f"user:{db_user.id}"
        role_changed = new_db_role != old_db_role
        unit_changed = new_db_unit_id != old_db_unit_id
        assignment_changed = role_changed or unit_changed

        # ✅ ATOMIC FIX: Begin nested transaction (savepoint)
        # This ensures DB + Assignment + Casbin operations are atomic
        async with db.begin_nested():
            # (1) Update user fields (EXCEPT role/unit_id - handled by assignment helper)
            # Nullable columns admin can clear by sending explicit `null`. Other
            # fields skip null (treated as "field not changed" rather than wipe
            # a non-nullable column). `exclude_unset=True` already filters
            # fields the client did not touch.
            _CLEARABLE_USER_FIELDS = {"full_name", "phone_number", "skills", "max_capacity", "avatar_url"}
            for field, value in update_data.items():
                # Skip role/unit_id - will be set by _create_or_update_user_assignment
                if field in ("role", "unit_id"):
                    continue
                if value is None and field not in _CLEARABLE_USER_FIELDS:
                    continue
                setattr(db_user, field, value)

            # ✅ REFACTORED: Use avatar_content + avatar_filename (Issue #3)
            if _co_avatar_duoc_gui(avatar_content, avatar_filename):
                log.debug(
                    "Processing avatar update for user",
                    user_id=db_user.id,
                    filename=avatar_filename,
                )
                new_avatar_url = await file_helpers.save_avatar(
                    content=avatar_content,
                    filename=avatar_filename,
                    old_avatar_url=db_user.avatar_url
                )
                db_user.avatar_url = new_avatar_url
                log.info(
                    "Avatar updated successfully for user",
                    user_id=db_user.id,
                    url=new_avatar_url,
                )

            # (2) ✅ PHASE 2: Handle role/unit assignment changes with temporal history
            if assignment_changed:
                log.info(
                    "Assignment changed - creating temporal history",
                    user_id=user_id_for_logging,
                    old_role=old_db_role,
                    new_role=new_db_role,
                    old_unit=old_db_unit_id,
                    new_unit=new_db_unit_id
                )

                # This function will:
                # - Deactivate old assignment
                # - Create new assignment
                # - Update cache fields (user.role, user.unit_id, user.current_assignment_id)
                await _create_or_update_user_assignment(
                    db=db,
                    user=db_user,
                    new_role=new_db_role,
                    new_unit_id=new_db_unit_id,
                    assigned_by_user_id=assigned_by_user_id,
                    # PR-B lượt 4 (Codex lượt 4 C1a): KHÔNG truyền enforcer — đồng bộ Casbin của hàm này (gỡ / gán qua bộ nhớ
                    # worker, NUỐT lỗi) bị thay bằng bước (3) bên dưới: ghi ``casbin_rule`` trong giao dịch, lỗi ⇒ không commit.
                    enforcer=None,
                )

            db.add(db_user)
            await db.flush()  # Flush to get updated values
            await db.refresh(db_user)

            # (3) Sync Casbin INSIDE the same transaction (if role changed)
            # PR-B lượt 4 (Codex lượt 3 điểm chặn 1 + Codex lượt 4 C1a, C2): bảng ``casbin_rule`` — nguồn CHUNG mọi worker —
            # ghi TRONG giao dịch của router, KHÔNG qua bộ nhớ enforcer của worker này (bản riêng, có thể cũ: thiếu vai worker
            # khác vừa gán ⇒ dòng ấy sót lại). Đọc + KHOÁ ``FOR UPDATE`` mọi dòng ``g, user:<id>, …`` hiện có, xoá ĐÚNG các dòng
            # ấy theo id (dòng chèn sau lần đọc là thao tác đến sau, không bị xoá), chèn vai mới — người dùng còn đúng MỘT vai
            # Casbin = vai CSDL mới (như hành vi cũ: gỡ mọi vai rồi gán vai mới). Lỗi ở đây KHÔNG bị nuốt ⇒ ném ra ⇒ router
            # không commit gì: vai CSDL, tự thu hồi + nhật ký (Q4) và ``casbin_rule`` cùng giữ nguyên. Bộ nhớ enforcer của
            # worker này nạp lại SAU commit (callback).
            if role_changed and enforcer:
                log.info(
                    "Role changed, syncing Casbin inside transaction",
                    user_id=user_id_for_logging,
                    old=old_db_role,
                    new=new_db_role
                )
                from app.repositories import UserRepository

                grouping_repo = UserRepository(db)
                rows = await grouping_repo.lock_grouping_rows(db_user.id)
                await grouping_repo.delete_grouping_ids([row_id for row_id, _ in rows])
                await grouping_repo.add_grouping(db_user.id, f"role:{new_db_role}")
                log.info(
                    "Casbin grouping rows replaced (in transaction)",
                    user_id=user_id_for_logging,
                    removed=[role for _, role in rows],
                    new_casbin_role=f"role:{new_db_role}",
                )

            # ✅ If we reach here, all operations succeeded
            # Nested transaction will commit on exit from 'async with' block

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            if role_changed and enforcer:
                # PR-B lượt 4: ``casbin_rule`` đã đổi TRONG giao dịch vừa commit ⇒ nạp lại bộ nhớ enforcer CỦA WORKER NÀY.
                # Nạp hỏng chỉ để bộ nhớ worker này cũ (như mọi worker khác) — CSDL đã đúng, không đường đổi vai CSDL nào
                # quyết từ bộ nhớ ⇒ ghi lỗi, không đổi kết quả đã commit.
                from app.services.casbin_service import dong_bo_tu_nguon_ben_vung

                loi_nap = await dong_bo_tu_nguon_ben_vung(enforcer)
                if loi_nap is not None:
                    log.error("update_user: reload enforcer after commit failed", user_id=user_id_for_logging, error=loi_nap)
            log.info(
                "User updated successfully with atomic DB+Assignment+Casbin transaction",
                user_id=user_id_for_logging,
                role_changed=role_changed,
                unit_changed=unit_changed,
                assignment_changed=assignment_changed
            )

            # ✅ REAL-TIME SYNC: Notify all connected clients
            await emit_data_updated(
                resource_type="user",
                operation="update",
                resource_id=db_user.id,
                data={
                    "username": db_user.username,
                    "full_name": db_user.full_name,
                    "role": db_user.role,
                    "unit_id": db_user.unit_id,
                    "status": db_user.status
                }
            )

        return db_user, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to update user (rolled back atomic transaction)",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_profile(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    avatar_content: Optional[bytes] = None,  # ✅ REFACTORED: bytes instead of UploadFile
    avatar_filename: Optional[str] = None,   # ✅ REFACTORED: filename for validation
) -> Tuple[models.User, Callable]:
    """
    Update user profile.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (user, post_commit_callback)
    """
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        # `email` is non-nullable; user can not clear it via this profile
        # endpoint. `full_name` and `phone_number` are nullable — explicit
        # `null` clears them.
        for field, value in update_data.items():
            if field == "email":
                if value is not None:
                    setattr(db_user, field, value)
            elif field in ("full_name", "phone_number"):
                setattr(db_user, field, value)

        # ✅ REFACTORED: Use avatar_content + avatar_filename (Issue #3)
        if _co_avatar_duoc_gui(avatar_content, avatar_filename):
            log.debug(
                "Processing profile avatar update",
                user_id=user_id_for_logging,
                filename=avatar_filename,
            )
            new_avatar_url = await file_helpers.save_avatar(
                content=avatar_content,
                filename=avatar_filename,
                old_avatar_url=db_user.avatar_url
            )
            db_user.avatar_url = new_avatar_url
            log.info(
                "Profile avatar updated successfully",
                user_id=user_id_for_logging,
                url=new_avatar_url,
            )

        db.add(db_user)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_user)

        # ✅ Create post-commit callback (empty - no post-commit actions needed)
        async def _post_commit():
            """Execute after router commits the transaction."""
            pass

        return db_user, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to update profile",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Xóa User ---


async def delete_user(
    db: AsyncSession, user_id: int, actor_id: Optional[int] = None
) -> Tuple[None, Callable]:
    """
    Delete a user.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    GĐ1b K4 (đặc tả bản 3.6 §4.3): đi qua ``assert_user_deletable`` — khoá người bị xoá (+ admin đang hoạt động nếu cần)
    trong MỘT câu, guard "admin cuối", kiểm MỌI khoá ngoại tới ``user`` CHỈ ĐỌC; không đạt ⇒ 409, không câu ghi nào.
    Mốc nền V5 (``221a757d``): có ``assignment_log`` / tư vấn ⇒ 500; có lead ⇒ lead bị gỡ âm thầm.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        # ✅ SPRINT 5: Use Repository for eager loading
        from app.repositories import UserRepository
        from app.services.user_deletion_policy import assert_user_deletable

        user_repo = UserRepository(db)

        deletable = await assert_user_deletable(db, [user_id], actor_id)
        if not deletable:
            raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")

        # ✅ FIX MissingGreenlet: Eager load cascade-delete relationships
        # Without this, SQLAlchemy tries to lazy-load during cascade delete,
        # which fails in async mode with "greenlet_spawn has not been called"
        user_to_delete = await user_repo.get_user_for_delete(user_id)

        if not user_to_delete:
            raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")

        # Save data for emit before deletion
        deleted_username = user_to_delete.username

        await db.delete(user_to_delete)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            # ✅ REAL-TIME SYNC: Notify all connected clients about the deletion
            await emit_data_updated(
                resource_type="user",
                operation="delete",
                resource_id=user_id,
                data={"username": deleted_username}
            )

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to delete user", user_id=user_id, error=str(e), exc_info=True
        )  # ✅ SỬA LỖI: Xóa `await`
        raise e


async def handle_forgot_password(db: AsyncSession, email_in: str):
    from ..celery_utils import send_password_reset_email_task

    cleaned_email = email_in.strip()

    # ✅ THÊM RATE LIMIT THEO EMAIL
    email_rate_limit_key = f"rate_limit:forgot_pw:{cleaned_email}"
    try:
        # Giới hạn 5 yêu cầu mỗi giờ
        current_count_str = await safe_redis_get(email_rate_limit_key)
        current_count = int(current_count_str) if current_count_str else 0

        if current_count >= 5:
            log.warning(
                "Forgot password rate limit (by email) exceeded", email=cleaned_email
            )
            # Vẫn trả về thành công (không để lộ thông tin)
            return

        # Tăng bộ đếm, set TTL 1 giờ (3600s)
        # Dùng pipeline để đảm bảo INCR và EXPIRE là atomic
        # ✅ FIX: Use safe_redis_pipeline instead of redis_client.pipeline
        async with safe_redis_pipeline() as pipe:
            pipe.incr(email_rate_limit_key)
            pipe.expire(email_rate_limit_key, 3600)
            await pipe.execute()

    except Exception as e_redis:
        # SECURITY: Fail-closed for forgot-password throttling.
        # If Redis is down, we can't verify rate limits, so block the request
        # to prevent email flooding. The user sees the generic 202 response
        # (no enumeration leak), they just won't receive an email.
        log.error(
            "Failed to check/set email rate limit for forgot_password — fail-closed",
            email=cleaned_email,
            error=str(e_redis),
        )
        return  # Silently return (same as rate-limited response)

    # (Logic cũ tiếp tục)
    user = await get_user_by_email(db, email=email_in)
    if not user:
        log.debug("User not found for forgot password request", email=cleaned_email)
        return

    log.info(
        "User found for forgot password request. Sending reset email.", user_id=user.id
    )

    # SECURITY: Invalidate any outstanding reset tokens for this user
    # by bumping a per-user generation counter. Only the token issued with
    # the latest generation will be accepted by reset_password().
    gen_key = f"reset_gen:{user.id}"
    try:
        async with safe_redis_pipeline() as pipe:
            pipe.incr(gen_key)
            pipe.expire(gen_key, 1800)  # 30min — matches token expiry
            results = await pipe.execute()
        current_gen = int(results[0])
    except Exception as e:
        # SECURITY: Fail-closed. If we can't guarantee latest-token-only
        # semantics, don't send the email. User sees generic 202 (no leak).
        log.error(
            "Failed to bump reset generation counter — email NOT sent (fail-closed)",
            user_id=user.id, error=str(e),
        )
        return

    token = create_password_reset_token(email=user.email, generation=current_gen)
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

    send_password_reset_email_task.delay(
        email_to=user.email, reset_url=reset_url, username=user.username
    )


async def reset_password(
    db: AsyncSession, token: str, new_password: str
) -> Tuple[models.User, Callable]:
    """
    Reset password from token.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (user, post_commit_callback)
    """
    try:
        # SECURITY: Atomic single-use claim via SET NX.
        # Only one request can claim a given token — all concurrent
        # duplicates get NX=False and are rejected immediately.
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:32]
        used_key = f"reset_token_used:{token_hash}"
        try:
            claimed = await redis_client.set(used_key, "1", nx=True, ex=1800)
        except Exception as redis_err:
            log.error("Redis SET NX failed for reset token claim — fail-closed",
                      error=str(redis_err))
            raise InvalidToken(detail="Unable to process reset. Please try again.")
        if not claimed:
            log.warning("Reset token reuse attempt blocked (SET NX)", token_fp=token_fingerprint(token))
            raise InvalidToken(detail="This reset link has already been used")

        token_data = verify_password_reset_token(token)
        if not token_data:
            log.warning(
                "Invalid reset token attempt", token_fp=token_fingerprint(token)
            )
            raise InvalidToken()

        email = token_data["email"]
        token_gen = token_data.get("gen", 1)

        user = await get_user_by_email(db, email=email)
        if not user:
            log.warning(
                "Reset token for non-existent user", email=email
            )
            raise ResourceNotFoundError(
                detail="User associated with this token not found."
            )

        # SECURITY: Verify token generation — only the latest reset link is valid
        gen_key = f"reset_gen:{user.id}"
        try:
            current_gen_str = await safe_redis_get(gen_key)
            current_gen = int(current_gen_str) if current_gen_str else None
            if current_gen is not None and token_gen < current_gen:
                log.warning(
                    "Stale reset token rejected (superseded by newer request)",
                    user_id=user.id,
                    token_gen=token_gen,
                    current_gen=current_gen,
                )
                raise InvalidToken(detail="This reset link has been superseded by a newer request")
        except InvalidToken:
            raise
        except Exception as e:
            # Redis down — fail-closed: reject token if we can't verify generation
            log.error("Failed to verify reset token generation", user_id=user.id, error=str(e))
            raise InvalidToken(detail="Unable to verify reset link. Please request a new one.")

        # ✅ SECURITY: Prevent resetting to the same password
        # Even in forgot-password flow, same password is a security risk
        if verify_password(new_password, user.password_hash):
            raise BadRequest(detail="New password must be different from your current password")

        # ✅ OWASP ASVS §2.1.7: Check password against known breaches
        is_breached, breach_count = await check_password_breached(new_password)
        if is_breached:
            raise BadRequest(
                detail=f"This password has appeared in {breach_count:,} data breaches. "
                "Please choose a different password."
            )

        user.password_hash = get_password_hash(new_password)

        # ✅ SECURITY FIX: Clear password_reset_required flag
        # This is important because forgot-password flow should also clear this flag
        # (similar to change_password in auth.py router)
        if hasattr(user, 'password_reset_required') and user.password_reset_required:
            user.password_reset_required = False
            log.info("Cleared password_reset_required flag via reset_password", user_id=user.id)

        db.add(user)

        # Token already claimed atomically via SET NX at the top of this function.
        # No additional Redis write needed here.

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("User password reset successfully", user_id=user.id)

        return user, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to reset password", token=token, error=str(e), exc_info=True
        )  # ✅ SỬA LỖI: Xóa `await`
        raise e


async def change_password(
    db: AsyncSession, user: models.User, old_password: str, new_password: str
) -> Tuple[None, Callable]:
    """
    User changes their own password.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    user_id_for_logging = user.id
    try:
        if not verify_password(old_password, user.password_hash):
            raise BadRequest(detail="Incorrect old password")

        # ✅ SECURITY: Prevent setting the same password
        # This is especially important when password_reset_required=true (security incident)
        if verify_password(new_password, user.password_hash):
            raise BadRequest(detail="New password must be different from your current password")

        # ✅ OWASP ASVS §2.1.7: Check password against known breaches
        is_breached, breach_count = await check_password_breached(new_password)
        if is_breached:
            raise BadRequest(
                detail=f"This password has appeared in {breach_count:,} data breaches. "
                "Please choose a different password."
            )

        user.password_hash = get_password_hash(new_password)
        db.add(user)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("User changed password successfully", user_id=user_id_for_logging)

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to change password",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


async def remove_user_from_global_blacklist(user_id: int):
    """Xóa user khỏi global blacklist (thường gọi sau khi login thành công)."""
    blacklist_key = f"user_blacklist:{user_id}"
    try:
        deleted_count = await safe_redis_delete(blacklist_key)
        if deleted_count > 0:
            log.info(
                "Removed user from global blacklist", user_id=user_id
            )  # ✅ SỬA LỖI: Xóa `await`
    except Exception as e:
        log.error(
            "Failed to remove user from global blacklist", user_id=user_id, error=str(e)
        )  # ✅ SỬA LỖI: Xóa `await`
        raise


async def set_password_by_admin(
    db: AsyncSession, user_id: int, new_password: str
) -> Tuple[models.User, Callable]:
    """
    Admin sets password for a user.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (user, post_commit_callback)
    """
    try:
        user = await get_user_by_id(db, user_id)
        
        # ✅ SECURITY: Prevent setting the same password (for consistency)
        if verify_password(new_password, user.password_hash):
            raise BadRequest(detail="New password must be different from the current password")

        user.password_hash = get_password_hash(new_password)
        db.add(user)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "Admin set password for user successfully",
                admin_user="admin",
                user_id=user.id,
            )

        return user, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to set password by admin",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def invalidate_all_sessions(
    db: AsyncSession,
    user: models.User,
    *,
    reason: str = "Password changed",
    fail_on_cache_cleanup: bool = False,
) -> Callable:
    """
    (V5 - Fixed) Vô hiệu hóa tất cả các phiên hoạt động.
    Sửa lỗi Race Condition bằng cách khóa (lock) và cập nhật DB trong 1 transaction.

    Does NOT commit. Returns the post-commit callback (F108 sibling): the
    caller commits, THEN awaits it — the user's sockets are cut server-side
    only once the revoke is durable. A rolled-back caller never runs it.
    """
    revoked_jtis = []
    user_id = user.id
    now = datetime.now(timezone.utc)
    max_token_ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    safe_ttl = max(60, max_token_ttl)

    try:
        # 1. Bắt đầu transaction và LẤY KHÓA
        # ✅ FIX: Use begin_nested() (savepoint) if already in transaction
        # 1. Bắt đầu transaction và LẤY KHÓA
        # ✅ FIX: Use begin_nested() (savepoint) if already in transaction
        async with db.begin_nested():
            # ✅ SPRINT 7: Use SessionRepository
            from app.repositories import SessionRepository
            session_repo = SessionRepository(db)
            
            all_sessions = await session_repo.get_active_sessions_for_update(user_id)

            if not all_sessions:
                log.info("No active sessions to invalidate", user_id=user_id)
            else:
                log.info(
                    f"Found {len(all_sessions)} active sessions to invalidate",
                    user_id=user_id,
                )
                for session in all_sessions:
                    # 2. ✅ CẬP NHẬT DATABASE
                    session.revoked_at = now
                    db.add(session)
                    revoked_jtis.append(session.refresh_jti)

            # 3. ✅ SET GLOBAL BLACKLIST (vẫn trong transaction)
            # Điều này ngăn chặn login/refresh MỚI trước khi transaction commit
            try:
                blacklist_key = f"user_blacklist:{user_id}"
                await safe_redis_set(blacklist_key, "sessions_invalidated", ex=safe_ttl)
                log.info(
                    "User added to global blacklist (in transaction)", user_id=user_id
                )
            except Exception as e_redis_set:
                log.error(
                    "CRITICAL: Failed to add user to global blacklist, rolling back DB",
                    user_id=user_id,
                    error=str(e_redis_set),
                )
                # Ném lỗi để rollback transaction
                raise CacheServiceError(
                    detail="Failed to invalidate sessions in cache",
                    context={
                        "operation": "redis_blacklist",
                        "user_id": user_id,
                        "error": chu_loi_an_toan(e_redis_set),  # V6 vòng 5b
                    }
                )

        # 4. Savepoint released here — the session-revoke rows are STAGED in the
        #    caller's OUTER transaction (NOT committed yet; the caller commits).
        log.info(
            "Session-revoke staged in caller transaction (savepoint released)",
            user_id=user_id,
        )

        # 5. ✅ XÓA REDIS KEYS (SAU KHI COMMIT THÀNH CÔNG)
        if revoked_jtis:
            try:
                async with safe_redis_pipeline(transaction=True) as pipe:
                    for jti in revoked_jtis:
                        pipe.delete(f"session:{jti}")
                        pipe.set(f"blacklist:{jti}", "password_changed", ex=safe_ttl)
                    await pipe.execute()
                log.info(
                    f"Invalidated {len(revoked_jtis)} session keys in Redis",
                    user_id=user_id,
                )
            except Exception as e_redis_del:
                log.error(
                    "Failed to clear session keys from Redis",
                    user_id=user_id,
                    error=str(e_redis_del),
                )
                # STRICT (offboarding): a Redis cleanup miss leaves a phantom
                # session:{jti} that can resurrect an old access token after the
                # account is reactivated + logs in (which clears user_blacklist).
                # Raise so the caller rolls back the status change → fail-closed.
                # Default path (change_password) stays best-effort: the DB
                # session-revoke is staged in the CALLER's transaction (savepoint
                # released into it above, NOT yet committed) and is durable only
                # if the caller commits.
                if fail_on_cache_cleanup:
                    raise CacheServiceError(
                        detail="Failed to clear session keys from cache",
                        context={
                            "operation": "redis_session_cleanup",
                            "user_id": user_id,
                        },
                    )

        # 6. Socket enforcement is POST-COMMIT (F108 sibling). It used to be
        #    dispatched HERE, while the revoke above was still only staged in
        #    the caller's transaction: a caller that then rolled back had
        #    already told every socket of the user it was logged out. Now the
        #    caller commits FIRST, then runs this callback — the project's
        #    ``(result, post_commit_callback)`` contract. Offboarding does not
        #    run it: it already cut the user's sockets strictly BEFORE its
        #    commit (``app/routers/admin/users.py``), rollback on failure.
        async def _post_commit():
            """Run ONLY after the caller committed the revoke: every socket of
            the user is notified and disconnected on every live worker
            (``emit_force_logout`` ALL branch, ACK-confirmed or logged as not)."""
            try:
                await dispatcher.dispatch(
                    TransportEvents.USER_FORCE_LOGOUT,
                    user_id=user_id,
                    reason=reason,
                    revoked_jtis=[]  # All sessions revoked
                )
                socket_events_emitted_total.labels(event_type="force_logout_all").inc()
                log.info("Dispatched force_logout event", user_id=user_id, reason=reason)
            except Exception as e_dispatch:
                socket_emit_failures_total.labels(event_type="force_logout_all").inc()
                log.error(
                    "Failed to dispatch logout event", error=str(e_dispatch)
                )

        return _post_commit

    except Exception as e:
        # Rollback tự động nếu lỗi trong `async with db.begin()`
        if not isinstance(e, BaseAppException):
            log.error(
                "Failed to invalidate sessions",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            raise UserServiceError(
                detail="Could not invalidate sessions",
                context={"user_id": user_id, "error": chu_loi_an_toan(e)}  # V6 vòng 5b
            )
        else:
            raise  # Re-raise custom exceptions (e.g., CacheServiceError)


async def logout_user(db: AsyncSession, user: models.User) -> Tuple[None, Callable]:
    """
    Logout user (legacy function).

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        user.active_jti = None
        db.add(user)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("User logged out successfully (legacy function)", user_id=user.id)

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to logout user (legacy function)",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )  # ✅ SỬA LỖI: Xóa `await`
        raise e


# --- Bulk Action ---


async def perform_bulk_action(
    db: AsyncSession,
    action: str,
    user_ids: List[int],
    admin_user: models.User,
    new_status: Optional[str] = None,
    request_meta: Optional[Any] = None,  # PR-B Q4: IP / User-Agent cho nhật ký tự thu hồi quyền duyệt chéo
) -> Tuple[str, Callable]:
    """
    Perform bulk action on users.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (message, post_commit_callback)
    """
    try:
        if action == "change_status":
            if new_status not in ["active", "pending", "banned"]:
                log.warning(  # ✅ SỬA LỖI: Xóa `await`
                    "Bulk action failed: Invalid status value provided.",
                    action=action,
                    provided_status=new_status,
                    admin_id=admin_user.id,
                )
                raise BadRequest(detail=f"Invalid status value: {new_status}")
        elif action not in ["delete"]:
            log.warning(  # ✅ SỬA LỖI: Xóa `await`
                "Bulk action failed: Unsupported action.",
                action=action,
                admin_id=admin_user.id,
            )
            raise BadRequest(detail=f"Unsupported bulk action: {action}.")

        # ✅ SPRINT 5: Use Repository for user loading
        from app.repositories import UserRepository
        user_repo = UserRepository(db)
        
        # GĐ1b K4 (§4.3): nhánh xoá KIỂM TRƯỚC mọi câu ghi — ``assert_user_deletable`` khoá + kiểm toàn bộ danh sách;
        # một người không đạt ⇒ 409 cả lệnh (không gỡ lead, không xoá ai, router không dọn Casbin).
        skipped_users = []
        if action == "delete":
            from app.services.user_deletion_policy import assert_user_deletable

            if admin_user.id in set(user_ids):
                log.warning(
                    "Admin attempted to delete self during bulk action, skipping.",
                    admin_id=admin_user.id,
                )
                skipped_users.append(admin_user.id)
            ids_to_delete = await assert_user_deletable(db, user_ids, admin_user.id)
            # ✅ FIX MissingGreenlet: Eager load cascade-delete relationships for delete action
            users_to_process = (
                await user_repo.get_users_by_ids_for_delete(ids_to_delete) if ids_to_delete else []
            )
        else:
            users_to_process = await user_repo.get_by_ids(user_ids)

        if not users_to_process and not skipped_users:
            log.info(
                "Bulk action: No users found matching provided IDs.",
                user_ids=user_ids,
                admin_id=admin_user.id,
            )
            # ✅ FIX Bug #2: Return Tuple instead of string
            async def _noop():
                pass
            return "No users found for the provided IDs. 0 users affected.", _noop, []

        processed_count = 0
        message = ""
        disconnect_ids: list = []  # status-changed ids the router must force-disconnect
        if action == "delete":
            for user in users_to_process:
                await db.delete(user)  # Mark user for deletion
                processed_count += 1

            # Build message with details
            message = f"Successfully deleted {processed_count} users."
            if skipped_users:
                message += f" Skipped {len(skipped_users)} users (cannot delete self)."

            log.info(
                "Admin bulk deleted users",
                admin_id=admin_user.id,
                deleted_ids=[u.id for u in users_to_process],
                skipped_ids=skipped_users,
            )

        elif action == "change_status":
            # GĐ1b PR-B Q4 (owner 20-11): khoá tài khoản HÀNG LOẠT ⇒ tự thu hồi quyền duyệt chéo của TỪNG người, CÙNG giao
            # dịch, TRƯỚC khi đổi trạng thái. Đi theo id TĂNG (mỗi người: dòng user → dòng quyền) ⇒ hai lệnh hàng loạt chồng
            # nhau khoá cùng chiều. Cùng điều kiện bỏ qua với vòng đổi trạng thái bên dưới (tự khoá chính mình).
            from app.services.document_cross_review_service import revoke_grants_on_account_change
            from app.services.user_deletion_policy import lock_users_in_id_order

            def _tu_khoa_minh(u: models.User) -> bool:
                return u.id == admin_user.id and new_status in ["banned", "pending"]

            # PR-B lượt 5 (Codex 22-11 P2): khoá TRƯỚC toàn tập (người đổi trạng thái ∪ Admin bấm — khoá ngoại thu hồi /
            # nhật ký) theo id TĂNG, rồi mới ghi ai — cùng chiều K4. Khoá lại trong ``revoke_grants_on_account_change`` là no-op.
            await lock_users_in_id_order(
                db,
                target_ids=[u.id for u in users_to_process if not _tu_khoa_minh(u)],
                referenced_ids=[admin_user.id],
            )
            for user in sorted(users_to_process, key=lambda u: u.id):
                if _tu_khoa_minh(user):
                    continue
                await revoke_grants_on_account_change(
                    db,
                    user_id=user.id,
                    new_status=new_status,
                    actor_id=admin_user.id,
                    request_meta=request_meta,
                )
                # PR-B lượt 2: trạng thái HIỆN HÀNH (dòng vừa khoá) cho phép so "có đổi không" ở vòng dưới — cùng giá trị với
                # quyết định thu hồi; bản nạp từ đầu yêu cầu có thể đã cũ.
                await db.refresh(user, attribute_names=["status", "role"])
            ids_changed = []
            skipped_users = []
            for user in users_to_process:
                # ✅ FIX Bug #1: Prevent admin from banning/pending themselves
                if user.id == admin_user.id and new_status in ["banned", "pending"]:
                    log.warning(
                        "Admin attempted to ban/pend self during bulk action, skipping.",
                        admin_id=admin_user.id,
                    )
                    skipped_users.append(user.id)
                    continue
                if user.status != new_status:
                    user.status = new_status
                    db.add(user)
                    ids_changed.append(user.id)
                    processed_count += 1
                else:
                    log.debug(
                        "Skipping status update for user already in desired state.",
                        user_id=user.id,
                        status=new_status,
                    )

            message = f"Successfully updated status to '{new_status}' for {processed_count} users."
            if ids_changed:
                log.info(  # ✅ SỬA LỖI: Xóa `await`
                    "Admin bulk changed user status",
                    admin_id=admin_user.id,
                    changed_ids=ids_changed,
                    new_status=new_status,
                )

            # Revoke sessions for accounts moved to a NON-active status. Persist
            # the status (flush ⇒ row lock) BEFORE revoking so a concurrent login
            # is serialized on the locked row (flush-before-revoke, P0). Strict
            # cache cleanup so a Redis miss fails the whole bulk → router rollback.
            # Server-side socket force-disconnect is done by the ROUTER (transport
            # boundary): this service returns the ids to disconnect.
            if new_status != "active" and ids_changed:
                await db.flush()
                by_id = {u.id: u for u in users_to_process}
                for uid in sorted(ids_changed):
                    u = by_id.get(uid)
                    if u is not None:
                        # Its post-commit callback is not run: the router cuts
                        # these users strictly BEFORE commit (offboarding).
                        await invalidate_all_sessions(
                            db,
                            u,
                            reason="Account deactivated by administrator",
                            fail_on_cache_cleanup=True,
                        )
                disconnect_ids = sorted(ids_changed)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback (empty - no post-commit actions needed)
        async def _post_commit():
            """Execute after router commits the transaction."""
            pass

        return message, _post_commit, disconnect_ids

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(  # ✅ SỬA LỖI: Xóa `await`
            "Failed to perform bulk action",
            action=action,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        if isinstance(e, (BadRequest, ResourceNotFoundError)):
            raise e
        else:
            raise
async def stream_users_csv(
    db: AsyncSession, params: Dict[str, Any]
) -> AsyncGenerator[str, None]:
    """
    Stream tất cả user ra dưới dạng CSV, áp dụng các filter.
    Hàm này là một async generator, yield từng dòng CSV.
    """
    log.info("Starting CSV stream generation with filters", filters=params)

    # --- 1. Xây dựng Query (Sao chép logic filter/sort từ get_users) ---
    
    # ✅ SPRINT 7: Use UserRepository to build query (DRY)
    from app.repositories import UserRepository
    user_repo = UserRepository(db)
    
    # Get base query with all filters applied from Repository
    query = await user_repo.get_users_stream_query(params)

    # Sao chép logic sort từ hàm get_users
    sort = params.get("sort", "id")
    order = params.get("order", "asc")
    # QW-A fix #5: second sort-injection sink (CSV export). `sort` is a
    # user-controlled query param → route through the SAME allowlist guard the
    # repository uses (unknown/sensitive cols fall back to id). The old
    # hasattr+getattr allowed ORDER BY <secret col> + .desc() on a relationship.
    from app.repositories.user_repository import _safe_user_sort_column
    sort_column = _safe_user_sort_column(sort)
    if order.lower() == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column.asc())

    # --- 2. Yield dòng Header ---
    headers = [
        "ID",
        "Username",
        "Email",
        "Full Name",
        "Role",
        "Status",
        "Phone",
        "Unit",
        "Skills",
        "Max Capacity",
    ]
    
    # Sử dụng io.StringIO để csv.writer ghi vào một string
    string_io = io.StringIO()
    writer = csv.writer(string_io)
    writer.writerow(headers)
    
    # Gửi (yield) dòng header
    yield string_io.getvalue()

    # --- 3. Stream dữ liệu từ CSDL ---
    # Sử dụng stream_scalars để không load tất cả user vào bộ nhớ
    try:
        stream = await db.stream_scalars(query)
        
        async for user in stream:
            # Reset string_io cho mỗi dòng
            string_io = io.StringIO()
            writer = csv.writer(string_io)

            row = [
                user.id,
                user.username,
                user.email,
                user.full_name or "",
                user.role,
                user.status,
                user.phone_number or "",
                user.unit.name if user.unit else "", # An toàn nhờ selectinload
                ",".join(user.skills) if user.skills else "",
                user.max_capacity or 0,
            ]

            # ✅ SECURITY FIX: Sanitize row to prevent CSV injection
            # This prevents formula injection attacks when CSV is opened in Excel/LibreOffice
            # See: OWASP CSV Injection, CWE-1236
            sanitized_row = sanitize_csv_row(row)
            writer.writerow(sanitized_row)

            # Gửi (yield) dòng dữ liệu
            yield string_io.getvalue()
            
    except Exception as e:
        log.error("Error during CSV stream query", error=str(e), exc_info=True)
        # Gửi thông báo lỗi vào file CSV nếu có thể
        # V6 vòng 5: tệp CSV tải về là PHẢN HỒI — không mang chữ lỗi CSDL.
        yield f"\"Error streaming data: {chu_loi_an_toan(e)}\""

    log.info("CSV stream generation complete", filters=params)


# =============================================================================
# PHASE 1 - Task 1.7: USER SYNC TO CASBIN (EXTRACTED FROM ROUTER)
# =============================================================================

async def sync_users_to_casbin(
    db: AsyncSession,
    enforcer: casbin.AsyncEnforcer,
    user_ids: Optional[List[int]] = None,
    actor_id: Optional[int] = None,  # PR-B Q4: Admin bấm đồng bộ (``revoked_by_user_id`` khi tự thu hồi quyền chéo)
    request_meta: Optional[Any] = None,
) -> Dict[str, any]:
    """
    Synchronize user roles from Casbin (source of truth) to database.

    This function extracts business logic from the router layer, making it
    protocol-independent and reusable across different contexts (HTTP, CLI, Celery).

    Business Rules:
    - Casbin is the source of truth for role assignments
    - Database user.role field is updated to match Casbin
    - Highest priority role is used if user has multiple roles
    - Failed syncs are collected and returned for error handling

    Args:
        db: Database session (injected via DI)
        enforcer: Casbin enforcer instance (injected via DI)
        user_ids: Optional list of specific user IDs to sync.
                  ``None`` = sync all users. ``[]`` = sync NO ONE.
                  Hai thứ đó KHÔNG giống nhau — xem chú thích ở
                  vị từ bên dưới. Tầng HTTP đã chặn ``[]`` bằng 422
                  (``SyncUsersRequest``); vị từ ở đây là hàng rào thứ
                  hai cho caller nội bộ tương lai.

    Returns:
        Dict containing:
        - synced_count: Number of users successfully synced
        - failed_count: Number of failed sync operations
        - failed_users: List of dicts with user_id, username, error

    Raises:
        No exceptions raised - errors are collected in failed_users

    Example:
        >>> result = await sync_users_to_casbin(
        ...     db=session,
        ...     enforcer=app.state.enforcer,
        ...     user_ids=[1, 2, 3]  # Sync specific users
        ... )
        >>> print(result["synced_count"])
        3

        >>> result = await sync_users_to_casbin(
        ...     db=session,
        ...     enforcer=app.state.enforcer,
        ...     user_ids=None  # Sync ALL users
        ... )

    Note:
        This function does NOT commit the transaction. The caller is responsible
        for calling db.commit() after this function returns.
    """
    # ✅ SPRINT 4 HOTFIX: Use Repository for data access
    from app.repositories import UserRepository
    
    repo = UserRepository(db)
    
    # Query users to sync.
    #
    # `is not None` chứ KHÔNG phải truthiness: `[]` là "không ai", còn
    # `None` mới là "tất cả". Bản trước dùng `if user_ids:` nên gộp hai
    # thứ ngược nhau vào cùng một nhánh — một danh sách rỗng do lỗi nhập
    # liệu biến thành lệnh ghi lên TOÀN BỘ user. `get_by_ids([])` trả `[]`
    # an toàn (user_repository.py:640), nên nhánh này không cần ca riêng.
    if user_ids is not None:
        users = await repo.get_by_ids(user_ids)
    else:
        users = await repo.get_all()

    synced_count = 0
    failed_users = []

    from app.repositories import document_bulk_repository as bulk_repo
    from app.services.document_cross_review_service import revoke_grants_on_account_change

    # Process each user — id TĂNG (PR-B Q4: mỗi người khoá dòng user → dòng quyền; hai lượt đồng bộ khoá cùng chiều).
    # PR-B lượt 5 (Codex 22-11 P2): khoá TRƯỚC toàn tập (người đích ∪ người thao tác — khoá ngoại phân công / thu hồi /
    # nhật ký) theo id TĂNG, rồi mới ghi ai — cùng chiều K4. Khoá lại trong vòng là no-op, giữ để đọc vai dưới khoá.
    from app.services.user_deletion_policy import lock_users_in_id_order

    await lock_users_in_id_order(db, target_ids=[u.id for u in users], referenced_ids=[actor_id])
    for user in sorted(users, key=lambda u: u.id):
        # PR-B lượt 3 (vá nhánh cùng khuôn Codex lượt 2 điểm chặn 3): TUẦN TỰ HOÁ THEO TÀI KHOẢN — khoá dòng người TRƯỚC khi
        # đọc vai Casbin, so với vai CSDL đọc DƯỚI khoá (không với bản nạp đầu lệnh). Một lệnh đổi vai đang giữ dòng người
        # (đã ghi CSDL, sắp ghi Casbin) ⇒ lượt đồng bộ chờ nó commit rồi mới đọc Casbin — không ghi đè vai CSDL bằng ảnh Casbin
        # đọc TRƯỚC lệnh ấy.
        locked = await bulk_repo.lock_user_no_key_update(db, user.id)
        if locked is None:
            continue
        # PR-B lượt 4 (Codex lượt 3 điểm chặn 3): đối tượng ``user`` nạp TRƯỚC khoá — làm mới dưới khoá, để lệnh gán bên
        # dưới so với vai HIỆN HÀNH (gán trùng vai cũ của đối tượng ⇒ ORM bỏ UPDATE mà ``synced_count`` vẫn tăng).
        # PR-B lượt 5: làm mới cả ``unit_id`` — bản ghi phân công mới lấy đơn vị HIỆN HÀNH dưới khoá.
        await db.refresh(user, attribute_names=["role", "unit_id"])
        # PR-B lượt 4 (Codex lượt 3 điểm chặn 1): vai Casbin đọc từ BẢNG ``casbin_rule`` (nguồn chung mọi worker), không từ
        # bộ nhớ enforcer của worker này (có thể cũ). Lỗi đọc CSDL ⇒ ném ra (giao dịch không commit gì).
        casbin_role = highest_priority_role(await repo.grouping_roles(user.id))

        # Update DB if role doesn't match (vai CSDL đọc dưới khoá ở đầu vòng)
        if locked.role != casbin_role:
            # GĐ1b PR-B Q4: đổi vai khỏi Cán bộ ⇒ tự thu hồi quyền duyệt chéo CÙNG giao dịch, TRƯỚC khi ghi vai. Lỗi ở
            # đây KHÔNG bị nuốt thành "failed_users" (bản cũ nuốt mọi lỗi trong vòng): nuốt thì router vẫn commit vai mới
            # mà quyền chưa thu hồi / thiếu nhật ký ⇒ ném ra để router không commit gì (fail-closed).
            await revoke_grants_on_account_change(
                db,
                user_id=user.id,
                new_role=casbin_role,
                actor_id=actor_id,
                request_meta=request_meta,
            )
            old_role = locked.role
            # PR-B lượt 5 (Codex 22-11 B-P1): đổi vai CSDL qua ĐÚNG hàm PUT dùng — đóng bản ghi phân công đang hiệu lực, mở
            # bản ghi mới mang vai đồng bộ (cùng giao dịch, dưới khoá dòng người ở trên). ``enforcer=None``: đồng bộ này đi từ
            # Casbin VỀ CSDL, không ghi Casbin.
            await _create_or_update_user_assignment(
                db=db,
                user=user,
                new_role=casbin_role,
                new_unit_id=user.unit_id,
                assigned_by_user_id=actor_id,
                enforcer=None,
            )
            db.add(user)
            synced_count += 1

            log.info(
                "User role synced from Casbin to DB",
                user_id=user.id,
                username=user.username,
                old_role=old_role,
                new_role=casbin_role
            )

    # Note: Caller is responsible for db.commit()

    return {
        "synced_count": synced_count,
        "failed_count": len(failed_users),
        "failed_users": failed_users
    }