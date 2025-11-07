# app/services/activity_service.py
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Request
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models, schemas


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
) -> models.UserActivityLog:
    """
    Create a new activity log entry.

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
        The created UserActivityLog instance
    """
    activity_log = models.UserActivityLog(
        actor_id=actor_id,
        target_user_id=target_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.add(activity_log)
    await db.commit()
    await db.refresh(activity_log)

    return activity_log


async def log_activity_from_request(
    db: AsyncSession,
    request: Request,
    action: str,
    resource_type: str,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    description: Optional[str] = None,
    changes: Optional[Dict[str, Any]] = None,
) -> models.UserActivityLog:
    """
    Create activity log from a FastAPI Request object.
    Automatically extracts IP and user agent from request.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", None)

    return await log_activity(
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

    Returns:
        Tuple of (total_count, list of activity logs with user details)
    """
    # Build filters
    filters = []
    if actor_id is not None:
        filters.append(models.UserActivityLog.actor_id == actor_id)
    if target_user_id is not None:
        filters.append(models.UserActivityLog.target_user_id == target_user_id)
    if action is not None:
        filters.append(models.UserActivityLog.action == action)
    if resource_type is not None:
        filters.append(models.UserActivityLog.resource_type == resource_type)
    if start_date is not None:
        filters.append(models.UserActivityLog.created_at >= start_date)
    if end_date is not None:
        filters.append(models.UserActivityLog.created_at <= end_date)

    # Count total
    count_query = select(func.count()).select_from(models.UserActivityLog)
    if filters:
        count_query = count_query.where(and_(*filters))
    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0

    # Get logs with user details
    query = (
        select(models.UserActivityLog)
        .options(
            selectinload(models.UserActivityLog.actor),
            selectinload(models.UserActivityLog.target_user),
        )
        .order_by(desc(models.UserActivityLog.created_at))
        .offset(skip)
        .limit(limit)
    )

    if filters:
        query = query.where(and_(*filters))

    result = await db.execute(query)
    logs = result.scalars().all()

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

    Returns:
        UserStatistics schema with counts and recent activities
    """
    # Count users by status
    status_query = (
        select(
            models.User.status,
            func.count(models.User.id).label("count")
        )
        .group_by(models.User.status)
    )
    status_result = await db.execute(status_query)
    status_counts = {row.status: row.count for row in status_result}

    active_users = status_counts.get("active", 0)
    pending_users = status_counts.get("pending", 0)
    banned_users = status_counts.get("banned", 0)

    # Total users
    total_query = select(func.count()).select_from(models.User)
    total_result = await db.execute(total_query)
    total_users = total_result.scalar() or 0

    # Count users by role
    role_query = (
        select(
            models.User.role,
            func.count(models.User.id).label("count")
        )
        .group_by(models.User.role)
    )
    role_result = await db.execute(role_query)
    users_by_role = {row.role: row.count for row in role_result}

    # New users in last 7 days and 30 days
    # Note: This assumes User model has created_at field - if not, skip or use another method
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    # Check if User model has created_at (or use id as proxy if not)
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
