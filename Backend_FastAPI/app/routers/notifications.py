# app/routers/notifications.py
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import notification_service
from ..socket_manager import sio

router = APIRouter(tags=["Notifications"])
PermissionDep = Depends(deps.check_permission)


@router.get("", response_model=schemas.NotificationsPage)
async def get_my_notifications(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    unread_only: bool = Query(False),
):
    """Get notifications for the current user."""
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


@router.post("/mark-as-read", status_code=status.HTTP_200_OK)
async def mark_notifications_as_read(
    request: schemas.MarkAsReadRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Mark specific notifications as read."""
    count = await notification_service.mark_as_read(
        db=db,
        user_id=current_user.id,
        notification_ids=request.notification_ids,
    )

    return {"detail": f"Marked {count} notification(s) as read"}


@router.post("/mark-all-as-read", status_code=status.HTTP_200_OK)
async def mark_all_notifications_as_read(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Mark all notifications as read for the current user."""
    count = await notification_service.mark_all_as_read(
        db=db,
        user_id=current_user.id,
    )

    return {"detail": f"Marked {count} notification(s) as read"}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Delete a notification."""
    deleted = await notification_service.delete_notification(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    return None


# Helper function to send real-time notification via WebSocket
async def send_realtime_notification(
    notification: models.Notification,
):
    """Send notification to user via WebSocket."""
    try:
        # Emit to specific user's room
        await sio.emit(
            "notification",
            {
                "id": notification.id,
                "type": notification.type,
                "title": notification.title,
                "message": notification.message,
                "link": notification.link,
                "created_at": notification.created_at.isoformat(),
            },
            room=f"user_{notification.user_id}",
        )
    except Exception as e:
        # Log error but don't fail the request
        print(f"Failed to send real-time notification: {e}")
