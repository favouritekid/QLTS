# app/routers/admin/roles.py
"""
Role & Policy Management Admin Router

Handles all Casbin policy and role management operations including:
- Policy CRUD (create, read, delete)
- Role assignment (uses role_service from PHASE 1)
- Grouping policies (role inheritance)
- Role management (atomic operations)
- Policy templates
- Batch operations
- Validation & simulation
- Analytics & insights
- Feature flags

PHASE 2A: Extracted from monolithic admin.py
Dependencies: role_service, activity_service (from PHASE 1), Casbin enforcer

Complexity: HIGH (Casbin integration, atomic operations, policy validation)
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

import casbin
import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import CasbinAuth  # Phase 2.2
from app.database import get_db
from app.schemas.permissions import (
    PolicyCreate,
    RoleAssignment,
    GroupingPolicyCreate,
)
from app.services import activity_service, role_service
from app.utils.exceptions import (
    BadRequest,
    ConflictError,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from app.socket_manager import sio
from app.socket_metrics import socket_events_emitted_total
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(prefix="/roles", tags=["Admin - Roles & Permissions"])



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
) -> models.UserActivityLog:
    """Trích IP/UA từ request rồi uỷ quyền cho ``activity_service``.

    Trả về **một** ``UserActivityLog``, KHÔNG phải tuple. Caller vẫn phải
    ``db.commit()`` — hàm này chỉ ``flush``.

    ⚠️ Đừng khôi phục kiểu ``Tuple[UserActivityLog, Callable]``. Contract một
    đối tượng là contract của ``activity_service.log_activity`` và đã có test
    service khoá nó; bọc lại thành tuple ở đây là dựng một callback no-op chỉ
    để chiều caller — hai nguồn chuẩn cho cùng một câu hỏi.
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


async def commit_and_log(db: AsyncSession, log_result: models.UserActivityLog):
    """Chốt giao dịch chứa bản ghi audit vừa flush.

    ``log_result`` là **một** ``UserActivityLog``. Bản trước nhận
    ``Tuple[UserActivityLog, Callable]`` rồi ``_, callback = log_result``, trong
    khi ``activity_service.log_activity`` đã trả về một đối tượng — mọi lời gọi
    ném ``TypeError: cannot unpack non-iterable UserActivityLog object``.

    Tham số vẫn được GIỮ dù thân hàm không đọc tới: nó làm thứ tự bắt buộc
    (ghi audit rồi mới commit) **hiện rõ tại callsite**. Nó không chứng minh
    được đối tượng truyền vào đúng là bản ghi vừa tạo — chỉ có phép kiểm kiểu
    bên dưới chặn được thứ hoàn toàn sai kiểu. Bỏ tham số đi thì
    ``commit_and_log(db)`` trông vẫn hợp lệ, và trật tự ấy biến mất khỏi trang
    giấy.

    Không còn ``callback``: ``log_activity`` không sinh việc hậu-commit nào.
    """
    if not isinstance(log_result, models.UserActivityLog):
        raise TypeError(
            "commit_and_log nhan mot UserActivityLog, nhan duoc %r"
            % type(log_result).__name__
        )
    await db.commit()


