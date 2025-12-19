# app/services/user_service.py
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
    CacheServiceError,
    DuplicateResourceError,
    InvalidCredentials,
    InvalidToken,
    ResourceNotFoundError,
    UserServiceError,
)

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

# ✅ 2. Event Dispatcher Pattern (replaces direct Socket.IO dependency)
from ..core.events import dispatcher, TransportEvents
from ..socket_metrics import socket_emit_failures_total, socket_events_emitted_total
from ..utils import file_helpers
from . import activity_service

# ✅ SỬA LỖI: Chuyển log sang đồng bộ (tương thích với main.py V5)
log = structlog.get_logger(__name__)


# =============================================================================
# REAL-TIME DATA SYNC HELPER
# =============================================================================

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
    Lấy role có độ ưu tiên cao nhất từ Casbin cho user.
    Returns: "admin" | "manager" | "officer" | "user"
    """
    ROLE_PRIORITY = {
        "role:admin": 4,
        "role:manager": 3,
        "role:officer": 2,
        "role:user": 1
    }

    user_subject = f"user:{user_id}"
    casbin_roles = await enforcer.get_roles_for_user(user_subject)

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
    assigned_by_user_id: Optional[int] = None
) -> Optional[models.UserUnitAssignment]:
    """
    ✅ PHASE 2: Temporal Architecture Helper

    Create or update user assignment with temporal history tracking.

    This function implements the atomic transaction pattern for user role/unit changes:
    1. Find old active assignment (if exists)
    2. Deactivate old assignment (set is_active=false, end_date=now())
    3. Create new assignment (with is_active=true)
    4. Update user cache fields (role, unit_id, current_assignment_id)

    Args:
        db: Database session
        user: User object to update
        new_role: New role to assign
        new_unit_id: New unit ID (can be None for non-unit users)
        assigned_by_user_id: ID of admin who made the assignment (None = system/migration)

    Returns:
        New UserUnitAssignment object if assignment was created, None if skipped

    Note:
        - If user has no unit (new_unit_id is None), we don't create assignment
        - This function must be called INSIDE a transaction
        - Caller is responsible for commit/rollback
    """
    now = datetime.now(timezone.utc)

    # Skip if user has no unit (regular users without unit assignment)
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

    # ✅ SPRINT 5: Use Repository for active assignment lookup
    from app.repositories import UserRepository
    user_repo = UserRepository(db)
    
    # 1. Find and deactivate old active assignment (if exists)
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
            if avatar_content and avatar_filename:
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

                added = await enforcer.add_grouping_policy(user_subject, role_name)
                log.debug("Added Casbin grouping policy for new user", added=added)

                # Save policy - this writes to casbin_rule table in SAME transaction
                await enforcer.save_policy()

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


async def update_user(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    enforcer: Optional[casbin.AsyncEnforcer] = None,
    avatar_content: Optional[bytes] = None,  # ✅ REFACTORED: bytes instead of UploadFile
    avatar_filename: Optional[str] = None,   # ✅ REFACTORED: filename for validation
    assigned_by_user_id: Optional[int] = None,  # ✅ PHASE 2: Track who made the assignment
) -> Tuple[models.User, Callable]:
    """
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

        # ✅ PHASE 2: Track role AND unit_id changes BEFORE updating
        old_db_role = db_user.role
        old_db_unit_id = db_user.unit_id
        new_db_role = update_data.get("role", old_db_role)  # Default to current if not changing
        new_db_unit_id = update_data.get("unit_id", old_db_unit_id)  # Default to current

        user_subject = f"user:{db_user.id}"
        role_changed = new_db_role != old_db_role
        unit_changed = new_db_unit_id != old_db_unit_id
        assignment_changed = role_changed or unit_changed

        if "email" in update_data and update_data["email"] != db_user.email:
            existing_user = await get_user_by_email(db, update_data["email"])
            if existing_user and existing_user.id != user_id_for_logging:
                raise DuplicateResourceError(
                    detail="Email already registered by another user"
                )

        # ✅ ATOMIC FIX: Begin nested transaction (savepoint)
        # This ensures DB + Assignment + Casbin operations are atomic
        async with db.begin_nested():
            # (1) Update user fields (EXCEPT role/unit_id - handled by assignment helper)
            for field, value in update_data.items():
                # Skip role/unit_id - will be set by _create_or_update_user_assignment
                if field not in ["role", "unit_id"] and value is not None:
                    setattr(db_user, field, value)

            # ✅ REFACTORED: Use avatar_content + avatar_filename (Issue #3)
            if avatar_content and avatar_filename:
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
                    assigned_by_user_id=assigned_by_user_id
                )

            db.add(db_user)
            await db.flush()  # Flush to get updated values
            await db.refresh(db_user)

            # (3) Sync Casbin INSIDE the same transaction (if role changed)
            if role_changed and enforcer:
                log.info(
                    "Role changed, syncing Casbin inside transaction",
                    user_id=user_id_for_logging,
                    old=old_db_role,
                    new=new_db_role
                )

                old_casbin_role = f"role:{old_db_role}" if old_db_role else None
                new_casbin_role = f"role:{new_db_role}"

                # Remove old role grouping (if exists)
                if old_casbin_role:
                    removed = await enforcer.remove_grouping_policy(user_subject, old_casbin_role)
                    log.debug("Removed old Casbin grouping policy", removed=removed)

                # Add new role grouping
                added = await enforcer.add_grouping_policy(user_subject, new_casbin_role)
                log.debug("Added new Casbin grouping policy", added=added)

                # Save policy - this writes to casbin_rule table in SAME transaction
                await enforcer.save_policy()

                log.info(
                    "Casbin grouping policy synced successfully (in transaction)",
                    user_id=user_id_for_logging,
                    new_casbin_role=new_casbin_role
                )

            # ✅ If we reach here, all operations succeeded
            # Nested transaction will commit on exit from 'async with' block

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
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

        for field, value in update_data.items():
            if field in ["full_name", "phone_number", "email"]:
                if value is not None:
                    setattr(db_user, field, value)

        # ✅ REFACTORED: Use avatar_content + avatar_filename (Issue #3)
        if avatar_content and avatar_filename:
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


