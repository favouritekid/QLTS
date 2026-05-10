# app/services/activity_service.py
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

# ✅ PHASE 1: Removed FastAPI Request import (protocol-independent)
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models, schemas


# Pass 2 hard-review BM-3: depth cap parity với audit_service._serialize_value.
_MAX_JSON_SAFE_DEPTH = 10
_DEPTH_SENTINEL = "[truncated: depth_exceeded]"


def _json_safe(value: Any, _depth: int = 0) -> Any:
    """Recursive serialize cho JSON column (changes field).

    JSON column raw INSERT raise TypeError với date/Decimal/UUID. Đây là
    last-mile shim — caller có thể quên set ``mode="json"`` trên Pydantic
    dump hoặc trộn raw model values vào dict.

    Pass 2 hard-review BM-3: depth cap _MAX_JSON_SAFE_DEPTH chống stack
    overflow trên adversarial nested JSONB. Trả sentinel marker nếu vượt.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):  # AFTER datetime (datetime kế thừa date)
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if _depth >= _MAX_JSON_SAFE_DEPTH:
        return _DEPTH_SENTINEL
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, _depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v, _depth + 1) for k, v in value.items()}
    if hasattr(value, "value"):  # enum
        return value.value
    return str(value)


async def log_activity(
    db: AsyncSession,
    action: str,
    resource_type: str,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    description: Optional[str] = None,
    changes: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[models.UserActivityLog, Callable]:
    """
    Create a new activity log entry.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        action: Action performed (e.g., 'create_user', 'update_user', 'login')
        resource_type: Type of resource (e.g., 'user', 'lead', 'organization')
        actor_id: ID of the user who performed the action
        target_user_id: ID of the target user (for user management actions)
        resource_id: ID of the resource affected
        description: Human-readable description of the action
        changes: Dictionary of changes made (old vs new values)
        ip_address: IP address of the requester
        user_agent: User agent string

    Returns:
        Tuple of (activity_log, post_commit_callback)
    """
    activity_log = models.UserActivityLog(
        actor_id=actor_id,
        target_user_id=target_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        # JSON column safety: serialize date/Decimal/UUID inside dict.
        changes=_json_safe(changes) if changes is not None else None,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.add(activity_log)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()
    await db.refresh(activity_log)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        pass  # No post-commit actions needed for activity logs

    return activity_log, _post_commit


# ✅ PHASE 1: Removed log_activity_from_request() - routers should extract IP/UA
# Routers can call log_activity() directly with:
#   ip_address = request.client.host if request.client else None
#   user_agent = request.headers.get("user-agent")


async def get_activity_logs(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Tuple[int, List[schemas.UserActivityLogWithDetails]]:
    """
    Get activity logs with optional filters.

    ✅ REFACTORED: Uses ActivityRepository for data access.

    Returns:
        Tuple of (total_count, list of activity logs with user details)
    """
    from ..repositories import ActivityRepository
    
    repo = ActivityRepository(db)
    total_count, logs = await repo.get_filtered(
        skip=skip,
        limit=limit,
        actor_id=actor_id,
        target_user_id=target_user_id,
        action=action,
        resource_type=resource_type,
        start_date=start_date,
        end_date=end_date,
    )

    # Convert to schema with details
    logs_with_details = []
    for log in logs:
        log_dict = {
            "id": log.id,
            "actor_id": log.actor_id,
            "target_user_id": log.target_user_id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "description": log.description,
            "changes": log.changes,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "created_at": log.created_at,
            "actor_username": log.actor.username if log.actor else None,
            "actor_full_name": log.actor.full_name if log.actor else None,
            "target_username": log.target_user.username if log.target_user else None,
            "target_full_name": log.target_user.full_name if log.target_user else None,
        }
        logs_with_details.append(schemas.UserActivityLogWithDetails(**log_dict))

    return total_count, logs_with_details


async def get_user_statistics(db: AsyncSession) -> schemas.UserStatistics:
    """
    Get comprehensive user statistics for the dashboard.

    ✅ REFACTORED: Uses ActivityRepository for data access.

    Returns:
        UserStatistics schema with counts and recent activities
    """
    from ..repositories import ActivityRepository
    
    repo = ActivityRepository(db)
    
    # Count users by status via repository
    status_counts = await repo.get_user_counts_by_status()
    active_users = status_counts.get("active", 0)
    pending_users = status_counts.get("pending", 0)
    banned_users = status_counts.get("banned", 0)

    # Total users via repository
    total_users = await repo.get_total_user_count()

    # Count users by role via repository
    users_by_role = await repo.get_user_counts_by_role()

    # New users in last 7 days and 30 days
    # Note: This assumes User model has created_at field - if not, skip or use another method
    # For now, let's set these to 0 as the User model doesn't have created_at
    new_users_last_7_days = 0
    new_users_last_30_days = 0

    # Get recent activities (last 10)
    _, recent_activities = await get_activity_logs(
        db=db,
        limit=10,
        resource_type="user"
    )

    return schemas.UserStatistics(
        total_users=total_users,
        active_users=active_users,
        pending_users=pending_users,
        banned_users=banned_users,
        new_users_last_7_days=new_users_last_7_days,
        new_users_last_30_days=new_users_last_30_days,
        users_by_role=users_by_role,
        recent_activities=recent_activities,
    )