async def emit_policy_update(operation: str, data: dict):
    """
    Emit Socket.IO event for policy updates.

    This notifies all connected clients (and potentially other workers)
    that a policy has been changed, allowing them to:
    1. Invalidate their React Query cache
    2. Reload their Casbin enforcer

    Args:
        operation: Type of operation (create, delete, update)
        data: Policy data that was changed
    """
    event_data = {
        "resource_type": "policy",
        "operation": operation,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await sio.emit("data_updated", event_data)
        socket_events_emitted_total.labels(event_type="data_updated").inc()
        log.info("Emitted policy update event", operation=operation, data=data)
    except Exception as e:
        log.error("Failed to emit policy update event", error=str(e), operation=operation)


# ============================================================================
# POLICY CRUD OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/policies", response_model=List[List[str]])
async def get_all_policies(
    request: Request, current_admin: models.User = CasbinAuth
):
    """(Admin only) Lấy tất cả các chính sách (policies) hiện có."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    # SỬA: Bỏ await vì get_policy() không phải là async
    policies = enforcer.get_policy()
    return policies




@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def add_new_policy(
    policy_in: PolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Add a new policy with validation, logging, and event consistency.

    **Event Flow (Transaction Safety):**
    1. Add policy via CasbinPolicyService (with template tracking)
    2. Log activity to DB
    3. COMMIT transaction ← CRITICAL CHECKPOINT
    4. Emit socket event (error isolated)
    5. Reload policy
    6. Return success

    **Security:**
    - ✓ Role: Admin only (Casbin)
    - ✓ Transaction: Commit before emit
    - ✓ Error Isolation: Socket failures don't crash API
    - ✓ Template Tracking: Policies marked with template_id='_manual'
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    # 1. Add policy via service (with template tracking)
    result = await casbin_service.add_policies_batch(
        policies=[(policy_in.subject, policy_in.object, policy_in.action)],
        validate=True,
        template_id="_manual",  # Mark as manually added via UI
        applied_by=current_admin.id,
    )

    if result["added"] == 0:
        if result["skipped"] > 0:
            raise DuplicateResourceError("Policy already exists.")
        if result["errors"]:
            raise DuplicateResourceError(result["errors"][0])

    # 2. Log activity to DB + commit
    await commit_and_log(db, await log_admin_activity(
        db=db,
        request=request,
        action="add_policy",
        resource_type="casbin_policy",
        actor_id=current_admin.id,
        description=f"Added policy: {policy_in.subject} → {policy_in.object} → {policy_in.action}",
        changes={
            "subject": policy_in.subject,
            "object": policy_in.object,
            "action": policy_in.action,
        },
    ))

    # 4. Emit socket event (error isolated via emit_policy_update)
    # Note: emit_policy_update already has try-except, so failures won't crash API
    await emit_policy_update("create", {
        "subject": policy_in.subject,
        "object": policy_in.object,
        "action": policy_in.action,
    })

    # 5. Reload policy for current worker to ensure consistency
    # Dưới lock: một lượt reload chen vào giữa thao tác nhóm sẽ thay model
    # ngay dưới chân nó, làm snapshot vừa dựng thành vô nghĩa.
    from app.services.casbin_service import khoa_enforcer

    async with khoa_enforcer(enforcer):
        await enforcer.load_policy()

    # 6. Return success
    return {"detail": "Policy added successfully."}




@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete("/policies", status_code=status.HTTP_200_OK)
async def delete_policy(
    policy_in: PolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Delete a policy with safety checks, logging, and event consistency.

    **Event Flow (Transaction Safety):**
    1. Validate policy removal (safety checks)
    2. Remove policy from Casbin
    3. Log activity to DB
    4. COMMIT transaction ← CRITICAL CHECKPOINT
    5. Emit socket event (error isolated)
    6. Reload policy
    7. Return success

    **Security:**
    - ✓ Role: Admin only (Casbin)
    - ✓ Safety: Cannot remove critical policies
    - ✓ Transaction: Commit before emit
    - ✓ Error Isolation: Socket failures don't crash API
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    # 1. SAFETY CHECK: Validate removal operation
    validation = await casbin_service.validate_policy_removal(
        policy_in.subject,
        policy_in.object,
        policy_in.action,
    )

    if not validation.is_safe:
        raise PermissionDeniedError(
            detail=f"Cannot remove this policy for safety reasons: {'; '.join(validation.warnings)}"
        )

    # 2. Remove policy from Casbin — bằng ĐỦ bốn trường.
    # Payload API chỉ có ba trường và chỉ tạo được policy `allow`, nên chuẩn
    # hoá về `eft="allow"` là đúng ngữ nghĩa của nó. KHÔNG dùng remove-filter
    # theo ba trường: nó khớp cả rule `deny` cùng (sub, obj, act) và xoá nhầm
    # deny là âm thầm MỞ quyền.
    from app.services.casbin_service import xoa_rule_chinh_xac

    removed = await xoa_rule_chinh_xac(
        enforcer, (policy_in.subject, policy_in.object, policy_in.action)
    )
    if not removed:
        raise ResourceNotFoundError("Policy not found or could not be removed.")

    # 3. Log activity to DB
    await commit_and_log(db, await log_admin_activity(
        db=db,
        request=request,
        action="remove_policy",
        resource_type="casbin_policy",
        actor_id=current_admin.id,
        description=f"Removed policy: {policy_in.subject} → {policy_in.object} → {policy_in.action}",
        changes={
            "subject": policy_in.subject,
            "object": policy_in.object,
            "action": policy_in.action,
        },
    ))

    # 5. Emit socket event (error isolated via emit_policy_update)
    # Note: emit_policy_update already has try-except, so failures won't crash API
    await emit_policy_update("delete", {
        "subject": policy_in.subject,
        "object": policy_in.object,
        "action": policy_in.action,
    })

    # 6. Reload policy for current worker to ensure consistency
    from app.services.casbin_service import khoa_enforcer

    async with khoa_enforcer(enforcer):
        await enforcer.load_policy()

    # 7. Return success
    return {"detail": "Policy removed successfully."}




# ============================================================================
# ROLE ASSIGNMENT OPERATIONS (Uses role_service from PHASE 1!)
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/assign", status_code=status.HTTP_201_CREATED)
async def assign_role_to_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """(Admin only) Gán một vai trò cho người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    from app.services.casbin_service import khoa_enforcer

    async with khoa_enforcer(enforcer):
        added = await enforcer.add_grouping_policy(
            f"user:{assignment.user_id}", assignment.role
        )
    if not added:
        raise DuplicateResourceError("User already has this role.")

    # KHÔNG gọi `save_policy()`. Đã đo hai điều:
    #  - `auto_save` bật mặc định và không nơi nào tắt, nên
    #    `add/remove_grouping_policy` ĐÃ tự ghi hàng xuống `casbin_rule`;
    #  - `save_policy()` của adapter async là `DELETE FROM casbin_rule` rồi ghi
    #    lại TOÀN BỘ model — một lệnh xoá trắng bảng trên đường chỉ định đổi
    #    MỘT hàng. Model lệch CSDL vì bất kỳ lý do gì (reload chen ngang, một
    #    worker nạp thiếu, `RUN_CASBIN_LOAD_ON_STARTUP=false`) đều bị ghi đè
    #    thành sự thật mới.
    # Chú thích cũ "writes to casbin_rule table in SAME transaction" cũng sai:
    # adapter mở session RIÊNG, không nằm trong transaction của người gọi.

    return {"detail": "Role assigned."}




@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete("/revoke")
async def remove_role_from_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """(Admin only) Xóa (thu hồi) vai trò của người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    from app.services.casbin_service import khoa_enforcer

    async with khoa_enforcer(enforcer):
        removed = await enforcer.remove_grouping_policy(
            f"user:{assignment.user_id}", assignment.role
        )
    if not removed:
        raise ResourceNotFoundError(
            "Role assignment not found or could not be removed."
        )

    # KHÔNG gọi `save_policy()`. Đã đo hai điều:
    #  - `auto_save` bật mặc định và không nơi nào tắt, nên
    #    `add/remove_grouping_policy` ĐÃ tự ghi hàng xuống `casbin_rule`;
    #  - `save_policy()` của adapter async là `DELETE FROM casbin_rule` rồi ghi
    #    lại TOÀN BỘ model — một lệnh xoá trắng bảng trên đường chỉ định đổi
    #    MỘT hàng. Model lệch CSDL vì bất kỳ lý do gì (reload chen ngang, một
    #    worker nạp thiếu, `RUN_CASBIN_LOAD_ON_STARTUP=false`) đều bị ghi đè
    #    thành sự thật mới.
    # Chú thích cũ "writes to casbin_rule table in SAME transaction" cũng sai:
    # adapter mở session RIÊNG, không nằm trong transaction của người gọi.

    return {"detail": "Role removed from user."}




@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/users/{user_id}/roles")
async def get_user_roles(
    user_id: int,
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """(Admin only) Lấy tất cả các roles (grouping policies) của một user."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Lấy tất cả roles của user
    user_subject = f"user:{user_id}"
    roles = await enforcer.get_roles_for_user(user_subject)

    return roles




@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/{role_name}/users")
async def get_role_users(
    role_name: str,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """(Admin only) Lấy tất cả users có một role cụ thể."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Get all grouping policies (user-to-role assignments)
    # Note: get_grouping_policy() is NOT async even in AsyncEnforcer
    all_grouping = enforcer.get_grouping_policy()

    # Filter to find users with this specific role
    user_ids = []
    for group in all_grouping:
        # group format: ["user:123", "role:manager"]
        if len(group) >= 2 and group[1] == role_name:
            # Extract user ID from "user:123"
            user_subject = group[0]
            if user_subject.startswith("user:"):
                try:
                    user_id = int(user_subject.split(":")[1])
                    user_ids.append(user_id)
                except (ValueError, IndexError):
                    continue

    # Fetch user details from database using Repository
    if not user_ids:
        return {"role": role_name, "user_count": 0, "users": []}

    from app.repositories import UserRepository
    user_repo = UserRepository(db)
    users = await user_repo.get_by_ids(user_ids)

    # Return user info with all Casbin roles 
    user_list = []
    for user in users:
        user_subject = f"user:{user.id}"
        # Get all roles for this user from Casbin
        casbin_roles = await enforcer.get_roles_for_user(user_subject)

        user_list.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,  # DB role (may differ from Casbin role)
            "casbin_roles": casbin_roles,  # All Casbin roles
        })

    return {
        "role": role_name,
        "user_count": len(user_list),
        "users": user_list,
    }




@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete("/{role_name}/users")
async def remove_role_from_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
    user_ids: List[int] = Body(...),
    role_to_remove: str = Body(...),
):
    """
    (Admin only) Remove a specific role from multiple users.

    SMART BEHAVIOR:
    - If user has ONLY this role → remove it and auto-assign role:user
    - If user has MULTIPLE roles → only remove this role, keep others
    - Updates database user.role to reflect remaining highest-priority role

    Priority order: admin > manager > officer > user

    REFACTORED: Business logic extracted to role_service.remove_role_from_users()
    Router now only handles HTTP concerns (request/response, dependency injection)
    """
    # Extract Casbin enforcer from app state (HTTP-specific)
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Call service layer with injected dependencies (DI pattern)
    result, callback = await role_service.remove_role_from_users(
        db=db,
        enforcer=enforcer,
        user_ids=user_ids,
        role_to_remove=role_to_remove,
    )
    await db.commit()
    await callback()

    return result




# ============================================================================
# GROUPING POLICY OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/grouping-policies", status_code=status.HTTP_201_CREATED)
async def add_grouping_policy(
    grouping: GroupingPolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Add a grouping policy for role inheritance or role assignment.

    This endpoint supports two use cases:
    1. Role-to-role inheritance: g, role:support, role:user
    2. User-to-role assignment: g, user:5, role:manager

    Examples:
        - Make role:support inherit from role:user:
          POST /grouping-policies
          {"subject": "role:support", "parent_role": "role:user"}

        - Assign role:manager to user:5:
          POST /grouping-policies
          {"subject": "user:5", "parent_role": "role:manager"}
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    from app.services.casbin_service import khoa_enforcer

    # Add the grouping policy (g rule)
    async with khoa_enforcer(enforcer):
        added = await enforcer.add_grouping_policy(
            grouping.subject, grouping.parent_role
        )

    if not added:
        raise DuplicateResourceError(
            f"Grouping policy already exists: {grouping.subject} → {grouping.parent_role}"
        )

    # KHÔNG gọi `save_policy()`. Đã đo hai điều:
    #  - `auto_save` bật mặc định và không nơi nào tắt, nên
    #    `add/remove_grouping_policy` ĐÃ tự ghi hàng xuống `casbin_rule`;
    #  - `save_policy()` của adapter async là `DELETE FROM casbin_rule` rồi ghi
    #    lại TOÀN BỘ model — một lệnh xoá trắng bảng trên đường chỉ định đổi
    #    MỘT hàng. Model lệch CSDL vì bất kỳ lý do gì (reload chen ngang, một
    #    worker nạp thiếu, `RUN_CASBIN_LOAD_ON_STARTUP=false`) đều bị ghi đè
    #    thành sự thật mới.
    # Chú thích cũ "writes to casbin_rule table in SAME transaction" cũng sai:
    # adapter mở session RIÊNG, không nằm trong transaction của người gọi.

    # Log activity
    await commit_and_log(db, await log_admin_activity(
        db=db,
        request=request,
        action="add_grouping_policy",
        resource_type="policy",
        actor_id=current_admin.id,
        resource_id=None,
        changes={
            "subject": grouping.subject,
            "parent_role": grouping.parent_role,
            "type": "grouping_policy",
        },
    ))

    log.info(
        "Grouping policy added",
        admin_id=current_admin.id,
        subject=grouping.subject,
        parent_role=grouping.parent_role,
    )

    return {
        "detail": f"Grouping policy added: {grouping.subject} → {grouping.parent_role}",
        "subject": grouping.subject,
        "parent_role": grouping.parent_role,
    }




@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete("/grouping-policies")
async def delete_grouping_policy(
    grouping: GroupingPolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Remove a grouping policy.

    Removes a grouping policy for either:
    1. Role-to-role inheritance
    2. User-to-role assignment
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    from app.services.casbin_service import khoa_enforcer

    # Remove the grouping policy
    async with khoa_enforcer(enforcer):
        removed = await enforcer.remove_grouping_policy(
            grouping.subject, grouping.parent_role
        )

    if not removed:
        raise ResourceNotFoundError(
            f"Grouping policy not found: {grouping.subject} → {grouping.parent_role}"
        )

    # KHÔNG gọi `save_policy()`. Đã đo hai điều:
    #  - `auto_save` bật mặc định và không nơi nào tắt, nên
    #    `add/remove_grouping_policy` ĐÃ tự ghi hàng xuống `casbin_rule`;
    #  - `save_policy()` của adapter async là `DELETE FROM casbin_rule` rồi ghi
    #    lại TOÀN BỘ model — một lệnh xoá trắng bảng trên đường chỉ định đổi
    #    MỘT hàng. Model lệch CSDL vì bất kỳ lý do gì (reload chen ngang, một
    #    worker nạp thiếu, `RUN_CASBIN_LOAD_ON_STARTUP=false`) đều bị ghi đè
    #    thành sự thật mới.
    # Chú thích cũ "writes to casbin_rule table in SAME transaction" cũng sai:
    # adapter mở session RIÊNG, không nằm trong transaction của người gọi.

    # Log activity
    await commit_and_log(db, await log_admin_activity(
        db=db,
        request=request,
        action="remove_grouping_policy",
        resource_type="policy",
        actor_id=current_admin.id,
        resource_id=None,
        changes={
            "subject": grouping.subject,
            "parent_role": grouping.parent_role,
            "type": "grouping_policy",
        },
    ))

    log.info(
        "Grouping policy removed",
        admin_id=current_admin.id,
        subject=grouping.subject,
        parent_role=grouping.parent_role,
    )

    return {
        "detail": f"Grouping policy removed: {grouping.subject} → {grouping.parent_role}"
    }


# ===============================================================
# ADVANCED POLICY MANAGEMENT ROUTES (NEW)
# ===============================================================




# ============================================================================
# ROLE MANAGEMENT OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("")
async def get_all_roles_with_info(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get all roles with metadata and policy counts.

    Returns detailed information about all roles including:
    - System roles (admin, manager, officer, user)
    - Custom roles created by admins
    - Policy counts for each role
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    roles = await casbin_service.get_all_roles()
    return {"roles": roles}




@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete("/{role_name}")
async def delete_role_atomic(
    role_name: str,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Atomically delete a role with all its associations.

    This endpoint performs ALL deletion operations in a single atomic transaction:
    1. Validates role can be deleted (not a system role)
    2. Finds all users with this role (DB + Casbin)
    3. Reassigns users to role:user
    4. Removes all permission policies (p rules)
    5. Removes all grouping policies (g rules)
    6. Commits everything atomically

    This prevents race conditions that could occur with client-side orchestration.

    SAFETY GUARANTEES:
    - All operations happen in a DB transaction
    - Either ALL succeed or ALL fail (rollback)
    - No zombie roles (roles without permissions)
    - No orphaned users (users with deleted roles)

    Args:
        role_name: Role identifier (e.g., "role:support")

    Returns:
        Success message with deletion statistics

    Raises:
        400: If trying to delete a system role
        404: If role doesn't exist
    """
    from app.services import role_service

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    try:
        # Delegate to Service Layer (Refactoring Pattern A)
        # Service handles validation, logic, and atomic operations
        result, post_commit = await role_service.delete_role_atomic(
            db=db,
            role_name=role_name,
            enforcer=enforcer
        )

        # Commit transaction
        await db.commit()
        
        # Execute post-commit side effects
        await post_commit()
        
        log.info(
            "Role deleted atomically",
            admin_id=current_admin.id,
            role_name=role_name,
        )

    except (ConflictError, DuplicateResourceError, PermissionDeniedError,
            ResourceNotFoundError, BadRequest) as e:
        # Domain exception: rollback rồi NÉM LẠI để middleware giữ đúng mã —
        # 409 / 400 / 404. Bọc chúng thành 500 là xoá mất thông tin người gọi
        # cần: "không xoá được vì còn policy" (409, hành động được) khác hẳn
        # "lỗi bất ngờ" (500, không hành động được). Với A01, một 500 che mất
        # 409 làm người vận hành tưởng là trục trặc tạm thời và thử lại mãi.
        await db.rollback()
        log.warning(
            "Role deletion refused (domain)",
            role_name=role_name,
            error=str(e),
            loai=type(e).__name__,
        )
        raise
    except Exception as e:
        # Chỉ lỗi BẤT NGỜ mới thành 500.
        await db.rollback()
        log.error(
            "Failed to delete role atomically",
            role_name=role_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete role. Please try again later.",
        )

    # Best-effort audit log — delete already committed, don't fail the request
    try:
        await commit_and_log(db, await log_admin_activity(
            db=db,
            request=request,
            action="delete_role_atomic",
            resource_type="role",
            actor_id=current_admin.id,
            resource_id=None,
            changes=result,
        ))
    except Exception:
        log.error("Failed to persist audit log for role deletion", role_name=role_name, exc_info=True)

    return result



# ============================================================================
# POLICY TEMPLATES
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/templates")
async def get_policy_templates(
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get all available policy templates.

    Templates provide pre-configured sets of policies for common roles.
    Admins can apply templates to quickly set up permissions.
    """
    from app.casbin_config.policy_templates import POLICY_TEMPLATES

    templates = []
    for template_id, template_data in POLICY_TEMPLATES.items():
        templates.append({
            "id": template_id,
            "display_name": template_data["display_name"],
            "description": template_data["description"],
            "category": template_data["category"],
            "policies": [
                {
                    "subject": policy["subject"],
                    "object": policy["object"],
                    "action": policy["action"],
                }
                for policy in template_data["policies"]
            ],
        })

    return {"templates": templates}




@limiter.limit(RateLimits.ADMIN_BULK)  # 10/hour - Bulk operation
@router.post("/templates/apply")
async def apply_template_to_role(
    request: Request,
    template_req: schemas.TemplateApplicationRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Apply a policy template to a role.

    This is a convenient way to quickly set up permissions for a role
    using pre-configured templates.

    Example: Apply "officer" template to "role:custom" to give it all
    officer permissions.
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    result = await casbin_service.apply_template_to_role(
        template_req.template_id,
        template_req.role,
        validate=template_req.run_validation,
        applied_by=current_admin.id,
    )

    # Log activity
    if result.get("added", 0) > 0:
        await commit_and_log(db, await log_admin_activity(
            db=db,
            request=request,
            action="apply_policy_template",
            resource_type="casbin_policy",
            actor_id=current_admin.id,
            description=f"Applied template '{template_req.template_id}' to '{template_req.role}'",
            changes={
                "template_id": template_req.template_id,
                "role": template_req.role,
                "policies_added": result.get("added", 0),
            },
        ))

    return result




# ============================================================================
# BATCH OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_BULK)  # 10/hour - Bulk operation
@router.post("/policies/batch")
async def add_policies_batch(
    request: Request,
    batch_req: schemas.PolicyBatchRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Add multiple policies in a batch operation.

    Supports:
    - Validation before applying
    - Dry-run mode (preview without applying)
    - Automatic safety checks

    Returns detailed results including successes, failures, and warnings.
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    # Convert to tuples
    policies_tuples = [
        (p.subject, p.object, p.action)
        for p in batch_req.policies
    ]

    # Dry run - just validate without applying
    if batch_req.dry_run:
        result = {
            "added": 0,
            "skipped": 0,
            "errors": [],
            "warnings": ["DRY RUN: No policies were actually added"],
        }

        for subject, obj, action in policies_tuples:
            validation = await casbin_service.validate_policy_addition(subject, obj, action)
            if not validation.is_valid:
                result["errors"].append(f"Invalid: {subject} {obj} {action}")
            result["warnings"].extend(validation.warnings)

        return result

    # Actually add policies (manual batch, no template)
    result = await casbin_service.add_policies_batch(
        policies_tuples,
        validate=batch_req.run_validation,
        template_id=None,  # Manual batch operation
        applied_by=current_admin.id
    )

    # Log activity for each added policy
    if result["added"] > 0:
        await commit_and_log(db, await log_admin_activity(
            db=db,
            request=request,
            action="batch_add_policies",
            resource_type="casbin_policy",
            actor_id=current_admin.id,
            description=f"Batch added {result['added']} policies",
            changes={
                "added": result["added"],
                "skipped": result["skipped"],
                "policies": [f"{p[0]} → {p[1]} → {p[2]}" for p in policies_tuples],
            },
        ))

    return result




# ============================================================================
# VALIDATION & SIMULATION
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/policies/validate")
async def validate_policy_operation(
    request: Request,
    validation_req: schemas.PolicyValidationRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Validate a policy operation before applying.

    Checks for:
    - Critical policy protection (prevent admin lockout)
    - Overly permissive policies
    - Impact on users
    - Safety warnings

    Use this before deleting policies to prevent accidents.
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    if validation_req.operation == "remove":
        validation = await casbin_service.validate_policy_removal(
            validation_req.subject,
            validation_req.object,
            validation_req.action,
        )
    else:  # add
        validation = await casbin_service.validate_policy_addition(
            validation_req.subject,
            validation_req.object,
            validation_req.action,
        )

    return {
        "is_valid": validation.is_valid,
        "is_safe": validation.is_safe,
        "severity": validation.severity.value,
        "warnings": validation.warnings,
        "affected_users": validation.affected_users,
    }




@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/permissions/simulate")
async def simulate_permission(
    request: Request,
    request_data: schemas.PermissionSimulateRequest,
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Simulate a permission check without actually granting access.

    Test whether a subject (role/user) would have permission to perform an action
    on a resource, without modifying any policies.

    This is useful for:
    - Testing policy configurations before deploying
    - Debugging permission issues
    - Understanding complex policy interactions

    Example:
        POST /api/admin/policies/simulate
        {
            "subject": "role:manager",
            "object": "/api/leads",
            "action": "GET"
        }
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Simulate permission check
    # Note: enforcer.enforce() is SYNC, not async (despite using AsyncEnforcer)
    is_allowed = enforcer.enforce(
        request_data.subject,
        request_data.object,
        request_data.action
    )

    # Generate user-friendly message
    if is_allowed:
        message = f"✅ ALLOWED: {request_data.subject} CAN {request_data.action} on {request_data.object}"
    else:
        message = f"❌ DENIED: {request_data.subject} CANNOT {request_data.action} on {request_data.object}"

    return {
        "subject": request_data.subject,
        "object": request_data.object,
        "action": request_data.action,
        "is_allowed": is_allowed,
        "message": message,
    }




# ============================================================================
# ANALYTICS & INSIGHTS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/policies/statistics")
async def get_policy_statistics(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get statistics about policies.

    Returns counts for:
    - Total policies
    - Total roles
    - Total user-role assignments
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    stats = await casbin_service.get_policy_count()
    return stats




@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/policies/suggestions")
async def get_policy_suggestions(
    request: Request,
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get autocomplete suggestions for policy fields.

    Returns lists of unique subjects, objects, and actions from existing policies.
    Useful for autocomplete/combobox components in the UI.

    Example response:
        {
            "subjects": ["role:admin", "role:manager", "role:officer"],
            "objects": ["/api/leads", "/api/users", "/api/admin/*"],
            "actions": ["GET", "POST", "PUT", "DELETE", ".*"]
        }
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Get all policies
    all_policies = enforcer.get_policy()

    # Extract unique subjects, objects, actions
    subjects = sorted(list(set(policy[0] for policy in all_policies if len(policy) > 0)))
    objects = sorted(list(set(policy[1] for policy in all_policies if len(policy) > 1)))
    actions = sorted(list(set(policy[2] for policy in all_policies if len(policy) > 2)))

    return {
        "subjects": subjects,
        "objects": objects,
        "actions": actions,
    }


# ===============================================================
# USER MANAGEMENT ROUTES
# ===============================================================




@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/{role_name}/permissions/explain")
async def explain_role_permissions(
    request: Request,
    role_name: str,
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Explain where a role's permissions come from.

    Categorizes policies into:
    - Template policies (from system role templates)
    - Feature policies (from enabled features)
    - Manual policies (added individually)
    - Inherited policies (from role inheritance via grouping policies)

    This helps admins understand permission inheritance and sources.
    """
    from app.casbin_config.policy_templates import (
        FEATURE_MAP,
        ADMIN_TEMPLATE,
        MANAGER_TEMPLATE,
        OFFICER_TEMPLATE,
        BASIC_USER_TEMPLATE,  # ← (1) IMPORT BASIC_USER_TEMPLATE
    )

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # (2) ĐỊNH NGHĨA TEMPLATE_MAP ĐẦY ĐỦ
    TEMPLATE_MAP = {
        "role:admin": ADMIN_TEMPLATE,
        "role:manager": MANAGER_TEMPLATE,
        "role:officer": OFFICER_TEMPLATE,
        "role:user": BASIC_USER_TEMPLATE,  # ← THÊM DÒNG NÀY
    }

    # (3) LẤY CÁC VAI TRÒ MÀ ROLE NÀY KẾ THỪA
    # Ví dụ: cho "role:support", sẽ trả về ["role:user"]
    inherited_roles = await enforcer.get_roles_for_user(role_name)

    # (4) LẤY CÁC POLICY TRỰC TIẾP (DIRECT) CỦA ROLE NÀY
    # Note: get_policy() là SYNC method, trả về tất cả policies
    all_policies = enforcer.get_policy()
    direct_policies_tuples = [
        (p[0], p[1], p[2])
        for p in all_policies
        if p[0] == role_name
    ]

    policies_from_template = []
    policies_from_features = []
    policies_manual = []
    policies_inherited = []  # ← (5) KHỞI TẠO LIST MỚI

    template_policy_set = set()
    feature_policy_set = set()

    # (6) PHÂN LOẠI CÁC POLICY TRỰC TIẾP
    # 6a. Tìm quyền từ Template
    if role_name in TEMPLATE_MAP:
        template = TEMPLATE_MAP[role_name]
        template_policies = [
            (p["subject"].replace("{role}", role_name), p["object"], p["action"])
            for p in template["policies"]
        ]
        for p_tuple in template_policies:
            if p_tuple in direct_policies_tuples:
                policies_from_template.append({
                    "subject": p_tuple[0],
                    "object": p_tuple[1],
                    "action": p_tuple[2]
                })
                template_policy_set.add(p_tuple)

    # 6b. Tìm quyền từ Features
    for feature_id, feature_def in FEATURE_MAP.items():
        feature_policies = [
            (p["subject"].replace("{role}", role_name), p["object"], p["action"])
            for p in feature_def["policies"]
        ]
        if all(fp in direct_policies_tuples for fp in feature_policies):
            for fp in feature_policies:
                policies_from_features.append({
                    "subject": fp[0],
                    "object": fp[1],
                    "action": fp[2]
                })
                feature_policy_set.add(fp)

    # 6c. Tìm quyền Manual (Thủ công)
    direct_policies_set = set(direct_policies_tuples)
    for p_tuple in direct_policies_tuples:
        if p_tuple not in template_policy_set and p_tuple not in feature_policy_set:
            policies_manual.append({
                "subject": p_tuple[0],
                "object": p_tuple[1],
                "action": p_tuple[2]
            })

    # (7) TÌM QUYỀN KẾ THỪA (PHẦN QUAN TRỌNG NHẤT)
    for inherited_role_name in inherited_roles:
        # Lấy tất cả policy của role CHA (bao gồm cả kế thừa của NÓ)
        # Note: get_implicit_permissions_for_user là ASYNC method
        inherited_policies = await enforcer.get_implicit_permissions_for_user(inherited_role_name)

        for p_tuple in inherited_policies:
            # Chỉ thêm nếu nó chưa phải là quyền trực tiếp (tránh trùng lặp)
            if tuple(p_tuple) not in direct_policies_set:
                # Hiển thị rõ nguồn gốc kế thừa
                inherited_role_display = inherited_role_name.replace("role:", "")
                policies_inherited.append({
                    "subject": f"{role_name} (← {inherited_role_display})",
                    "object": p_tuple[1],
                    "action": p_tuple[2]
                })

    return {
        "role": role_name,
        "policies_from_template": policies_from_template,
        "policies_from_features": policies_from_features,
        "policies_manual": policies_manual,
        "policies_inherited": policies_inherited,  # ← (8) TRẢ VỀ DỮ LIỆU MỚI
    }


# =============================================================================
# SYSTEM CONFIGURATION - DEGREE LEVELS
# =============================================================================



@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/permissions/who-can-access")
async def who_can_access_resource(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    object: str = Query(..., description="Resource path (e.g., /api/leads)"),
    action: str = Query(..., description="HTTP method (e.g., GET, POST)"),
    current_admin: models.User = CasbinAuth,
):
    """
    ✅ PATCHED FOR DoS (v15):
    (Admin only) Reverse permission lookup: Find which roles can access a resource.

    SECURITY FIX:
    - Only returns ROLES (not individual users) - preventing DoS attacks
    - With 50k users, old implementation could crash server
    - New implementation: ~10ms for ~10 roles (5000x faster)

    This endpoint has been hardened against DoS attacks where malicious
    admins could spam requests to exhaust CPU by triggering 50,000+
    permission checks.

    Example:
        GET /api/admin/policies/who-can-access?object=/api/leads&action=GET

    Returns:
        List of roles that have permission to access the resource.
        Casbin automatically handles role inheritance.

    PERFORMANCE:
        - Checks ~10 roles instead of 50k users
        - ~10ms execution time (vs 5000ms+ in old implementation)
    """
    import time
    from app.services.casbin_service import CasbinPolicyService

    start_time = time.time()

    # Initialize Casbin service
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db=None, enforcer=enforcer)

    # Get allowed roles (simplified - no more include_users or max_results)
    allowed_subjects = await casbin_service.get_subjects_for_permission(
        obj=object,
        act=action
    )

    # Calculate execution time for monitoring
    execution_time_ms = int((time.time() - start_time) * 1000)

    # Generate warning if execution took too long (should be rare now)
    warning = None
    if execution_time_ms > 1000:
        warning = f"⚠️ Slow query ({execution_time_ms}ms). This is unusual for role-only lookup."

    # Log activity for audit trail
    await commit_and_log(db, await log_admin_activity(
        db=db,
        request=request,
        action="permission_lookup",
        resource_type="policy",
        actor_id=current_admin.id,
        resource_id=None,
        changes={
            "object": object,
            "action": action,
            "results_count": len(allowed_subjects),
            "execution_time_ms": execution_time_ms,
        },
    ))

    log.info(
        "Permission lookup completed",
        admin_id=current_admin.id,
        object=object,
        action=action,
        results=len(allowed_subjects),
        time_ms=execution_time_ms,
    )

    return {
        "object": object,
        "action": action,
        "allowed_subjects": allowed_subjects,
        "total_count": len(allowed_subjects),
        "execution_time_ms": execution_time_ms,
        "include_users": False,  # Always false now - we only check roles
        "warning": warning,
    }




# ============================================================================
# FEATURE FLAGS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/{role_name}/features")
async def get_role_features(
    request: Request,
    role_name: str,
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get feature-based permission status for a role.

    Returns a high-level view of which business features are enabled
    for a specific role, abstracting away low-level policy details.

    Example:
        GET /api/admin/roles/role:manager/features

    Returns:
        {
            "role": "role:manager",
            "features": [
                {"feature_id": "view_leads", "display_name": "Xem Leads", "enabled": true, ...},
                {"feature_id": "edit_leads", "display_name": "Sửa Leads", "enabled": false, ...},
                ...
            ]
        }
    """
    from app.casbin_config.policy_templates import FEATURE_MAP

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Get current policies for this role
    all_policies = enforcer.get_policy()
    role_policies = [
        (p[0], p[1], p[2])
        for p in all_policies
        if p[0] == role_name
    ]

    features = []

    # Check each feature
    for feature_id, feature_def in FEATURE_MAP.items():
        # Check if all policies for this feature exist for this role
        feature_policies = [
            (
                policy["subject"].replace("{role}", role_name),
                policy["object"],
                policy["action"]
            )
            for policy in feature_def["policies"]
        ]

        # Feature is enabled if all its policies exist
        enabled = all(policy in role_policies for policy in feature_policies)

        features.append({
            "feature_id": feature_id,
            "display_name": feature_def["display_name"],
            "enabled": enabled,
            "policy_count": len(feature_def["policies"]),
        })

    return {
        "role": role_name,
        "features": features,
    }




@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/{role_name}/features/toggle")
async def toggle_role_feature(
    request: Request,
    role_name: str,
    request_data: schemas.ToggleFeatureRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Enable or disable a feature for a role.

    This endpoint manages all policies associated with a feature as a group,
    making it easier to grant/revoke business-level permissions.

    Example:
        POST /api/admin/roles/role:manager/features/toggle
        {
            "feature_id": "view_leads",
            "enabled": true
        }

    This will add/remove all policies associated with the "view_leads" feature.
    """
    from app.casbin_config.policy_templates import FEATURE_MAP
    from app.services.casbin_service import CasbinPolicyService

    # Validate feature exists
    if request_data.feature_id not in FEATURE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown feature: {request_data.feature_id}"
        )

    feature_def = FEATURE_MAP[request_data.feature_id]
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db=db, enforcer=enforcer)

    # Convert feature policies to tuples with role substituted
    policies_tuples = [
        (
            policy["subject"].replace("{role}", role_name),
            policy["object"],
            policy["action"]
        )
        for policy in feature_def["policies"]
    ]

    # Add or remove policies based on enabled flag
    if request_data.enabled:
        # Enable feature: add all policies (track as feature-based)
        result = await casbin_service.add_policies_batch(
            policies_tuples,
            validate=True,
            template_id=f"_feature:{request_data.feature_id}",
            applied_by=current_admin.id
        )

        # Log activity
        await commit_and_log(db, await log_admin_activity(
            db=db,
            request=request,
            action="enable_feature",
            resource_type="casbin_policy",
            actor_id=current_admin.id,
            description=f"Enabled feature '{feature_def['display_name']}' for {role_name}",
            changes={
                "feature_id": request_data.feature_id,
                "role": role_name,
                "policies_added": result["added"],
            },
        ))
    else:
        # Disable feature: remove all policies
        result = await casbin_service.remove_policies_batch(
            policies_tuples,
            validate=True,
            force=False
        )

        # CỔNG TRUNG THỰC: tầng service nay đếm đúng, nhưng bề mặt HTTP mới là
        # thứ người vận hành nhìn. Bản cũ luôn trả 200 và luôn ghi audit
        # "Disabled feature" kể cả khi `removed=0` — đo được: đúng thành công
        # giả. Với A01 Broken Access Control, một 200 cho việc thu hồi KHÔNG
        # xảy ra là kiểu hỏng tệ nhất: người vận hành tin quyền đã bị gỡ.
        #
        # KHÔNG trừ `blocked`. Safety-check từ chối xoá là từ chối CÓ CHỦ Ý,
        # nhưng hệ quả với người dùng thì y hệt: policy VẪN CÒN, nên feature
        # VẪN CHƯA TẮT. Trừ `blocked` ra là quay lại đúng lỗi đang vá — báo
        # "Disabled feature" cho một việc không xảy ra.
        #
        # Và ĐO thay vì trừ: `con_song` là rule thật sự còn trong enforcer.
        # Phép trừ `len - removed` sai hai chiều — rule vốn đã không tồn tại bị
        # tính là "chưa xoá" (báo động giả), còn rule bị chặn hay ném lỗi thì
        # không phải lúc nào cũng vào được `removed`.
        con_song = result.get("con_song", [])
        if con_song or not result.get("an_toan", False):
            raise ConflictError(
                f"Không tắt được feature '{feature_def['display_name']}' cho "
                f"{role_name}: {len(con_song)}/{len(policies_tuples)} policy "
                f"chưa bị xoá (trong đó {result.get('blocked', 0)} bị "
                f"safety-check giữ lại"
                + (
                    f"; {len(result.get('deny_chua_cham', []))} rule deny KHÔNG "
                    f"bị chạm tới vì non-deny xoá hụt"
                    if not result.get("an_toan", False)
                    else ""
                )
                + f"), quyền cũ VẪN CÒN hiệu lực. "
                f"Chi tiết: {result.get('warnings') or result.get('errors')}"
            )

        # Log activity — chỉ tới đây khi MỌI policy dự kiến đã thật sự bị xoá.
        await commit_and_log(db, await log_admin_activity(
            db=db,
            request=request,
            action="disable_feature",
            resource_type="casbin_policy",
            actor_id=current_admin.id,
            description=f"Disabled feature '{feature_def['display_name']}' for {role_name}",
            changes={
                "feature_id": request_data.feature_id,
                "role": role_name,
                "policies_removed": result.get("removed", 0),
            },
        ))

    return result


# =============================================================================
# TEMPLATE DRIFT DETECTION & SYNC (Phase 4 Fix)
# Reference: AUTHORIZATION_DECISIONS.md Decision 14
# =============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/drift/all")
async def get_all_drift_status(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get drift status for all system roles.

    Drift detection compares template definitions (policy_templates.py)
    with actual policies in database (casbin_rule table).

    Returns:
        Dictionary with drift status for each role and overall health.
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db=db, enforcer=enforcer)

    return await casbin_service.detect_all_drift()


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/{role_name}/drift")
async def get_role_drift_status(
    request: Request,
    role_name: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Get drift status for a specific role.

    Compares template definition with actual DB policies.
    """
    from app.services.casbin_service import CasbinPolicyService
    from app.casbin_config.policy_templates import SYSTEM_ROLES

    # Find template_id for this role
    template_id = None
    for system_role in SYSTEM_ROLES:
        if system_role["name"] == role_name:
            template_id = system_role.get("template_id")
            break

    if not template_id:
        raise HTTPException(
            status_code=400,
            detail=f"No template defined for role: {role_name}"
        )

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db=db, enforcer=enforcer)

    return await casbin_service.detect_template_drift(role_name, template_id)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("/{role_name}/refresh-from-template")
async def refresh_role_from_template_endpoint(
    request: Request,
    role_name: str,
    force: bool = False,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Force reset role to match template exactly.

    ⚠️ WARNING: Destructive operation! Set force=True to confirm.
    """
    from app.services.casbin_service import CasbinPolicyService
    from app.casbin_config.policy_templates import SYSTEM_ROLES

    template_id = None
    for system_role in SYSTEM_ROLES:
        if system_role["name"] == role_name:
            template_id = system_role.get("template_id")
            break

    if not template_id:
        raise HTTPException(
            status_code=400,
            detail=f"No template defined for role: {role_name}"
        )

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db=db, enforcer=enforcer)

    result = await casbin_service.refresh_role_from_template(
        role_name, template_id, force=force, applied_by=current_admin.id
    )

    if result.get("success"):
        await commit_and_log(db, await log_admin_activity(
            db=db,
            request=request,
            action="refresh_role_from_template",
            resource_type="casbin_policy",
            actor_id=current_admin.id,
            description=f"Refreshed {role_name} from template {template_id}",
            changes={
                "role": role_name,
                "template_id": template_id,
                "policies_removed": result.get("policies_removed"),
                "policies_added": result.get("policies_added"),
            },
        ))

    return result


@limiter.limit(RateLimits.ADMIN_BULK)  # 10/hour - Dangerous operation
@router.post("/sync-all-from-templates")
async def sync_all_roles_from_templates_endpoint(
    request: Request,
    dry_run: bool = True,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Sync all system roles to match their templates.

    ⚠️ WARNING: With dry_run=False, this is VERY destructive!
    """
    from app.services.casbin_service import CasbinPolicyService

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db=db, enforcer=enforcer)

    result = await casbin_service.sync_all_roles_from_templates(dry_run=dry_run)

    if not dry_run:
        await commit_and_log(db, await log_admin_activity(
            db=db,
            request=request,
            action="sync_all_roles_from_templates",
            resource_type="casbin_policy",
            actor_id=current_admin.id,
            description="Synced all system roles from templates",
            changes={"results": result},
        ))

    return result



