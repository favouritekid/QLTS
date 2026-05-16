# app/routers/admin/users.py
"""
User Management Admin Router

Handles all user-related administrative operations including:
- User CRUD (create, read, update, delete)
- User export (Excel, CSV streaming)
- Bulk user operations
- Casbin synchronization (uses user_service from PHASE 1)
- Lead management (uses lead_service from PHASE 1)
- User analytics and activity logs

PHASE 2A: Extracted from monolithic admin.py (line count: ~500)
Dependencies: user_service, lead_service, activity_service (from PHASE 1)

Breaking API Changes:
- POST /api/admin/users → POST /api/admin/users (no change)
- GET /api/admin/users → GET /api/admin/users (no change)
- GET /api/admin/sync/status → GET /api/admin/users/sync/status
- POST /api/admin/sync/users → POST /api/admin/users/sync
- POST /api/admin/leads/* → POST /api/admin/users/leads/*
- GET /api/admin/activity-logs → GET /api/admin/users/activity-logs
- GET /api/admin/statistics/users → GET /api/admin/users/statistics
"""
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

import io
from typing import Callable, List, Optional, Tuple
from datetime import datetime, timezone

import pandas as pd
import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status as http_status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import EmailStr, TypeAdapter, ValidationError

from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.config import settings
from app.core import deps
from app.core.deps import CasbinAuth  # Phase 2.2
from app.database import get_db
from app.services import activity_service, lead_service, user_service
from app.tasks import process_automatic_lead_assignment_task
from app.core.constants import UserRole
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(prefix="/users", tags=["Admin - Users"])



# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def log_admin_activity(
    db: AsyncSession,
    request: Request,
    action: str,
    resource_type: str,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    description: Optional[str] = None,
    changes: Optional[dict] = None,
) -> Tuple[models.UserActivityLog, Callable]:
    """
    Helper: extract IP/UA from request and delegate to activity_service.
    Returns (activity_log, post_commit_callback) — caller must commit and run callback.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    return await activity_service.log_activity(
        db=db,
        action=action,
        resource_type=resource_type,
        actor_id=actor_id,
        target_user_id=target_user_id,
        resource_id=resource_id,
        description=description,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ============================================================================
# USER CRUD OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "",
    status_code=http_status.HTTP_201_CREATED,
    response_model=schemas.UserAdminResponse,
)
async def create_new_user(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form("user"),
    status: str = Form("active"),
    avatar: Optional[UploadFile] = File(None),
):
    """(Admin only) Tạo một người dùng mới, có hỗ trợ upload avatar."""
    # Form() bypasses FastAPI's body validation, so we construct
    # AdminUserCreate manually. Surface pydantic field errors as the
    # 422 contract the rest of the admin/* tests expect — without this
    # the inline error bubbles to the generic 500 handler.
    try:
        user_in = schemas.AdminUserCreate(
            username=username,
            email=email,
            password=password,
            confirm_password=password,
            full_name=full_name,
            role=role,
            status=status,
        )
    except ValidationError as exc:
        return JSONResponse(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": "Validation Error",
                "errors": [
                    {
                        "field": ".".join(str(loc) for loc in err.get("loc", [])),
                        "message": err.get("msg", ""),
                    }
                    for err in exc.errors()
                ],
            },
        )

    # ✅ SECURITY: Prevent privilege escalation - users can only create roles below their own
    _role_hierarchy = {
        UserRole.ADMIN: 4,
        UserRole.MANAGER: 3,
        UserRole.ACCOUNTANT: 2,
        UserRole.OFFICER: 1,
        UserRole.USER: 0,
    }
    creator_level = _role_hierarchy.get(current_admin.role, -1)
    target_level = _role_hierarchy.get(user_in.role, -1)
    if target_level < 0:
        raise BusinessRuleViolation(detail=f"Invalid role: {user_in.role}")
    if target_level >= creator_level:
        raise BusinessRuleViolation(
            detail="Cannot create a user with equal or higher role than your own"
        )

    if await user_service.get_user_by_username(db, user_in.username):
        raise DuplicateResourceError(detail="Username already exists")
    if await user_service.get_user_by_email(db, user_in.email):
        raise DuplicateResourceError(detail="Email already exists")

    # ✅ REFACTORED (Issue #3): Read avatar file content in router layer
    avatar_content = None
    avatar_filename = None
    if avatar and avatar.filename:
        # Validate file size before reading (DoS protection)
        avatar.file.seek(0, 2)  # Seek to end
        file_size = avatar.file.tell()
        avatar.file.seek(0)  # Reset to beginning

        if file_size > settings.MAX_AVATAR_CONTENT_LENGTH:
            raise HTTPException(
                status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB."
            )

        avatar_content = await avatar.read()
        avatar_filename = avatar.filename

    # ✅ ATOMIC FIX (v17): Pass enforcer to service for atomic DB + Casbin transaction
    enforcer = request.app.state.enforcer
    created_user, callback = await user_service.create_user_by_admin(
        db=db,
        user_in=user_in,
        enforcer=enforcer,
        avatar_content=avatar_content,  # ✅ REFACTORED: Pass bytes instead of UploadFile
        avatar_filename=avatar_filename,  # ✅ REFACTORED: Pass filename
    )
    # Casbin sync now happens inside create_user_by_admin atomically

    # ✅ TRANSACTION PATTERN: Commit and execute callback
    await db.commit()
    await callback()

    # Best-effort audit log — business change already committed above
    try:
        _, log_callback = await log_admin_activity(
            db=db,
            request=request,
            action="create_user",
            resource_type="user",
            actor_id=current_admin.id,
            target_user_id=created_user.id,
            resource_id=created_user.id,
            description=f"Admin created new user: {created_user.username}",
        )
        await db.commit()
        await log_callback()
    except Exception:
        log.error("Failed to persist audit log for create_user", user_id=created_user.id, exc_info=True)

    return created_user




@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("")
async def get_all_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
):
    """List users với phân trang, filter, search.

    E2E F3 fix 2026-05-16 — response shape varies theo caller role để
    chống PII leak (memory `service-explicit-dict-field-drop-pattern`):
    - manager / admin: full ``UsersPage`` (UserAdminResponse) — bao gồm
      email, phone_number, mfa_enabled, password_reset_required,
      max_capacity (admin context cần đầy đủ thông tin lead-routing +
      security audit).
    - officer / accountant / collaborator / user: ``UsersPagePicker``
      (UserPickerSchema) — chỉ id, username, full_name, role, status,
      unit_id, avatar_url, skills, availability_status. Đủ cho UI
      picker / dropdown / "ai phụ trách" display, KHÔNG leak PII.

    Casbin allow GET /api/admin/users cho mọi role (existing behavior
    cho user-picker). Schema branching closes data-shape leak.

    response_model removed (Union[UsersPage, UsersPagePicker] would lose
    OpenAPI clarity); FastAPI auto-serializes Pydantic instance returned.
    """
    skip = (page - 1) * page_size
    query_params = dict(request.query_params)
    total, users = await user_service.get_users(
        db, params=query_params, skip=skip, limit=page_size
    )

    # Privileged roles get full PII shape; everyone else gets picker.
    privileged_roles = {"admin", "manager"}
    if current_admin.role in privileged_roles:
        return schemas.UsersPage(
            total_count=total,
            users=[schemas.UserAdminResponse.model_validate(u) for u in users],
        )
    return schemas.UsersPagePicker(
        total_count=total,
        users=[schemas.UserPickerSchema.model_validate(u) for u in users],
    )








# === KẾT THÚC HÀM CẬP NHẬT ===





@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/list", response_model=List[schemas.UserAdminResponse])
async def list_users(
    request: Request,
    unit_id: Optional[int] = Query(None, description="Filter by organization unit ID"),
    include_children: bool = Query(False, description="Include users from child units (hierarchical filter)"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) List all users with optional filtering.

    Filters:
    - unit_id: Show only users belonging to specific organizational unit
    - include_children: If True, include users from all child units of the selected unit
    - is_active: Show only active or inactive users

    **Hierarchical Filter Behavior:**
    - When selecting a **child unit**: Shows only users from that unit
    - When selecting a **parent unit** with `include_children=true`:
      Shows users from parent AND all descendant units
    """
    return await user_service.list_users(
        db=db,
        unit_id=unit_id,
        include_children=include_children,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )


