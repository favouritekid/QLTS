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

from typing import Callable, Dict, List, Tuple
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
) -> Tuple[Dict[str, any], Callable]:
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
            result = await db.execute(
                select(models.User).where(models.User.id == user_id)
            )
            user = result.scalar_one_or_none()

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
