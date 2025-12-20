# app/services/role_service.py
"""
Role Management Service

Handles role assignment, removal, and management operations.
Follows protocol-independent architecture - no HTTP dependencies.

Business Rules:
- Users must always have at least one role
- If last role removed, auto-assign "role:user"
- Database user.role field reflects highest priority role
- Role priority: admin > manager > officer > user
"""

from typing import Any, Callable, Dict, List, Tuple
import logging

import casbin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.utils.exceptions import ResourceNotFoundError

log = logging.getLogger(__name__)

# Role priority for determining DB field value (highest to lowest)
ROLE_PRIORITY = {
    "role:admin": 4,
    "role:manager": 3,
    "role:officer": 2,
    "role:user": 1,
}


async def remove_role_from_users(
    db: AsyncSession,
    enforcer: casbin.AsyncEnforcer,
    user_ids: List[int],
    role_to_remove: str,
) -> Tuple[Dict[str, Any], Callable]:
    """
    Remove a specific role from multiple users.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    SMART BEHAVIOR:
    - If user has ONLY this role → remove it and auto-assign "role:user"
    - If user has MULTIPLE roles → only remove this role, keep others
    - Updates database user.role to reflect remaining highest-priority role

    Args:
        db: Database session (injected via DI)
        enforcer: Casbin enforcer instance (injected via DI)
        user_ids: List of user IDs to remove role from
        role_to_remove: Role name to remove (e.g., "role:admin")

    Returns:
        Tuple of (result_dict, post_commit_callback)
        result_dict contains:
        - removed_count: Number of users role was removed from
        - reassigned_to_user_count: Number of users auto-assigned to "role:user"
        - failed_count: Number of failed operations
        - failed_users: List of failed operations with errors

    Raises:
        ResourceNotFoundError: If no user IDs provided

    Business Logic:
        1. For each user:
           a. Check if user has the role to remove
           b. Remove the role from Casbin
           c. Check remaining roles
           d. If no roles left, auto-assign "role:user"
           e. Update database user.role to highest priority role
        2. Flush changes to database
        3. Post-commit: Save Casbin policies
        4. Return operation summary

    Example:
        >>> result, callback = await remove_role_from_users(
        ...     db=session,
        ...     enforcer=app.state.enforcer,
        ...     user_ids=[1, 2, 3],
        ...     role_to_remove="role:manager"
        ... )
        >>> await db.commit()
        >>> await callback()
        >>> print(result["removed_count"])
        3
    """
    if not user_ids:
        raise ResourceNotFoundError(
            detail="No user IDs provided",
            context={"operation": "remove_role_from_users"}
        )

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
                log.warning(
                    f"User {user_id} doesn't have role {role_to_remove}, skipping"
                )
                continue

            # Remove the specified role from Casbin
            await enforcer.remove_grouping_policy(user_subject, role_to_remove)
            removed_count += 1

            # Get remaining roles after removal
            remaining_roles = [r for r in current_roles if r != role_to_remove]

            # SMART BEHAVIOR: If no roles left, auto-assign role:user as fallback
            if not remaining_roles:
                await enforcer.add_grouping_policy(user_subject, "role:user")
                remaining_roles = ["role:user"]
                reassigned_count += 1
                log.info(f"User {user_id} had no roles left, auto-assigned role:user")

            # Update database user.role field to highest priority remaining role
            # ✅ REFACTORED: Use UserRepository
            from app.repositories import UserRepository
            user_repo = UserRepository(db)
            user = await user_repo.get_by_id(user_id)

            if user:
                # Find highest priority role from remaining roles
                highest_priority_role = max(
                    remaining_roles,
                    key=lambda r: ROLE_PRIORITY.get(r, 0),
                    default="role:user",
                )

                # Extract role name without "role:" prefix for DB
                db_role_name = highest_priority_role.replace("role:", "")
                user.role = db_role_name
                db.add(user)

                log.info(
                    f"User {user_id} updated",
                    removed_role=role_to_remove,
                    remaining_roles=remaining_roles,
                    db_role=db_role_name,
                )

        except Exception as e:
            failed_users.append({"user_id": user_id, "error": str(e)})
            log.error(f"Failed to remove role from user {user_id}", error=str(e))

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # Save Casbin policies to persist changes
        await enforcer.save_policy()

    result = {
        "detail": f"Removed {role_to_remove} from {removed_count} user(s), {reassigned_count} auto-assigned to role:user",
        "removed_count": removed_count,
        "reassigned_to_user_count": reassigned_count,
        "failed_count": len(failed_users),
        "failed_users": failed_users,
    }

    return result, _post_commit


async def delete_role_atomic(
    db: AsyncSession,
    role_name: str,
    enforcer: casbin.AsyncEnforcer,
) -> Tuple[Dict[str, Any], Callable]:
    """
    Atomically delete a role with all its associations.
    Moved from Router to Service (Refactoring Pattern A).
    
    Args:
        db: Database session
        role_name: Role identifier (e.g., "role:support")
        enforcer: Casbin enforcer
        
    Returns:
        Tuple of (stats_dict, post_commit_callback)
    """
    from app.repositories import UserRepository
    from app.utils.exceptions import BadRequest, ResourceNotFoundError
    
    # STEP 1: Validate - System roles cannot be deleted
    SYSTEM_ROLES = {"role:admin", "role:manager", "role:officer", "role:user"}
    if role_name in SYSTEM_ROLES:
        raise BadRequest(f"Cannot delete system role: {role_name}")

    # STEP 2: Check if role exists (has any policies)
    all_policies = enforcer.get_policy()
    role_has_policies = any(p[0] == role_name for p in all_policies)
    if not role_has_policies:
        raise ResourceNotFoundError(f"Role not found: {role_name}")

    user_repo = UserRepository(db)
    
    # STEP 3a: Find all users with this role in DB (using Repository)
    db_role = role_name.replace("role:", "")
    users_from_db = await user_repo.get_by_db_role(db_role)

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

    # STEP 4: Update users in DB to role:user (using Repository)
    reassigned_count = 0
    users_to_update = await user_repo.get_by_ids(list(all_user_ids))
    for user in users_to_update:
        # Only update if they had this role
        if user.role == db_role:
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

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # Save Casbin policies
        await enforcer.save_policy()
        log.info(
            f"Atomic role deletion complete for {role_name}",
            reassigned=reassigned_count,
            policies_removed=removed_p_count
        )

    result = {
        "detail": f"Role {role_name} deleted successfully",
        "role_name": role_name,
        "users_reassigned": reassigned_count,
        "permission_policies_removed": removed_p_count,
        "user_grouping_policies_removed": removed_g_user_count,
        "inheritance_grouping_policies_removed": removed_g_inherit_count,
        "total_affected_users": len(all_user_ids),
    }
    
    return result, _post_commit