# =============================================================================
# OFFERING ACADEMIC INFO (LEVEL 3) - ADMIN ENDPOINTS
# =============================================================================



@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/{user_id}/password")
async def admin_set_user_password(
    request: Request,
    user_id: int,
    password_data: schemas.AdminSetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """(Admin only) Admin đặt lại mật khẩu cho người dùng."""
    user, post_commit = await user_service.set_password_by_admin(
        db, user_id, password_data.new_password
    )
    await db.commit()
    await post_commit()
    return None




# ============================================================================
# USER EXPORT OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/export")
async def export_all_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Export tất cả người dùng ra CSV (không phân trang).

    Endpoint này trả về toàn bộ danh sách users phù hợp với các filter (role, status, search)
    mà không có giới hạn phân trang. Được sử dụng khi Admin nhấn nút "Export CSV"
    để đảm bảo export toàn bộ users, không chỉ trang hiện tại.

    ✅ Sử dụng eager loading (selectinload) để tránh N+1 queries.
    🔒 SECURITY: Excludes password_hash from export to prevent credential leakage
    """
    query_params = dict(request.query_params)
    # Gọi get_users với skip=0 và limit rất lớn để lấy tất cả
    # Hoặc có thể gọi với skip=0, limit=None nếu service hỗ trợ
    total, users = await user_service.get_users(
        db, params=query_params, skip=0, limit=10000  # Giới hạn tạm 10k users
    )

    # 🔒 SECURITY FIX: Remove password_hash from export
    # Convert SQLAlchemy models to dicts and exclude sensitive fields
    safe_users = []
    for user in users:
        user_dict = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "status": user.status,
            "phone_number": user.phone_number,
            "avatar_url": user.avatar_url,
            "unit_id": user.unit_id,
            "skills": user.skills,
            "availability_status": user.availability_status,
            "max_capacity": user.max_capacity,
            "total_lead_score": user.total_lead_score,
            "current_assignment_id": user.current_assignment_id,
            # Explicitly EXCLUDE: password_hash, active_jti, search_vector
        }
        safe_users.append(user_dict)

    return safe_users


# ✅ FIX: Move /users/export-csv BEFORE /users/{user_id} to prevent route conflict
# FastAPI matches routes in order, so specific paths must come before path parameters


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/export/csv")
async def stream_export_users_csv(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Stream export users ra file CSV.
    Endpoint này sử dụng StreamingResponse để xử lý lượng dữ liệu lớn
    mà không tốn bộ nhớ server.

    ✅ SECURITY FIX: Uses CSV sanitization to prevent CSV injection attacks
    ✅ PERFORMANCE FIX: Uses full-text search to prevent Search DoS attacks
    """
    # Lấy các query params (filters) từ request
    query_params = dict(request.query_params)
    log.info("CSV export stream requested by admin", admin_id=current_admin.id, filters=query_params)

    # 1. Gọi service (là một async generator)
    csv_streamer = user_service.stream_users_csv(db, query_params)

    # 2. Đặt tên file và headers
    filename = f"users_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "Content-Type": "text/csv; charset=utf-8",
    }

    # 3. Trả về StreamingResponse
    return StreamingResponse(
        csv_streamer,
        headers=headers,
        media_type="text/csv"
    )




