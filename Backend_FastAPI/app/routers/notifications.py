# app/routers/notifications.py
from typing import List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import notification_service
from ..socket_manager import sio
from app.core.rate_limits import limiter, RateLimits

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Notifications"])
PermissionDep = Depends(deps.check_permission)


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=schemas.NotificationsPage)
async def get_my_notifications(
    request: Request,  # ✅ Required for rate limiter
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
):
    """
    Get notifications for the current user.

    Rate limit: 60 requests/minute per IP (production), 10000/minute (test).
    This prevents Thundering Herd problem when many users reconnect simultaneously.
    """
    skip = (page - 1) * page_size

    total, unread, notifications = await notification_service.get_user_notifications(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=page_size,
        unread_only=unread_only,
    )

    return {
        "total_count": total,
        "unread_count": unread,
        "notifications": notifications,
    }


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("/mark-as-read", status_code=status.HTTP_200_OK)
async def mark_notifications_as_read(
    http_request: Request,
    request: schemas.MarkAsReadRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Mark specific notifications as read."""
    count, callback = await notification_service.mark_as_read(
        db=db,
        user_id=current_user.id,
        notification_ids=request.notification_ids,
    )
    await db.commit()
    await callback()

    return {"detail": f"Marked {count} notification(s) as read"}


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("/mark-all-as-read", status_code=status.HTTP_200_OK)
async def mark_all_notifications_as_read(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Mark all notifications as read for the current user."""
    count, callback = await notification_service.mark_all_as_read(
        db=db,
        user_id=current_user.id,
    )
    await db.commit()
    await callback()

    return {"detail": f"Marked {count} notification(s) as read"}


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    request: Request,
    notification_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Delete a notification."""
    deleted, callback = await notification_service.delete_notification(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    await db.commit()
    await callback()

    return None


# Helper function to send real-time notification via WebSocket
async def send_realtime_notification(
    notification: models.Notification,
):
    """Send notification to user via WebSocket."""
    try:
        room_name = f"user_room_{notification.user_id}"

        notification_data = {
            "id": notification.id,
            "user_id": notification.user_id,
            "type": notification.type,
            "title": notification.title,
            "message": notification.message,
            "link": notification.link,
            "data": notification.data,
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat(),
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
        }

        # Emit to specific user's room
        await sio.emit(
            "notification",
            notification_data,
            room=room_name,
        )

        log.info(
            "Real-time notification sent via WebSocket",
            notification_id=notification.id,
            user_id=notification.user_id,
            room=room_name,
            type=notification.type,
        )
    except Exception as e:
        # Log error but don't fail the request
        log.error(
            "Failed to send real-time notification",
            notification_id=notification.id,
            user_id=notification.user_id,
            error=str(e),
        )