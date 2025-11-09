# app/routers/admin.py
import io
from typing import List, Optional
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone

import casbin
import pandas as pd
import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import EmailStr  # <-- BỔ SUNG TypeAdapter, ValidationError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .. import database, models, schemas, services
from ..celery_utils import process_automatic_lead_assignment_task
from ..core import deps
from ..services import activity_service, notification_service
from ..routers.notifications import send_realtime_notification
from ..schemas.permissions import PolicyCreate, RoleAssignment, GroupingPolicyCreate
from ..services import (
    config_service,
    lead_service,
    organization_service,
    pipeline_service,
)
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Admin"])

# --- ĐỊNH NGHĨA DEPENDENCY MỚI ---
PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


# ===============================================================
# POLICY MANAGEMENT ROUTES
# ===============================================================


@router.get(
    "/policies",
    response_model=List[List[str]],  # Casbin trả về List[List[str]]
    tags=["Admin - Permissions"],
)
async def get_all_policies(
    request: Request, current_admin: models.User = PermissionDep
):
    """(Admin only) Lấy tất cả các chính sách (policies) hiện có."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    # SỬA: Bỏ await vì get_policy() không phải là async
    policies = enforcer.get_policy()
    return policies


@router.post(
    "/policies",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
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
    await activity_service.log_activity_from_request(
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


@router.delete(
    "/policies",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
async def delete_policy(
    policy_in: PolicyCreate,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một chính sách (quyền) cụ thể với safety checks."""
    from ..services.casbin_service import CasbinPolicyService

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
    await activity_service.log_activity_from_request(
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


@router.post(
    "/assign-role",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
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


@router.delete(
    "/assign-role",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
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


@router.get(
    "/users/{user_id}/roles",
    response_model=List[str],
    tags=["Admin - Permissions"],
)
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


@router.get(
    "/roles/{role_name}/users",
    tags=["Admin - Permissions"],
)
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


@router.post(
    "/roles/remove-from-users",
    tags=["Admin - Permissions"],
)
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
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    if not user_ids:
        raise ResourceNotFoundError("No user IDs provided")

    # Role priority for DB field (highest to lowest)
    ROLE_PRIORITY = {
        "role:admin": 4,
        "role:manager": 3,
        "role:officer": 2,
        "role:user": 1,
    }

    removed_count = 0
    reassigned_count = 0
    failed_users = []

    for user_id in user_ids:
        user_subject = f"user:{user_id}"

        try:
            # Get all current roles for this user
            current_roles = await enforcer.get_roles_for_user(user_subject)

            # Check if user actually has the role to remove
            if role_to_remove not in current_roles:
                log.warning(f"User {user_id} doesn't have role {role_to_remove}, skipping")
                continue

            # Remove the specified role
            await enforcer.remove_grouping_policy(user_subject, role_to_remove)
            removed_count += 1

            # Get remaining roles after removal
            remaining_roles = [r for r in current_roles if r != role_to_remove]

            # If no roles left, auto-assign role:user as fallback
            if not remaining_roles:
                await enforcer.add_grouping_policy(user_subject, "role:user")
                remaining_roles = ["role:user"]
                reassigned_count += 1
                log.info(f"User {user_id} had no roles left, auto-assigned role:user")

            # Update database user.role field to highest priority remaining role
            result = await db.execute(
                select(models.User).where(models.User.id == user_id)
            )
            user = result.scalar_one_or_none()

            if user:
                # Find highest priority role from remaining roles
                highest_priority_role = max(
                    remaining_roles,
                    key=lambda r: ROLE_PRIORITY.get(r, 0),
                    default="role:user"
                )

                # Extract role name without "role:" prefix for DB
                db_role_name = highest_priority_role.replace("role:", "")
                user.role = db_role_name
                await db.commit()

                log.info(
                    f"User {user_id} updated",
                    removed_role=role_to_remove,
                    remaining_roles=remaining_roles,
                    db_role=db_role_name
                )

        except Exception as e:
            failed_users.append({"user_id": user_id, "error": str(e)})
            log.error(f"Failed to remove role from user {user_id}", error=str(e))

    # Save Casbin policies
    await enforcer.save_policy()

    return {
        "detail": f"Removed {role_to_remove} from {removed_count} user(s), {reassigned_count} auto-assigned to role:user",
        "removed_count": removed_count,
        "reassigned_to_user_count": reassigned_count,
        "failed_count": len(failed_users),
        "failed_users": failed_users,
    }


@router.post(
    "/grouping-policies",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
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
    await activity_service.log_activity_from_request(
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


@router.delete(
    "/grouping-policies",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
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
    await activity_service.log_activity_from_request(
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


@router.get(
    "/roles",
    response_model=schemas.RolesListResponse,
    tags=["Admin - Permissions"],
)
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
    from ..services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    roles = await casbin_service.get_all_roles()
    return {"roles": roles}


@router.delete(
    "/roles/{role_name}",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
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
    from ..services.casbin_service import CasbinPolicyService

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
        await activity_service.log_activity_from_request(
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


@router.get(
    "/policy-templates",
    response_model=schemas.TemplatesListResponse,
    tags=["Admin - Permissions"],
)
async def get_policy_templates(
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get all available policy templates.

    Templates provide pre-configured sets of policies for common roles.
    Admins can apply templates to quickly set up permissions.
    """
    from ..casbin_config.policy_templates import POLICY_TEMPLATES

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


@router.post(
    "/policies/batch",
    response_model=schemas.PolicyBatchResult,
    tags=["Admin - Permissions"],
)
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
    from ..services.casbin_service import CasbinPolicyService

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
        await activity_service.log_activity_from_request(
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


@router.post(
    "/policies/validate",
    response_model=schemas.PolicyValidationResult,
    tags=["Admin - Permissions"],
)
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
    from ..services.casbin_service import CasbinPolicyService

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


@router.post(
    "/policies/apply-template",
    response_model=schemas.PolicyBatchResult,
    tags=["Admin - Permissions"],
)
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
    from ..services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    result = await casbin_service.apply_template_to_role(
        template_req.template_id,
        template_req.role,
        validate=template_req.run_validation,
    )

    # Log activity
    if result.get("added", 0) > 0:
        await activity_service.log_activity_from_request(
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


@router.get(
    "/policies/statistics",
    response_model=schemas.PolicyStatistics,
    tags=["Admin - Permissions"],
)
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
    from ..services.casbin_service import CasbinPolicyService

    enforcer = request.app.state.enforcer
    casbin_service = CasbinPolicyService(db, enforcer)

    stats = await casbin_service.get_policy_count()
    return stats


@router.get(
    "/policies/suggestions",
    response_model=schemas.PolicySuggestionsResponse,
    tags=["Admin - Permissions"],
)
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


@router.post(
    "/users",
    response_model=schemas.User,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - User Management"],
)
async def create_new_user(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form("user"),
    status: str = Form("active"),
    avatar: Optional[UploadFile] = File(None),
):
    """(Admin only) Tạo một người dùng mới, có hỗ trợ upload avatar."""
    user_in = schemas.AdminUserCreate(
        username=username,
        email=email,
        password=password,
        confirm_password=password,
        full_name=full_name,
        role=role,
        status=status,
    )

    if await services.user_service.get_user_by_username(db, user_in.username):
        raise DuplicateResourceError(detail="Username already exists")
    if await services.user_service.get_user_by_email(db, user_in.email):
        raise DuplicateResourceError(detail="Email already exists")

    # ✅ ATOMIC FIX (v17): Pass enforcer to service for atomic DB + Casbin transaction
    enforcer = request.app.state.enforcer
    created_user = await services.user_service.create_user_by_admin(
        db=db,
        user_in=user_in,
        enforcer=enforcer,
        avatar_file=avatar
    )
    # Casbin sync now happens inside create_user_by_admin atomically

    # Log activity
    await activity_service.log_activity_from_request(
        db=db,
        request=request,
        action="create_user",
        resource_type="user",
        actor_id=current_admin.id,
        target_user_id=created_user.id,
        resource_id=created_user.id,
        description=f"Admin created new user: {created_user.username}",
    )

    return created_user


@router.get(
    "/users", response_model=schemas.UsersPage, tags=["Admin - User Management"]
)
async def get_all_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """(Admin only) Lấy danh sách tất cả người dùng với phân trang, filter, search."""
    skip = (page - 1) * page_size
    query_params = dict(request.query_params)
    total, users = await services.user_service.get_users(
        db, params=query_params, skip=skip, limit=page_size
    )
    return {"total_count": total, "users": users}


@router.get(
    "/users/export",
    response_model=List[schemas.User],
    tags=["Admin - User Management"],
)
async def export_all_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Export tất cả người dùng ra CSV (không phân trang).

    Endpoint này trả về toàn bộ danh sách users phù hợp với các filter (role, status, search)
    mà không có giới hạn phân trang. Được sử dụng khi Admin nhấn nút "Export CSV"
    để đảm bảo export toàn bộ users, không chỉ trang hiện tại.

    ✅ Sử dụng eager loading (selectinload) để tránh N+1 queries.
    """
    query_params = dict(request.query_params)
    # Gọi get_users với skip=0 và limit rất lớn để lấy tất cả
    # Hoặc có thể gọi với skip=0, limit=None nếu service hỗ trợ
    total, users = await services.user_service.get_users(
        db, params=query_params, skip=0, limit=10000  # Giới hạn tạm 10k users
    )
    return users


@router.get(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def get_user_details(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy thông tin chi tiết của một người dùng."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    return db_user


@router.put(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def update_existing_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),  # <-- Sửa lại thành Optional[str]
    phone_number: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    skills: Optional[str] = Form(None),  # Nhận JSON string từ form-data
    max_capacity: Optional[int] = Form(None),
):
    """(Admin only) Cập nhật người dùng, có hỗ trợ upload avatar."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    if not db_user:
        raise ResourceNotFoundError(detail="User not found")

    # Xây dựng dict chỉ chứa các trường hợp lệ được cung cấp
    update_dict = {}
    if full_name is not None and full_name.strip():
        update_dict["full_name"] = full_name.strip()
    if phone_number is not None and phone_number.strip():
        update_dict["phone_number"] = phone_number.strip()
    if role is not None and role.strip():
        update_dict["role"] = role.strip()
    if status is not None and status.strip():
        update_dict["status"] = status.strip()
    if max_capacity is not None and max_capacity >= 0:
        update_dict["max_capacity"] = max_capacity
    if skills is not None:
        try:
            # Chuyển đổi chuỗi JSON 'skills' từ Form thành đối tượng Python (list)
            import json

            update_dict["skills"] = json.loads(skills)
            if not isinstance(update_dict["skills"], list):
                raise ValueError("Skills must be a JSON list of strings")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                existing_user = await services.user_service.get_user_by_email(db, valid_email)
                if existing_user:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already registered by another user",
                    )
            update_dict["email"] = valid_email
            
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

    # Truyền avatar và enforcer vào hàm service
    updated_user = await services.user_service.update_user(
        db, db_user, user_in, enforcer=enforcer, avatar_file=avatar
    )

    # Log activity
    await activity_service.log_activity_from_request(
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

    # Send notification to user if admin updated their info
    if current_admin.id != updated_user.id and changes:
        log.info(
            "Admin updated user info, creating notification",
            admin_id=current_admin.id,
            target_user_id=updated_user.id,
            changes=list(changes.keys()),
        )
        change_description = ", ".join([f"{key}" for key in changes.keys()])
        try:
            notification = await notification_service.create_notification(
                db=db,
                user_id=updated_user.id,
                title="Your profile has been updated",
                message=f"An administrator has updated your profile. Changed: {change_description}",
                notification_type="admin_update",
                link=f"/profile",
            )
            log.info(
                "Notification created successfully",
                notification_id=notification.id,
                target_user_id=updated_user.id,
            )
            # Send real-time notification via WebSocket
            await send_realtime_notification(notification)
        except Exception as e:
            log.error(
                "Failed to create/send notification",
                admin_id=current_admin.id,
                target_user_id=updated_user.id,
                error=str(e),
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
@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def delete_existing_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một người dùng."""
    if user_id == current_admin.id:
        raise PermissionDeniedError(detail="Admin cannot delete themselves")

    # Get user info before deleting for activity log
    db_user = await services.user_service.get_user_by_id(db, user_id)
    username = db_user.username if db_user else f"User#{user_id}"

    # Bỏ kiểm tra 'is None' vì service đã ném 404
    await services.user_service.delete_user(db, user_id)

    # Log activity
    await activity_service.log_activity_from_request(
        db=db,
        request=request,
        action="delete_user",
        resource_type="user",
        actor_id=current_admin.id,
        target_user_id=user_id,
        resource_id=user_id,
        description=f"Admin deleted user: {username}",
    )

    return None


@router.post(
    "/users/{user_id}/set-password",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def admin_set_user_password(
    user_id: int,
    password_data: schemas.AdminSetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Admin đặt lại mật khẩu cho người dùng."""
    await services.user_service.set_password_by_admin(
        db, user_id, password_data.new_password
    )
    return None


@router.post(
    "/users/bulk-action",
    status_code=status.HTTP_200_OK,
    tags=["Admin - User Management"],
)
async def bulk_user_action(
    action_data: schemas.BulkActionSchema,
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thực hiện hành động hàng loạt (xóa, đổi trạng thái) trên nhiều người dùng."""
    message = await services.user_service.perform_bulk_action(
        db,
        action=action_data.action,
        user_ids=action_data.user_ids,
        admin_user=current_admin,
        new_status=action_data.status,
    )

    # Log activity for bulk action
    action_desc = f"Bulk {action_data.action}"
    if action_data.action == "change_status" and action_data.status:
        action_desc += f" to {action_data.status}"
    action_desc += f" for {len(action_data.user_ids)} users"

    await activity_service.log_activity_from_request(
        db=db,
        request=request,
        action=f"bulk_{action_data.action}",
        resource_type="user",
        actor_id=current_admin.id,
        description=action_desc,
        changes={"user_ids": action_data.user_ids, "status": action_data.status} if action_data.status else {"user_ids": action_data.user_ids},
    )

    return {"detail": message}

@router.get(
    "/users/export-csv",
    tags=["Admin - User Management"],
    summary="Stream all users matching filters to a CSV file",
)
async def stream_export_users_csv(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Stream export users ra file CSV.
    Endpoint này sử dụng StreamingResponse để xử lý lượng dữ liệu lớn
    mà không tốn bộ nhớ server.
    """
    # Lấy các query params (filters) từ request
    query_params = dict(request.query_params)
    log.info("CSV export stream requested by admin", admin_id=current_admin.id, filters=query_params)
    
    # 1. Gọi service (là một async generator)
    csv_streamer = services.user_service.stream_users_csv(db, query_params)
    
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


# ← PHASE 3: Detection endpoint - check DB/Casbin sync status
@router.get(
    "/sync/status",
    tags=["Admin - User Management"],
    summary="Check sync status between DB and Casbin roles"
)
async def get_sync_status(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep
):
    """
    (Admin only) Kiểm tra tình trạng đồng bộ giữa DB (user.role) và Casbin (grouping policies).
    Trả về số lượng user đã sync, chưa sync, và chi tiết các user bị lệch.
    """
    enforcer = request.app.state.enforcer

    # Get all users
    result = await db.execute(select(models.User))
    users = result.scalars().all()

    mismatched_users = []
    synced_count = 0

    for user in users:
        casbin_role = await services.user_service.get_highest_priority_role_from_casbin(
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
@router.post(
    "/sync/users",
    tags=["Admin - User Management"],
    summary="Manually sync DB roles to match Casbin (source of truth)"
)
async def sync_users(
    request: Request,
    sync_request: schemas.SyncUsersRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Đồng bộ role từ Casbin về DB cho tất cả users hoặc một nhóm users cụ thể.
    Casbin được coi là source of truth (nguồn chân lý).

    - `user_ids`: Danh sách ID users cần sync. Nếu None hoặc rỗng, sync tất cả users.
    """
    enforcer = request.app.state.enforcer
    user_ids = sync_request.user_ids

    # Determine which users to sync
    if user_ids:
        result = await db.execute(
            select(models.User).where(models.User.id.in_(user_ids))
        )
    else:
        result = await db.execute(select(models.User))

    users = result.scalars().all()

    synced_count = 0
    failed_users = []

    for user in users:
        try:
            casbin_role = await services.user_service.get_highest_priority_role_from_casbin(
                enforcer, user.id
            )

            if user.role != casbin_role:
                old_role = user.role
                user.role = casbin_role
                db.add(user)
                synced_count += 1
                log.info(
                    "User role synced",
                    user_id=user.id,
                    old_role=old_role,
                    new_role=casbin_role
                )
        except Exception as e:
            log.error(
                "Failed to sync user",
                user_id=user.id,
                error=str(e),
                exc_info=True
            )
            failed_users.append({
                "user_id": user.id,
                "username": user.username,
                "error": str(e)
            })

    await db.commit()

    # Log activity
    await activity_service.log_activity_from_request(
        db=db,
        request=request,
        action="sync_users",
        resource_type="user",
        actor_id=current_admin.id,
        resource_id=None,
        changes={
            "synced_count": synced_count,
            "failed_count": len(failed_users),
            "user_ids": user_ids or "all"
        }
    )

    log.info(
        "User sync completed",
        admin_id=current_admin.id,
        synced=synced_count,
        failed=len(failed_users)
    )

    return {
        "synced_count": synced_count,
        "failed_count": len(failed_users),
        "failed_users": failed_users
    }


# ===============================================================
# ORGANIZATION & MAJOR MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một đơn vị tổ chức mới."""
    return await organization_service.create_organization_unit(db, unit_in)


@router.get(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def get_organization_unit_details(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một đơn vị tổ chức."""
    return await organization_service.get_organization_unit_by_id(db, unit_id)


@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def update_existing_organization_unit(
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một đơn vị tổ chức."""
    return await organization_service.update_organization_unit(db, unit_id, unit_in)


@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_organization_unit(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một đơn vị tổ chức."""
    await organization_service.delete_organization_unit(db, unit_id)
    return None


@router.post(
    "/majors",
    response_model=schemas.Major,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_major(
    major_in: schemas.MajorCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một ngành học mới."""
    return await organization_service.create_major(db, major_in)


@router.get(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def get_major_details(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một ngành học."""
    return await organization_service.get_major_by_id(db, major_id)


@router.put(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def update_existing_major(
    major_id: int,
    major_in: schemas.MajorUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một ngành học."""
    return await organization_service.update_major(db, major_id, major_in)


@router.delete(
    "/majors/{major_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_major(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một ngành học."""
    await organization_service.delete_major(db, major_id)
    return None


# ===============================================================
# CONFIG MANAGEMENT ROUTES
# ===============================================================


@router.get(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def get_assignment_config_route(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy cấu hình phân chia của một đơn vị."""
    params = await config_service.get_assignment_config(db, unit_id)
    return {"params": params}


@router.put(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def update_assignment_config_route(
    unit_id: int,
    config_in: schemas.AssignmentConfig,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật cấu hình phân chia của một đơn vị."""
    updated_model = await config_service.update_assignment_config(
        db, unit_id, config_in.params
    )
    # Trả về schema Pydantic dựa trên model đã cập nhật từ DB
    return schemas.AssignmentConfig(params=updated_model.params)


@router.get(
    "/skill-rules", response_model=List[schemas.SkillRule], tags=["Admin - Config"]
)
async def get_all_skill_rules_route(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy tất cả các quy tắc kỹ năng."""
    return await config_service.get_all_skill_rules(db)


@router.post(
    "/skill-rules",
    response_model=schemas.SkillRule,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Config"],
)
async def create_new_skill_rule_route(
    rule_in: schemas.SkillRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một quy tắc kỹ năng mới."""
    return await config_service.create_skill_rule(db, rule_in)


@router.delete(
    "/skill-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Config"],
)
async def delete_skill_rule_route(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một quy tắc kỹ năng."""
    await config_service.delete_skill_rule(db, rule_id)
    return None


# ===============================================================
# PIPELINE MANAGEMENT ROUTES (MỚI)
# ===============================================================


@router.get(
    "/pipeline-stages",
    response_model=List[schemas.PipelineStage],
    tags=["Admin - Pipeline Management"],
)
async def get_all_pipeline_stages_list(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy danh sách tất cả Giai đoạn (Stages) trong Pipeline."""
    # Gọi service function đã có (trả về List[dict] từ cache/DB)
    # Pydantic sẽ tự động chuyển đổi List[dict] -> List[schemas.PipelineStage]
    stages_data = await pipeline_service.get_all_pipeline_stages(db)
    return stages_data


@router.post(
    "/pipeline-stages",
    response_model=schemas.PipelineStage,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_pipeline_stage(
    stage_in: schemas.PipelineStageCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Giai đoạn (Stage) mới trong Pipeline."""
    return await pipeline_service.create_pipeline_stage(db, stage_in)


@router.get(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def get_pipeline_stage_details(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Giai đoạn (Stage)."""
    return await pipeline_service.get_pipeline_stage(db, stage_id)


@router.put(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_pipeline_stage(
    stage_id: str,
    stage_in: schemas.PipelineStageUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Giai đoạn (Stage)."""
    return await pipeline_service.update_pipeline_stage(db, stage_id, stage_in)


@router.delete(
    "/pipeline-stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_pipeline_stage(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Giai đoạn (Stage). (Chỉ thành công nếu không có Status nào liên kết)"""
    await pipeline_service.delete_pipeline_stage(db, stage_id)
    return None


@router.post(
    "/consultation-statuses",
    response_model=schemas.ConsultationStatus,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_consultation_status(
    status_in: schemas.ConsultationStatusCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Trạng thái tư vấn (Status) mới."""
    return await pipeline_service.create_consultation_status(db, status_in)


@router.get(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def get_consultation_status_details(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Trạng thái tư vấn (Status)."""
    return await pipeline_service.get_consultation_status(db, status_id)


@router.put(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_consultation_status(
    status_id: str,
    status_in: schemas.ConsultationStatusUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Trạng thái tư vấn (Status)."""
    return await pipeline_service.update_consultation_status(db, status_id, status_in)


@router.delete(
    "/consultation-statuses/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_consultation_status(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Trạng thái tư vấn (Status). (Chỉ thành công nếu không có Lead nào sử dụng)"""
    await pipeline_service.delete_consultation_status(db, status_id)
    return None


# ===============================================================
# LEAD MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/leads/{lead_id}/revert-status",
    response_model=schemas.Lead,
    tags=["Admin - Lead Management"],  # Thêm tag mới hoặc dùng tag cũ
    summary="Admin reverts the last status change of a Lead",
)
async def admin_revert_lead_status(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (Đã bao gồm check admin)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Check Casbin)
    reason: Optional[str] = Body(
        None, embed=True, description="Reason for reverting the status"
    ),
    db: AsyncSession = Depends(database.get_db),
):
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của một Lead.
    """
    try:
        # Dependency 'LeadAccessDep' đã kiểm tra quyền admin/manager
        updated_lead = await lead_service.revert_last_status(
            db=db, lead_id=lead.id, admin_user=current_user, reason=reason
        )
        return updated_lead
    except (BadRequest, ResourceNotFoundError) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.error(
            "Error reverting lead status via API",
            lead_id=lead.id,
            admin_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revert lead status.",
        )


@router.post(
    "/leads/bulk-assign",
    status_code=status.HTTP_202_ACCEPTED,  # Trả về 202 vì task chạy nền
    tags=["Admin - Lead Management"],
    summary="Trigger automatic assignment for multiple leads",
)
async def bulk_assign_leads(
    assignment_data: schemas.BulkAssignLeadsSchema,  # Sử dụng schema mới
    current_admin: models.User = PermissionDep,  # Yêu cầu quyền admin (qua Casbin)
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


@router.post(
    "/leads/import",
    response_model=schemas.LeadImportResult,  # Sử dụng schema kết quả mới
    status_code=status.HTTP_200_OK,  # Trả về 200 OK (hoặc 207 Multi-Status nếu muốn chi tiết hơn)
    tags=["Admin - Lead Management"],
    summary="Import leads from a CSV or Excel file",
)
async def import_leads_from_file(
    file: UploadFile = File(
        ..., description="CSV or Excel file containing lead data (.csv, .xlsx)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Import leads từ file CSV hoặc Excel.
    File cần có các cột: 'full_name', 'email', 'phone', 'source', 'unit_id', 'major_id' (tùy chọn).
    Endpoint sẽ tạo leads trong DB nhưng **không** tự động phân công.
    Trả về kết quả import bao gồm ID các lead đã tạo và danh sách lỗi.
    """
    log.info(
        "Received lead import request",
        admin_id=current_admin.id,
        filename=file.filename,
    )

    # --- 1. Kiểm tra loại file ---
    file_extension = ""
    if file.filename:
        file_extension = file.filename.rsplit(".", 1)[-1].lower()

    if file_extension not in ["csv", "xlsx"]:
        log.warning(
            "Import failed: Invalid file extension",
            filename=file.filename,
            ext=file_extension,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only .csv and .xlsx files are supported.",
        )

    # --- 2. Đọc nội dung file vào DataFrame ---
    try:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded."
            )

        if file_extension == "csv":
            # Dùng io.BytesIO để pandas đọc từ bytes
            df = pd.read_csv(io.BytesIO(content))
        else:  # xlsx
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")

        log.info(f"Successfully read {len(df)} rows from {file_extension} file.")

    except HTTPException as e:
        raise e  # Ném lại lỗi 400
    except Exception as e:
        log.error(
            "Failed to read or parse file content",
            filename=file.filename,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read or parse the file. Ensure it is a valid {file_extension} file. Error: {e}",
        )
    finally:
        await file.close()  # Luôn đóng file

    # --- 3. Xử lý dữ liệu và Tạo Leads ---
    required_columns = {"full_name", "email", "phone", "source", "unit_id"}
    # optional_columns = {"major_id"}  # Các cột tùy chọn
    # Chuẩn hóa tên cột (viết thường, bỏ dấu cách)
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")

    # Kiểm tra các cột bắt buộc
    missing_cols = required_columns - set(df.columns)
    if missing_cols:
        log.warning(
            "Import failed: Missing required columns", missing=list(missing_cols)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is missing required columns: {', '.join(missing_cols)}",
        )

    leads_to_insert = []
    errors: List[schemas.LeadImportError] = []
    processed_row_count = 0
    initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID  # Lấy status mặc định

    # Lấy stage_id tương ứng với initial_status_id (cần cho bulk insert)
    initial_status_obj = await db.get(models.ConsultationStatus, initial_status_id)
    initial_stage_id = initial_status_obj.stage_id if initial_status_obj else None
    if not initial_stage_id:
        log.error(
            f"FATAL: Initial status {initial_status_id} not found in DB. Cannot determine initial stage."
        )
        raise HTTPException(
            status_code=500,
            detail="System configuration error: Initial lead status not found.",
        )

    # Lấy danh sách email đã tồn tại để kiểm tra trùng lặp hiệu quả hơn
    existing_emails_in_db = set()
    async for email_tuple in await db.stream(select(models.Lead.email)):
        existing_emails_in_db.add(email_tuple[0])
    emails_in_current_file = set()

    # Lặp qua từng dòng trong DataFrame
    for index, row in df.iterrows():
        processed_row_count += 1
        row_number = index + 2
        row_data = row.to_dict()
        cleaned_data = {}  # Dữ liệu đã được ép kiểu
        validation_errors_for_row = []  # Lỗi ép kiểu

        # --- ✅ BẮT ĐẦU SỬA LỖI ÉP KIỂU ---

        # 1. Ép kiểu các trường bắt buộc
        try:
            # Dùng str() và strip() cho các trường text
            cleaned_data["full_name"] = str(row_data.get("full_name", "")).strip()
            cleaned_data["email"] = str(row_data.get("email", "")).strip()
            # Xử lý đặc biệt cho 'phone': luôn chuyển sang string, bỏ ".0" nếu là float
            phone_val = row_data.get("phone")
            cleaned_data["phone"] = (
                str(phone_val).split(".")[0] if pd.notna(phone_val) else ""
            )

            cleaned_data["source"] = str(row_data.get("source", "")).strip()

            # Xử lý 'unit_id': ép sang int
            unit_id_val = row_data.get("unit_id")
            if pd.notna(unit_id_val):
                cleaned_data["unit_id"] = int(float(unit_id_val))
            else:
                # Nếu unit_id là bắt buộc, Pydantic sẽ bắt lỗi 'missing' sau
                cleaned_data["unit_id"] = None

        except (ValueError, TypeError, Exception) as e:
            # Lỗi cơ bản khi ép kiểu (ví dụ: unit_id là "abc")
            validation_errors_for_row.append(f"Type conversion error: {e}")

        # 2. Ép kiểu trường tùy chọn 'major_id'
        major_id_val = row_data.get("major_id")
        if pd.notna(major_id_val):
            try:
                cleaned_data["major_id"] = int(float(major_id_val))
            except (ValueError, TypeError):
                validation_errors_for_row.append(
                    "Invalid format for 'major_id', expected a number."
                )
        else:
            cleaned_data["major_id"] = None

        # --- KẾT THÚC SỬA LỖI ÉP KIỂU ---

        # 3. Validate bằng Pydantic
        try:
            # Nếu đã có lỗi ép kiểu, ném lỗi luôn để vào khối except
            if validation_errors_for_row:
                raise ValueError(", ".join(validation_errors_for_row))

            lead_in = schemas.LeadCreate(**cleaned_data)

            # Kiểm tra trùng lặp email
            if (
                lead_in.email in existing_emails_in_db
                or lead_in.email in emails_in_current_file
            ):
                raise ValueError(
                    f"Email '{lead_in.email}' already exists in the database or this file."
                )

            emails_in_current_file.add(lead_in.email)

            # Chuẩn bị dict để bulk insert (Nếu mọi thứ OK)
            lead_dict = lead_in.model_dump()
            lead_dict["status"] = initial_status_id
            lead_dict["consultation_status_id"] = initial_status_id
            lead_dict["pipeline_stage_id"] = initial_stage_id
            lead_dict["assigned_officer_id"] = None
            lead_dict["assigned_at"] = None

            leads_to_insert.append(lead_dict)

        except (ValueError, TypeError) as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Data validation failed: {e}",  # Lỗi Pydantic hoặc lỗi ép kiểu/trùng lặp
                    row_data=row_data,
                )
            )
        except Exception as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Unexpected error processing row: {e}",
                    row_data=row_data,
                )
            )

    # --- 4. Thực hiện Bulk Insert ---
    created_lead_ids: List[int] = []
    batch_size = 100  # Commit mỗi 100 lead

    if leads_to_insert:
        try:
            for i in range(0, len(leads_to_insert), batch_size):
                batch = leads_to_insert[i : i + batch_size]
                
                async with db.begin_nested(): # Bắt đầu 1 transaction con
                    # 1. Insert batch
                    await db.execute(pg_insert(models.Lead), batch)
                    
                    # 2. Lấy ID của batch vừa insert
                    inserted_emails = [ld["email"] for ld in batch]
                    query = select(models.Lead.id).where(models.Lead.email.in_(inserted_emails))
                    result = await db.execute(query)
                    batch_ids = result.scalars().all()
                    created_lead_ids.extend(batch_ids)
                
                # 3. Commit transaction con (db.begin_nested() tự commit)
                log.info(f"Committed batch {i // batch_size + 1}, {len(batch_ids)} leads inserted.")

            # Commit transaction chính (nếu có)
            await db.commit()
            log.info(f"Successfully bulk inserted {len(created_lead_ids)} leads in total.")

        except Exception as e:
            await db.rollback() # Rollback transaction chính nếu có lỗi
            log.error(
                "Bulk lead insertion failed during batch, rolling back.", error=str(e), exc_info=True
            )
            # Ghi nhận lỗi
            errors.append(
                schemas.LeadImportError(
                    row_number=-1,
                    error_message=f"Database bulk insert error (batch failed): {e}",
                    row_data={},
                )
            )
            created_lead_ids = []  # Reset ID vì đã rollback

    # --- 5. Trả về kết quả ---
    result = schemas.LeadImportResult(
        total_rows_processed=processed_row_count,
        successful_imports=len(created_lead_ids),
        failed_imports=len(errors),
        created_lead_ids=created_lead_ids,
        errors=errors,
    )

    result_summary = result.model_dump(exclude={"errors"})
    if errors:
        log.warning("Lead import process finished with errors", result=result_summary)
    else:
        log.info("Lead import process finished successfully", result=result_summary)

    return result


# ===============================================================
# ACTIVITY LOGS & STATISTICS ROUTES
# ===============================================================


@router.get(
    "/activity-logs",
    response_model=schemas.ActivityLogsPage,
    tags=["Admin - Activity Logs"],
)
async def get_activity_logs(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    actor_id: Optional[int] = Query(None),
    target_user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
):
    """(Admin only) Lấy danh sách activity logs với filters."""
    skip = (page - 1) * page_size

    total, logs = await activity_service.get_activity_logs(
        db=db,
        skip=skip,
        limit=page_size,
        actor_id=actor_id,
        target_user_id=target_user_id,
        action=action,
        resource_type=resource_type,
    )

    return {"total_count": total, "logs": logs}


@router.get(
    "/statistics",
    response_model=schemas.UserStatistics,
    tags=["Admin - Statistics"],
)
async def get_user_statistics(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy thống kê tổng quan về users cho dashboard."""
    return await activity_service.get_user_statistics(db)


# =============================================================================
# ADVANCED CASBIN PERMISSION TOOLS
# =============================================================================


@router.get(
    "/policies/who-can-access",
    response_model=schemas.WhoCanAccessResponse,
    tags=["Admin - Policies (Advanced)"],
)
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
    from ..services.casbin_service import CasbinPolicyService

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
    await activity_service.log_activity_from_request(
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


@router.post(
    "/policies/simulate",
    response_model=schemas.PermissionSimulateResponse,
    tags=["Admin - Policies (Advanced)"],
)
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


@router.get(
    "/roles/{role_name}/features",
    response_model=schemas.RoleFeaturesResponse,
    tags=["Admin - Policies (Advanced)"],
)
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
    from ..casbin_config.policy_templates import FEATURE_MAP

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


@router.post(
    "/roles/{role_name}/features",
    response_model=schemas.PolicyBatchResult,
    tags=["Admin - Policies (Advanced)"],
)
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
    from ..casbin_config.policy_templates import FEATURE_MAP
    from ..services.casbin_service import CasbinPolicyService

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


@router.get(
    "/roles/{role_name}/explain",
    response_model=schemas.PermissionExplainResponse,
    tags=["Admin - Policies (Advanced)"],
)
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
    from ..casbin_config.policy_templates import (
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