# ============================================================================
# USER BULK OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_BULK)  # 10/hour - Bulk operation
@router.post("/bulk")
async def bulk_user_action(
    action_data: schemas.BulkActionSchema,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """(Admin only) Thực hiện hành động hàng loạt (xóa, đổi trạng thái) trên nhiều người dùng."""
    enforcer = request.app.state.enforcer

    # Perform bulk action
    message, bulk_callback = await user_service.perform_bulk_action(
        db,
        action=action_data.action,
        user_ids=action_data.user_ids,
        admin_user=current_admin,
        new_status=action_data.status,
    )

    # Clean up Casbin policies for deleted users
    if action_data.action == "delete":
        for user_id in action_data.user_ids:
            # Skip if this was the admin (they can't delete themselves)
            if user_id == current_admin.id:
                continue

            # Remove all Casbin policies for this user
            user_subject = f"user:{user_id}"
            try:
                # Remove all role assignments for this user
                await enforcer.delete_roles_for_user(user_subject)
                # Remove all permissions for this user
                await enforcer.delete_permissions_for_user(user_subject)
            except Exception as e:
                # Log but don't fail the request if Casbin cleanup fails
                print(f"Warning: Failed to clean up Casbin policies for user {user_id}: {e}")

    # Log activity for bulk action
    action_desc = f"Bulk {action_data.action}"
    if action_data.action == "change_status" and action_data.status:
        action_desc += f" to {action_data.status}"
    action_desc += f" for {len(action_data.user_ids)} users"

    _, log_callback = await log_admin_activity(
        db=db,
        request=request,
        action=f"bulk_{action_data.action}",
        resource_type="user",
        actor_id=current_admin.id,
        description=action_desc,
        changes={"user_ids": action_data.user_ids, "status": action_data.status} if action_data.status else {"user_ids": action_data.user_ids},
    )
    await db.commit()
    await bulk_callback()
    await log_callback()

    return {"detail": message}


# ← PHASE 3: Detection endpoint - check DB/Casbin sync status


# ============================================================================
# CASBIN SYNC OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/sync/status")
async def get_sync_status(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth
):
    """
    (Admin only) Kiểm tra tình trạng đồng bộ giữa DB (user.role) và Casbin (grouping policies).
    Trả về số lượng user đã sync, chưa sync, và chi tiết các user bị lệch.
    """
    enforcer = request.app.state.enforcer

    # Get all users via service
    users = await user_service.get_all_users(db)

    mismatched_users = []
    synced_count = 0

    for user in users:
        casbin_role = await user_service.get_highest_priority_role_from_casbin(
            enforcer, user.id
        )

        if user.role != casbin_role:
            casbin_roles = await enforcer.get_roles_for_user(f"user:{user.id}")
            mismatched_users.append({
                "user_id": user.id,
                "username": user.username,
                "db_role": user.role,
                "casbin_role": casbin_role,
                "all_casbin_roles": casbin_roles
            })
        else:
            synced_count += 1

    log.info(
        "Sync status check completed",
        admin_id=current_admin.id,
        total=len(users),
        synced=synced_count,
        out_of_sync=len(mismatched_users)
    )

    return {
        "total_users": len(users),
        "synced_count": synced_count,
        "out_of_sync_count": len(mismatched_users),
        "mismatched_users": mismatched_users
    }


# ← PHASE 4: Remediation endpoint - manually sync DB to match Casbin


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/sync")
async def sync_users(
    request: Request,
    sync_request: schemas.SyncUsersRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Đồng bộ role từ Casbin về DB cho tất cả users hoặc một nhóm users cụ thể.
    Casbin được coi là source of truth (nguồn chân lý).

    - `user_ids`: Danh sách ID users cần sync. Nếu None hoặc rỗng, sync tất cả users.

    REFACTORED: Business logic extracted to user_service.sync_users_to_casbin()
    Router now only handles HTTP concerns (request/response, DI, admin activity logging)
    """
    # Extract Casbin enforcer from app state (HTTP-specific)
    enforcer = request.app.state.enforcer
    user_ids = sync_request.user_ids

    # Call service layer with injected dependencies (DI pattern)
    result = await user_service.sync_users_to_casbin(
        db=db,
        enforcer=enforcer,
        user_ids=user_ids
    )

    # Commit transaction (router responsibility)
    await db.commit()

    # Best-effort audit log — business change already committed above
    try:
        _, log_callback = await log_admin_activity(
            db=db,
            request=request,
            action="sync_users",
            resource_type="user",
            actor_id=current_admin.id,
            resource_id=None,
            changes={
                "synced_count": result["synced_count"],
                "failed_count": result["failed_count"],
                "user_ids": user_ids or "all"
            }
        )
        await db.commit()
        await log_callback()
    except Exception:
        log.error("Failed to persist audit log for sync_users", exc_info=True)

    log.info(
        "User sync completed",
        admin_id=current_admin.id,
        synced=result["synced_count"],
        failed=result["failed_count"]
    )

    return result


# ===============================================================
# ORGANIZATION & MAJOR MANAGEMENT ROUTES
# ===============================================================




# ============================================================================
# LEAD MANAGEMENT OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_BULK)  # 10/hour - Bulk operation
@router.post("/leads/bulk-assign")
async def bulk_assign_leads(
    request: Request,
    assignment_data: schemas.BulkAssignLeadsSchema,  # Sử dụng schema mới
    current_admin: models.User = CasbinAuth,  # Yêu cầu quyền admin (qua Casbin)
):
    """
    (Admin only) Kích hoạt tác vụ phân công tự động cho một danh sách các Lead ID.
    Các tác vụ sẽ được xử lý dưới nền bởi Celery worker.
    """
    lead_ids = assignment_data.lead_ids
    dispatched_count = 0
    failed_ids = []

    log.info(
        "Received bulk assign request",
        admin_id=current_admin.id,
        lead_count=len(lead_ids),
    )

    for lead_id in lead_ids:
        try:
            # Gọi task Celery cho từng lead_id
            process_automatic_lead_assignment_task.delay(lead_id)
            dispatched_count += 1
            log.debug("Dispatched assignment task", lead_id=lead_id)
        except Exception as e:
            failed_ids.append(lead_id)
            log.error(
                "Failed to dispatch assignment task for lead",
                lead_id=lead_id,
                error=str(e),
                exc_info=True,  # Log traceback nếu có lỗi khi gọi .delay()
            )

    success_rate = (dispatched_count / len(lead_ids)) * 100 if lead_ids else 100
    message = f"Successfully dispatched {dispatched_count}/{len(lead_ids)} ({success_rate:.1f}%) assignment tasks."

    if failed_ids:
        log.warning(
            "Some tasks failed to dispatch",
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
        )
        message += f" Failed to dispatch for {len(failed_ids)} leads."
        # Bạn có thể cân nhắc trả về status code khác nếu có lỗi, ví dụ 207 Multi-Status
        # Hoặc vẫn trả về 202 nhưng kèm thông tin lỗi chi tiết hơn trong body
        # return {"detail": message, "failed_ids": failed_ids}

    log.info(
        "Finished processing bulk assign request",
        dispatched=dispatched_count,
        failed=len(failed_ids),
    )
    return {"detail": message}




@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/leads/import")
async def import_leads_from_file(
    request: Request,
    file: UploadFile = File(
        ..., description="CSV or Excel file containing lead data (.csv, .xlsx)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Import leads từ file CSV hoặc Excel.
    File cần có các cột: 'full_name', 'email', 'phone', 'source', 'unit_id', 'offering_id' (tùy chọn).
    Endpoint sẽ tạo leads trong DB nhưng **không** tự động phân công.
    Trả về kết quả import bao gồm ID các lead đã tạo và danh sách lỗi.

    REFACTORED: Business logic extracted to lead_service.import_leads_from_file_content()
    Router now only handles HTTP concerns (file reading, exception conversion)
    """
    log.info(
        "Received lead import request",
        admin_id=current_admin.id,
        filename=file.filename,
    )

    # Read file content (HTTP-specific operation)
    try:
        content = await file.read()
    except Exception as e:
        log.error(
            "Failed to read uploaded file",
            filename=file.filename,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {e}",
        )
    finally:
        await file.close()

    # Call service layer with file content (DI pattern)
    try:
        result, callback = await lead_service.import_leads_from_file_content(
            file_content=content,
            filename=file.filename or "unknown",
            db=db,
        )
        await db.commit()
        await callback()
        return result

    except ValueError as e:
        # Service raises ValueError for validation errors
        # Router converts to HTTPException (HTTP concern)
        log.warning(
            "Lead import validation failed",
            admin_id=current_admin.id,
            filename=file.filename,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ===============================================================
# ACTIVITY LOGS & STATISTICS ROUTES
# ===============================================================




# ============================================================================
# ANALYTICS & MONITORING
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/statistics")
async def get_user_statistics(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """(Admin only) Lấy thống kê tổng quan về users cho dashboard."""
    return await activity_service.get_user_statistics(db)


# =============================================================================
# ADVANCED CASBIN PERMISSION TOOLS
# =============================================================================
# NOTE: activity-logs endpoint moved to top-level admin router (admin/__init__.py)
# to support all resource types (users, casbin_policy, leads, etc.)
# Available at: /api/admin/activity-logs
# =============================================================================

# ============================================================================
# GENERIC USER CRUD OPERATIONS (/{user_id})
# ============================================================================
# ⚠️ IMPORTANT: These routes MUST be declared LAST to avoid conflicts with
# specific routes like /export, /statistics, /activity-logs, etc.
# FastAPI matches routes in declaration order, so:
#   - /users/export would match GET /users/{user_id} if /{user_id} comes first
#   - Moving /{user_id} routes to the end ensures specific routes match first
# ============================================================================

@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/{user_id}", response_model=schemas.UserAdminResponse)
async def get_user_details(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin/Manager) Get user details.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to users in managed units
    - ✓ IDOR Protection: Enabled

    Admin: Can view all users
    Manager: Can view users in managed units only
    """
    # Verify ownership
    db_user = await deps.verify_user_management_permission(
        target_user_id=user_id,
        db=db,
        current_user=current_admin
    )
    return db_user




@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put("/{user_id}", response_model=schemas.UserAdminResponse)
async def update_existing_user(
    request: Request,  # Required for rate limiter (must be first)
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),  # <-- Sửa lại thành Optional[str]
    phone_number: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    skills: Optional[str] = Form(None),  # Nhận JSON string từ form-data
    max_capacity: Optional[int] = Form(None),
    unit_id: Optional[int] = Form(None),  # Organizational unit assignment
):
    """
    (Admin/Manager) Update user information.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to users in managed units
    - ✓ IDOR Protection: Enabled

    Admin: Can update all users
    Manager: Can update users in managed units only
    """
    # Verify ownership first
    db_user = await deps.verify_user_management_permission(
        target_user_id=user_id,
        db=db,
        current_user=current_admin
    )

    # Xây dựng dict chỉ chứa các trường được cung cấp.
    # Convention với Form-data:
    #   - field không gửi (None) → skip (giữ giá trị cũ)
    #   - field gửi rỗng "" → clear (set NULL) cho nullable column
    #   - field gửi value → set sau khi strip()
    # Áp dụng cho `full_name`/`phone_number` (nullable). `role`/`status`
    # vẫn skip empty vì model nullable=False.
    update_dict = {}
    if full_name is not None:
        stripped = full_name.strip()
        update_dict["full_name"] = stripped if stripped else None
    if phone_number is not None:
        stripped = phone_number.strip()
        update_dict["phone_number"] = stripped if stripped else None
    if role is not None and role.strip():
        update_dict["role"] = role.strip()
    if status is not None and status.strip():
        update_dict["status"] = status.strip()
    if max_capacity is not None and max_capacity >= 0:
        update_dict["max_capacity"] = max_capacity

    # Handle unit_id assignment - validate unit exists
    # ✅ PHASE 8: Use OrganizationRepository instead of db.get()
    if unit_id is not None:
        if unit_id > 0:  # Assigning to a unit
            from app.repositories.organization_repository import OrganizationRepository
            org_repo = OrganizationRepository(db)
            unit = await org_repo.get_by_id_full(unit_id)
            if not unit:
                raise ResourceNotFoundError(
                    detail=f"Organization unit with id {unit_id} not found."
                )
            update_dict["unit_id"] = unit_id
        else:  # Remove unit assignment (set to None)
            update_dict["unit_id"] = None

    if skills is not None:
        try:
            # Chuyển đổi chuỗi JSON 'skills' từ Form thành đối tượng Python (list)
            import json

            update_dict["skills"] = json.loads(skills)
            if not isinstance(update_dict["skills"], list):
                raise ValueError("Skills must be a JSON list of strings")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f'Invalid format for skills. Must be a JSON string of a list (e.g., \'["skill1", "skill2"]\'): {e}',
            )
    # Chỉ xử lý email nếu được cung cấp và không rỗng
    if email is not None and email.strip():
        cleaned_email = email.strip()
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(cleaned_email)
            
            # ✅ SỬA: Thêm kiểm tra DB (giống hệt logic của profile.py)
            if valid_email != db_user.email:
                existing_user = await user_service.get_user_by_email(db, valid_email)
                if existing_user:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail="Email already registered by another user",
                    )
            update_dict["email"] = valid_email
            
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid email format: {cleaned_email}. Error: {error_detail}",
            )
        # (Thêm HTTPException nếu raise từ logic check DB)
        except HTTPException as e: 
            raise e

    # Track changes for activity log
    changes = {}
    if update_dict:
        for key, new_value in update_dict.items():
            old_value = getattr(db_user, key, None)
            if old_value != new_value:
                changes[key] = {"old": str(old_value), "new": str(new_value)}

    # Tạo schema UserUpdate CHỈ với các dữ liệu đã được xác thực
    user_in = schemas.UserUpdate(**update_dict)

    # ← PHASE 1: Lấy enforcer từ app state để sync Casbin khi role thay đổi
    enforcer = request.app.state.enforcer

    # ✅ REFACTORED (Issue #3): Read avatar file content in router layer
    avatar_content = None
    avatar_filename = None
    if avatar and avatar.filename:
        # Validate file size before reading (DoS protection)
        avatar.file.seek(0, 2)  # Seek to end
        file_size = avatar.file.tell()
        avatar.file.seek(0)  # Reset to beginning

        if file_size > settings.MAX_AVATAR_CONTENT_LENGTH:
            raise HTTPException(
                status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB."
            )

        avatar_content = await avatar.read()
        avatar_filename = avatar.filename

    # Truyền avatar và enforcer vào hàm service
    updated_user, callback = await user_service.update_user(
        db, db_user, user_in, enforcer=enforcer,
        avatar_content=avatar_content,  # ✅ REFACTORED: Pass bytes instead of UploadFile
        avatar_filename=avatar_filename,  # ✅ REFACTORED: Pass filename
        assigned_by_user_id=current_admin.id  # ✅ PHASE 2: Track who made the assignment
    )

    # ✅ TRANSACTION PATTERN: Commit and execute callback
    await db.commit()
    await callback()

    # Best-effort audit log — business change already committed above
    try:
        _, log_callback = await log_admin_activity(
            db=db,
            request=request,
            action="update_user",
            resource_type="user",
            actor_id=current_admin.id,
            target_user_id=updated_user.id,
            resource_id=updated_user.id,
            description=f"Admin updated user: {updated_user.username}",
            changes=changes if changes else None,
        )
        await db.commit()
        await log_callback()
    except Exception:
        await db.rollback()
        log.error("Failed to persist audit log for update_user", user_id=updated_user.id, exc_info=True)

    # ✅ NOTIFICATION 2.0: Dispatch USER_ROLE_CHANGED if role or unit changed
    if "role" in changes or "unit_id" in changes:
        from app.services.notification_dispatcher import safe_dispatch, _rooms_for_user
        from app.core.events import SystemEvents

        old_unit_str = changes.get("unit_id", {}).get("old") if "unit_id" in changes else None
        old_unit_id = None
        if old_unit_str and old_unit_str != "None":
            try:
                old_unit_id = int(old_unit_str)
            except (ValueError, TypeError):
                pass

        await safe_dispatch(
            db=db,
            event=SystemEvents.USER_ROLE_CHANGED,
            payload={
                "user_id": updated_user.id,
                "old_role": changes.get("role", {}).get("old", updated_user.role),
                "new_role": changes.get("role", {}).get("new", updated_user.role),
                "old_unit_id": old_unit_id,
                "new_unit_id": updated_user.unit_id,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"user_role_changed:{updated_user.id}:{updated_user.role}:{updated_user.unit_id}",
            rooms=_rooms_for_user(updated_user.id),
        )

    # Dispatch USER_DEACTIVATED notification if status changed to inactive
    if "status" in changes and changes["status"]["new"] == "inactive":
        from app.services.notification_dispatcher import safe_dispatch, _rooms_for_user
        from app.core.events import SystemEvents
        await safe_dispatch(
            db=db,
            event=SystemEvents.USER_DEACTIVATED,
            payload={
                "user_id": updated_user.id,
                "username": updated_user.username,
                "old_status": changes["status"]["old"],
                "reason": "Account deactivated by administrator",
                "actor_id": current_admin.id,
            },
            dedupe_key=f"user_deactivated:{updated_user.id}",
            skip_preference_check=True,  # Critical notification
            rooms=_rooms_for_user(updated_user.id),
        )

    # Send notification to user if admin updated their info
    if current_admin.id != updated_user.id and changes:
        log.info(
            "Admin updated user info, dispatching notification",
            admin_id=current_admin.id,
            target_user_id=updated_user.id,
            changes=list(changes.keys()),
        )
        change_description = ", ".join([f"{key}" for key in changes.keys()])
        from app.services.notification_dispatcher import safe_dispatch, _rooms_for_user
        from app.core.events import SystemEvents

        await safe_dispatch(
            db=db,
            event=SystemEvents.USER_PROFILE_UPDATED,
            payload={
                "user_id": updated_user.id,
                "updated_fields": change_description,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"user_profile_updated:{updated_user.id}",
            rooms=_rooms_for_user(updated_user.id),
        )
    else:
        log.debug(
            "Skipping notification",
            admin_id=current_admin.id,
            target_user_id=updated_user.id,
            same_user=current_admin.id == updated_user.id,
            has_changes=bool(changes),
        )

    return updated_user



# === KẾT THÚC HÀM CẬP NHẬT ===


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete("/{user_id}")
async def delete_existing_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin/Manager) Delete a user.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to users in managed units
    - ✓ IDOR Protection: Enabled

    **Business Rules:**
    - Cannot delete yourself (returns 403)
    - Cannot delete the last active admin (returns 400 BusinessRuleViolation).
      Guard is enforced atomically in `user_service.delete_user()` via
      `SELECT ... FOR UPDATE` on the active-admin row set.

    Admin: Can delete all users (except self)
    Manager: Can delete users in managed units only (except self)
    """
    # Safety check: Cannot delete self
    if user_id == current_admin.id:
        raise PermissionDeniedError(detail="You cannot delete your own account")

    # Verify ownership
    db_user = await deps.verify_user_management_permission(
        target_user_id=user_id,
        db=db,
        current_user=current_admin
    )
    username = db_user.username if db_user else f"User#{user_id}"

    # ⚠️ IMPORTANT: Log activity BEFORE deleting user to avoid FK constraint violation
    # The activity_log.target_user_id references user.id, so user must exist when logging
    _, log_callback = await log_admin_activity(
        db=db,
        request=request,
        action="delete_user",
        resource_type="user",
        actor_id=current_admin.id,
        target_user_id=user_id,
        resource_id=user_id,
        description=f"Admin deleted user: {username}",
    )

    # Delete user AFTER logging (service handles cascading deletes)
    await user_service.delete_user(db, user_id)

    await db.commit()
    await log_callback()

    return None