async def delete_user(db: AsyncSession, user_id: int) -> Tuple[None, Callable]:
    """
    Delete a user.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        # ✅ SPRINT 5: Use Repository for eager loading
        from app.repositories import UserRepository
        user_repo = UserRepository(db)
        
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
        async with redis_client.pipeline() as pipe:
            pipe.incr(email_rate_limit_key)
            pipe.expire(email_rate_limit_key, 3600)
            await pipe.execute()

    except Exception as e_redis:
        # Fail-open (vẫn cho chạy) nhưng log lỗi
        log.error(
            "Failed to check/set email rate limit for forgot_password",
            email=cleaned_email,
            error=str(e_redis),
        )

    # (Logic cũ tiếp tục)
    user = await get_user_by_email(db, email=email_in)
    if not user:
        log.debug("User not found for forgot password request", email=cleaned_email)
        return

    log.info(
        "User found for forgot password request. Sending reset email.", user_id=user.id
    )
    token = create_password_reset_token(email=user.email)
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
        email = verify_password_reset_token(token)
        if not email:
            log.warning(
                "Invalid reset token attempt", token_prefix=token[:10]
            )  # ✅ SỬA LỖI: Xóa `await`
            raise InvalidToken()

        user = await get_user_by_email(db, email=email)
        if not user:
            log.warning(
                "Reset token for non-existent user", email=email
            )  # ✅ SỬA LỖI: Xóa `await`
            raise ResourceNotFoundError(
                detail="User associated with this token not found."
            )

        user.password_hash = get_password_hash(new_password)
        db.add(user)

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


async def invalidate_all_sessions(db: AsyncSession, user: models.User):
    """
    (V5 - Fixed) Vô hiệu hóa tất cả các phiên hoạt động.
    Sửa lỗi Race Condition bằng cách khóa (lock) và cập nhật DB trong 1 transaction.
    """
    revoked_jtis = []
    user_id = user.id
    now = datetime.now(timezone.utc)
    max_token_ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    safe_ttl = max(60, max_token_ttl)

    try:
        # 1. Bắt đầu transaction và LẤY KHÓA
        async with db.begin():
            result = await db.execute(
                select(models.UserSession)
                .where(
                    models.UserSession.user_id == user_id,
                    models.UserSession.revoked_at.is_(None),  # Chỉ khóa session active
                )
                .with_for_update()  # ✅ KHÓA CÁC DÒNG NÀY
            )
            all_sessions = result.scalars().all()

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
                        "error": str(e_redis_set),
                    }
                )

        # 4. ✅ COMMIT TỰ ĐỘNG (khi ra khỏi `async with db.begin()`)
        log.info("DB transaction committed, sessions revoked in DB", user_id=user_id)

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
                # Không ném lỗi ở đây, vì DB đã commit (nhưng cần log)

        # 6. ✅ DISPATCH EVENT (Event Dispatcher Pattern - SAU KHI MỌI THỨ HOÀN TẤT)
        try:
            await dispatcher.dispatch(
                TransportEvents.USER_FORCE_LOGOUT,
                user_id=user_id,
                reason="Password changed",
                revoked_jtis=[]  # All sessions revoked
            )
            socket_events_emitted_total.labels(event_type="force_logout_all").inc()
            log.info("Dispatched force_logout event (password change)", user_id=user_id)
        except Exception as e_dispatch:
            socket_emit_failures_total.labels(event_type="force_logout_all").inc()
            log.error(
                "Failed to dispatch logout event", error=str(e_dispatch)
            )

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
                context={"user_id": user_id, "error": str(e)}
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
        
        # ✅ FIX MissingGreenlet: Eager load cascade-delete relationships for delete action
        if action == "delete":
            users_to_process = await user_repo.get_users_by_ids_for_delete(user_ids)
        else:
            users_to_process = await user_repo.get_by_ids(user_ids)

        if not users_to_process:
            log.info(
                "Bulk action: No users found matching provided IDs.",
                user_ids=user_ids,
                admin_id=admin_user.id,
            )  # ✅ SỬa LỖI: Xóa `await`
            return "No users found for the provided IDs. 0 users affected."

        processed_count = 0
        message = ""
        if action == "delete":
            # ✅ SPRINT 5: Use Repository for consultation check
            # Check if any users have consultations (cannot delete)
            users_with_consultations = await user_repo.count_consultations_by_officers(user_ids)

            if users_with_consultations:
                user_list = ", ".join(f"User ID {uid} ({count} consultations)"
                                     for uid, count in users_with_consultations.items())
                error_msg = f"Cannot delete users with consultations: {user_list}. Please reassign or delete their consultations first."
                log.warning(
                    "Bulk delete blocked: Users have consultations",
                    admin_id=admin_user.id,
                    users_with_consultations=users_with_consultations,
                )
                raise BadRequest(detail=error_msg)

            # Unassign leads from users being deleted (set assigned_officer_id to NULL)
            await db.execute(
                select(models.Lead)
                .where(models.Lead.assigned_officer_id.in_(user_ids))
            )
            unassign_result = await db.execute(
                select(models.Lead)
                .where(models.Lead.assigned_officer_id.in_(user_ids))
            )
            leads_to_unassign = unassign_result.scalars().all()
            for lead in leads_to_unassign:
                lead.assigned_officer_id = None
                db.add(lead)

            if leads_to_unassign:
                log.info(
                    "Unassigned leads before bulk delete",
                    admin_id=admin_user.id,
                    lead_count=len(leads_to_unassign),
                )

            ids_to_delete = []
            skipped_users = []
            for user in users_to_process:
                if user.id == admin_user.id:
                    log.warning(
                        "Admin attempted to delete self during bulk action, skipping.",
                        admin_id=admin_user.id,
                    )
                    skipped_users.append(user.id)
                    continue

                await db.delete(user)  # Mark user for deletion
                ids_to_delete.append(user.id)
                processed_count += 1

            # Build message with details
            message = f"Successfully deleted {processed_count} users."
            if skipped_users:
                message += f" Skipped {len(skipped_users)} users (cannot delete self)."
            if leads_to_unassign:
                message += f" Unassigned {len(leads_to_unassign)} leads."

            log.info(
                "Admin bulk deleted users",
                admin_id=admin_user.id,
                deleted_ids=ids_to_delete,
                skipped_ids=skipped_users,
                unassigned_leads=len(leads_to_unassign) if leads_to_unassign else 0,
            )

        elif action == "change_status":
            ids_changed = []
            for user in users_to_process:
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
                    )  # ✅ SỬA LỖI: Xóa `await`

            message = f"Successfully updated status to '{new_status}' for {processed_count} users."
            if ids_changed:
                log.info(  # ✅ SỬA LỖI: Xóa `await`
                    "Admin bulk changed user status",
                    admin_id=admin_user.id,
                    changed_ids=ids_changed,
                    new_status=new_status,
                )

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback (empty - no post-commit actions needed)
        async def _post_commit():
            """Execute after router commits the transaction."""
            pass

        return message, _post_commit

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
    
    # ✅ Tối ưu: Eager load 'unit' để tránh N+1 query khi stream
    query = select(models.User).options(selectinload(models.User.unit))

    # Sao chép logic filter từ hàm get_users
    allowed_filters = {
        "role": models.User.role,
        "status": models.User.status,
    }

    # ✅ SECURITY FIX: Search DoS Prevention (same as get_users)
    filters = []
    for key, value in params.items():
        if key in allowed_filters and value:
            values_to_filter = [v.strip() for v in value.split(",")]
            query = query.filter(allowed_filters[key].in_(values_to_filter))
        elif key == "search" and value:
            # ✅ NEW: Use full-text search (same as get_users)
            search_term = value.strip().replace(' ', ' & ')
            query = query.filter(
                models.User.search_vector.op('@@')(
                    func.to_tsquery('simple', search_term)
                )
            )

    if filters:
        query = query.where(*filters)

    # Sao chép logic sort từ hàm get_users
    sort = params.get("sort", "id")
    order = params.get("order", "asc")
    if hasattr(models.User, sort):
        sort_column = getattr(models.User, sort)
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
        yield f"\"Error streaming data: {str(e)}\""

    log.info("CSV stream generation complete", filters=params)


# =============================================================================
# PHASE 1 - Task 1.7: USER SYNC TO CASBIN (EXTRACTED FROM ROUTER)
# =============================================================================

async def sync_users_to_casbin(
    db: AsyncSession,
    enforcer: casbin.AsyncEnforcer,
    user_ids: Optional[List[int]] = None,
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
                  If None or empty, sync all users in database.

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
    
    # Query users to sync (specific IDs or all)
    if user_ids:
        users = await repo.get_by_ids(user_ids)
    else:
        users = await repo.get_all()

    synced_count = 0
    failed_users = []

    # Process each user
    for user in users:
        try:
            # Get highest priority role from Casbin (source of truth)
            casbin_role = await get_highest_priority_role_from_casbin(
                enforcer, user.id
            )

            # Update DB if role doesn't match
            if user.role != casbin_role:
                old_role = user.role
                user.role = casbin_role
                db.add(user)
                synced_count += 1

                log.info(
                    "User role synced from Casbin to DB",
                    user_id=user.id,
                    username=user.username,
                    old_role=old_role,
                    new_role=casbin_role
                )

        except Exception as e:
            log.error(
                "Failed to sync user role from Casbin",
                user_id=user.id,
                username=getattr(user, 'username', 'unknown'),
                error=str(e),
                exc_info=True
            )
            failed_users.append({
                "user_id": user.id,
                "username": getattr(user, 'username', 'unknown'),
                "error": str(e)
            })

    # Note: Caller is responsible for db.commit()

    return {
        "synced_count": synced_count,
        "failed_count": len(failed_users),
        "failed_users": failed_users
    }