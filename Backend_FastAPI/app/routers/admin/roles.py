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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core import deps
from app.database import get_db
from app.schemas.permissions import (
    PolicyCreate,
    RoleAssignment,
    GroupingPolicyCreate,
)
from app.services import activity_service, role_service
from app.utils.exceptions import (
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(prefix="/roles", tags=["Admin - Roles & Permissions"])

# Permission dependency
PermissionDep = Depends(deps.check_permission)


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
    """
    Helper function to log admin activities with IP/UA extracted from request.

    This duplicates the helper from admin.py for router independence.
    Protocol-independent service (activity_service) handles actual logging.
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
# POLICY CRUD OPERATIONS
# ============================================================================


@router.get("/policies", response_model=List[List[str]])
async def get_all_policies(
    request: Request, current_admin: models.User = PermissionDep
):
    """(Admin only) Lấy tất cả các chính sách (policies) hiện có."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    # SỬA: Bỏ await vì get_policy() không phải là async
    policies = enforcer.get_policy()
    return policies




@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def add_new_policy(
    policy_in: PolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thêm một chính sách (quyền) mới với validation và logging."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not added:
        raise DuplicateResourceError("Policy already exists.")

    # Log activity
    await log_admin_activity(
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
    )

    return {"detail": "Policy added successfully."}




@router.delete("/policies", status_code=status.HTTP_200_OK)
async def delete_policy(
    policy_in: PolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một chính sách (quyền) cụ thể với safety checks."""
    from app.services.casbin_service import CasbinPolicyService

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    # SAFETY CHECK: Validate removal operation
    validation = await casbin_service.validate_policy_removal(
        policy_in.subject,
        policy_in.object,
        policy_in.action,
    )

    if not validation.is_safe:
        raise PermissionDeniedError(
            detail=f"Cannot remove this policy for safety reasons: {'; '.join(validation.warnings)}"
        )

    # Remove policy
    removed = await enforcer.remove_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not removed:
        raise ResourceNotFoundError("Policy not found or could not be removed.")

    # Log activity
    await log_admin_activity(
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
    )

    return {"detail": "Policy removed successfully."}




# ============================================================================
# ROLE ASSIGNMENT OPERATIONS (Uses role_service from PHASE 1!)
# ============================================================================


@router.post("/assign", status_code=status.HTTP_201_CREATED)
async def assign_role_to_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Gán một vai trò cho người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_grouping_policy(
        f"user:{assignment.user_id}", assignment.role
    )
    if not added:
        raise DuplicateResourceError("User already has this role.")

    # Explicitly save to ensure persistence
    await enforcer.save_policy()

    return {"detail": "Role assigned."}




@router.delete("/revoke")
async def remove_role_from_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa (thu hồi) vai trò của người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    removed = await enforcer.remove_grouping_policy(
        f"user:{assignment.user_id}", assignment.role
    )
    if not removed:
        raise ResourceNotFoundError(
            "Role assignment not found or could not be removed."
        )

    # Explicitly save to ensure persistence
    await enforcer.save_policy()

    return {"detail": "Role removed from user."}




@router.get("/users/{user_id}/roles")
async def get_user_roles(
    user_id: int,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy tất cả các roles (grouping policies) của một user."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Lấy tất cả roles của user
    user_subject = f"user:{user_id}"
    roles = await enforcer.get_roles_for_user(user_subject)

    return roles




@router.get("/{role_name}/users")
async def get_role_users(
    role_name: str,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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

    # Fetch user details from database
    if not user_ids:
        return {"role": role_name, "user_count": 0, "users": []}

    result = await db.execute(
        select(models.User).where(models.User.id.in_(user_ids))
    )
    users = result.scalars().all()

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




@router.delete("/{role_name}/users")
async def remove_role_from_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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
    return await role_service.remove_role_from_users(
        db=db,
        enforcer=enforcer,
        user_ids=user_ids,
        role_to_remove=role_to_remove,
    )




# ============================================================================
# GROUPING POLICY OPERATIONS
# ============================================================================


@router.post("/grouping-policies", status_code=status.HTTP_201_CREATED)
async def add_grouping_policy(
    grouping: GroupingPolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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

    # Add the grouping policy (g rule)
    added = await enforcer.add_grouping_policy(grouping.subject, grouping.parent_role)

    if not added:
        raise DuplicateResourceError(
            f"Grouping policy already exists: {grouping.subject} → {grouping.parent_role}"
        )

    # Save to database
    await enforcer.save_policy()

    # Log activity
    await log_admin_activity(
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
    )

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




@router.delete("/grouping-policies")
async def delete_grouping_policy(
    grouping: GroupingPolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Remove a grouping policy.

    Removes a grouping policy for either:
    1. Role-to-role inheritance
    2. User-to-role assignment
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # Remove the grouping policy
    removed = await enforcer.remove_grouping_policy(grouping.subject, grouping.parent_role)

    if not removed:
        raise ResourceNotFoundError(
            f"Grouping policy not found: {grouping.subject} → {grouping.parent_role}"
        )

    # Save to database
    await enforcer.save_policy()

    # Log activity
    await log_admin_activity(
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
    )

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


@router.get("")
async def get_all_roles_with_info(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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




@router.delete("/{role_name}")
async def delete_role_atomic(
    role_name: str,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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
    from app.services.casbin_service import CasbinPolicyService

    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    # STEP 1: Validate - System roles cannot be deleted
    SYSTEM_ROLES = {"role:admin", "role:manager", "role:officer", "role:user"}
    if role_name in SYSTEM_ROLES:
        raise BadRequest(f"Cannot delete system role: {role_name}")

    # STEP 2: Check if role exists (has any policies)
    all_policies = enforcer.get_policy()
    role_has_policies = any(p[0] == role_name for p in all_policies)
    if not role_has_policies:
        raise ResourceNotFoundError(f"Role not found: {role_name}")

    # BEGIN ATOMIC TRANSACTION
    try:
        # STEP 3a: Find all users with this role in DB
        result = await db.execute(
            select(models.User).where(models.User.role == role_name.replace("role:", ""))
        )
        users_from_db = result.scalars().all()

        # STEP 3b: Find all users with grouping policy for this role
        all_grouping = enforcer.get_grouping_policy()
        user_ids_from_casbin = []
        for group in all_grouping:
            # group format: ["user:123", "role:support"]
            if len(group) >= 2 and group[1] == role_name and group[0].startswith("user:"):
                try:
                    user_id = int(group[0].split(":")[1])
                    user_ids_from_casbin.append(user_id)
                except (ValueError, IndexError):
                    continue

        # Merge: Get all unique user IDs
        all_user_ids = set([u.id for u in users_from_db] + user_ids_from_casbin)

        # STEP 4: Update users in DB to role:user
        reassigned_count = 0
        for user_id in all_user_ids:
            result = await db.execute(
                select(models.User).where(models.User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                # Only update if they had this role
                if user.role == role_name.replace("role:", ""):
                    user.role = "user"
                    db.add(user)
                    reassigned_count += 1

        # STEP 5: Remove grouping policies (user → role)
        removed_g_user_count = 0
        for user_id in all_user_ids:
            user_subject = f"user:{user_id}"
            removed = await enforcer.remove_grouping_policy(user_subject, role_name)
            if removed:
                removed_g_user_count += 1

            # STEP 6: Add grouping policy (user → role:user) if needed
            user_roles = await enforcer.get_roles_for_user(user_subject)
            if not user_roles or len(user_roles) == 0:
                await enforcer.add_grouping_policy(user_subject, "role:user")

        # STEP 7: Remove all permission policies (p rules) for this role
        policies_to_remove = [
            (p[0], p[1], p[2])
            for p in all_policies
            if p[0] == role_name
        ]
        removed_p_count = 0
        for p in policies_to_remove:
            removed = await enforcer.remove_policy(p[0], p[1], p[2])
            if removed:
                removed_p_count += 1

        # STEP 8: Remove role inheritance grouping policies (g, role:X, role:user)
        removed_g_inherit_count = 0
        for group in all_grouping:
            # Check if this is a role inheriting from another role
            if len(group) >= 2 and group[0] == role_name:
                removed = await enforcer.remove_grouping_policy(group[0], group[1])
                if removed:
                    removed_g_inherit_count += 1

        # STEP 9: Save Casbin policies
        await enforcer.save_policy()

        # STEP 10: Commit DB transaction
        await db.commit()

        # STEP 11: Log activity
        await log_admin_activity(
            db=db,
            request=request,
            action="delete_role_atomic",
            resource_type="role",
            actor_id=current_admin.id,
            resource_id=None,
            changes={
                "role_name": role_name,
                "users_reassigned": reassigned_count,
                "permission_policies_removed": removed_p_count,
                "user_grouping_policies_removed": removed_g_user_count,
                "inheritance_grouping_policies_removed": removed_g_inherit_count,
                "total_affected_users": len(all_user_ids),
            },
        )

        log.info(
            "Role deleted atomically",
            admin_id=current_admin.id,
            role_name=role_name,
            users_reassigned=reassigned_count,
            policies_removed=removed_p_count,
        )

        return {
            "detail": f"Role {role_name} deleted successfully",
            "role_name": role_name,
            "users_reassigned": reassigned_count,
            "permission_policies_removed": removed_p_count,
            "user_grouping_policies_removed": removed_g_user_count,
            "inheritance_grouping_policies_removed": removed_g_inherit_count,
            "total_affected_users": len(all_user_ids),
        }

    except Exception as e:
        # Rollback DB transaction
        await db.rollback()
        log.error(
            "Failed to delete role atomically",
            role_name=role_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete role: {str(e)}",
        )




# ============================================================================
# POLICY TEMPLATES
# ============================================================================


@router.get("/templates")
async def get_policy_templates(
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get all available policy templates.

    Templates provide pre-configured sets of policies for common roles.
    Admins can apply templates to quickly set up permissions.
    """
    from app.core.casbin_config.policy_templates import POLICY_TEMPLATES

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




@router.post("/templates/apply")
async def apply_template_to_role(
    request: Request,
    template_req: schemas.TemplateApplicationRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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
    )

    # Log activity
    if result.get("added", 0) > 0:
        await log_admin_activity(
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
        )

    return result




# ============================================================================
# BATCH OPERATIONS
# ============================================================================


@router.post("/policies/batch")
async def add_policies_batch(
    request: Request,
    batch_req: schemas.PolicyBatchRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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

    # Actually add policies
    result = await casbin_service.add_policies_batch(
        policies_tuples,
        validate=batch_req.run_validation
    )

    # Log activity for each added policy
    if result["added"] > 0:
        await log_admin_activity(
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
        )

    return result




# ============================================================================
# VALIDATION & SIMULATION
# ============================================================================


@router.post("/policies/validate")
async def validate_policy_operation(
    request: Request,
    validation_req: schemas.PolicyValidationRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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




@router.post("/permissions/simulate")
async def simulate_permission(
    request: Request,
    request_data: schemas.PermissionSimulateRequest,
    current_admin: models.User = PermissionDep,
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


@router.get("/policies/statistics")
async def get_policy_statistics(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
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




@router.get("/policies/suggestions")
async def get_policy_suggestions(
    request: Request,
    current_admin: models.User = PermissionDep,
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




@router.get("/{role_name}/permissions/explain")
async def explain_role_permissions(
    request: Request,
    role_name: str,
    current_admin: models.User = PermissionDep,
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
    from app.core.casbin_config.policy_templates import (
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



@router.post("/permissions/who-can-access")
async def who_can_access_resource(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    object: str = Query(..., description="Resource path (e.g., /api/leads)"),
    action: str = Query(..., description="HTTP method (e.g., GET, POST)"),
    current_admin: models.User = PermissionDep,
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
    await log_admin_activity(
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
    )

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


@router.get("/{role_name}/features")
async def get_role_features(
    request: Request,
    role_name: str,
    current_admin: models.User = PermissionDep,
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
    from app.core.casbin_config.policy_templates import FEATURE_MAP

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




@router.post("/{role_name}/features/{feature_name}/toggle")
async def toggle_role_feature(
    request: Request,
    role_name: str,
    request_data: schemas.ToggleFeatureRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Enable or disable a feature for a role.

    This endpoint manages all policies associated with a feature as a group,
    making it easier to grant/revoke business-level permissions.

    Example:
        POST /api/admin/roles/role:manager/features
        {
            "feature_id": "view_leads",
            "enabled": true
        }

    This will add/remove all policies associated with the "view_leads" feature.
    """
    from app.core.casbin_config.policy_templates import FEATURE_MAP
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
        # Enable feature: add all policies
        result = await casbin_service.add_policies_batch(policies_tuples, validate=True)

        # Log activity
        await activity_service.log_activity(
            db=db,
            actor_id=current_admin.id,
            action="enable_feature",
            description=f"Enabled feature '{feature_def['display_name']}' for {role_name}",
            resource_type="casbin_policy",
            resource_id=None,
            changes={
                "feature_id": request_data.feature_id,
                "role": role_name,
                "policies_added": result["added"],
            }
        )
    else:
        # Disable feature: remove all policies
        result = await casbin_service.remove_policies_batch(
            policies_tuples,
            validate=True,
            force=False
        )

        # Log activity
        await activity_service.log_activity(
            db=db,
            actor_id=current_admin.id,
            action="disable_feature",
            description=f"Disabled feature '{feature_def['display_name']}' for {role_name}",
            resource_type="casbin_policy",
            resource_id=None,
            changes={
                "feature_id": request_data.feature_id,
                "role": role_name,
                "policies_removed": result.get("removed", 0),
            }
        )

    return result




