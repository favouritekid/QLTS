# app/services/notification_service.py
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import logging

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.services import notification_preference_service
from app.services.email_service import EmailService

log = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    notification_type: str = "info",
    link: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> models.Notification:
    """
    Create a new notification for a user with preference checking.

    This function:
    1. Checks user's notification preferences
    2. Creates the notification in the database (if preferences allow)
    3. Sends an email notification (if preferences allow)

    Args:
        db: Database session
        user_id: ID of the user to notify
        title: Notification title
        message: Notification message
        notification_type: Type of notification (info, success, warning, error, admin_update, system)
        link: Optional link to navigate to
        data: Optional additional data

    Returns:
        Created Notification instance
    """
    # Check user preferences
    should_send = await notification_preference_service.should_send_notification(
        db, user_id, notification_type
    )

    log.info(
        "Notification preference check",
        extra={
            "user_id": user_id,
            "notification_type": notification_type,
            "should_send": should_send,
        }
    )

    # Always create the notification in the database
    # Preferences only control delivery channels (email, sound, browser)
    notification = models.Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        message=message,
        link=link,
        data=data,
    )

    db.add(notification)
    await db.commit()
    await db.refresh(notification)

    # Send email if preferences allow
    if should_send["send_email"]:
        try:
            # Get user info for email
            user = await db.get(models.User, user_id)
            if user and user.email:
                email_service = EmailService()
                email_sent = email_service.send_notification_email(
                    user.email,
                    user.full_name or user.username,
                    notification
                )

                if email_sent:
                    log.info(
                        "Email notification sent successfully",
                        extra={"user_id": user_id, "notification_id": notification.id}
                    )
                else:
                    log.warning(
                        "Failed to send email notification",
                        extra={"user_id": user_id, "notification_id": notification.id}
                    )
        except Exception as e:
            log.error(
                "Error sending email notification",
                extra={"user_id": user_id, "notification_id": notification.id, "error": str(e)}
            )

    return notification


async def get_user_notifications(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False,
) -> Tuple[int, int, List[models.Notification]]:
    """
    Get notifications for a user.

    Returns:
        Tuple of (total_count, unread_count, notifications list)
    """
    # Build base query
    filters = [models.Notification.user_id == user_id]

    if unread_only:
        filters.append(models.Notification.is_read == False)  # noqa: E712

    # Count total notifications
    count_query = select(func.count()).select_from(models.Notification).where(and_(*filters))
    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0

    # Count unread notifications
    unread_query = select(func.count()).select_from(models.Notification).where(
        and_(
            models.Notification.user_id == user_id,
            models.Notification.is_read == False  # noqa: E712
        )
    )
    unread_result = await db.execute(unread_query)
    unread_count = unread_result.scalar() or 0

    # Get notifications
    query = (
        select(models.Notification)
        .where(and_(*filters))
        .order_by(desc(models.Notification.created_at))
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)
    notifications = result.scalars().all()

    return total_count, unread_count, list(notifications)


async def mark_as_read(
    db: AsyncSession,
    user_id: int,
    notification_ids: List[int],
) -> int:
    """
    Mark notifications as read.

    Returns:
        Number of notifications marked as read
    """
    # Get notifications that belong to the user and are unread
    query = select(models.Notification).where(
        and_(
            models.Notification.id.in_(notification_ids),
            models.Notification.user_id == user_id,
            models.Notification.is_read == False  # noqa: E712
        )
    )

    result = await db.execute(query)
    notifications = result.scalars().all()

    # Mark as read
    for notification in notifications:
        notification.is_read = True
        notification.read_at = datetime.utcnow()

    await db.commit()

    return len(notifications)


async def mark_all_as_read(
    db: AsyncSession,
    user_id: int,
) -> int:
    """
    Mark all notifications as read for a user.

    Returns:
        Number of notifications marked as read
    """
    query = select(models.Notification).where(
        and_(
            models.Notification.user_id == user_id,
            models.Notification.is_read == False  # noqa: E712
        )
    )

    result = await db.execute(query)
    notifications = result.scalars().all()

    # Mark as read
    for notification in notifications:
        notification.is_read = True
        notification.read_at = datetime.utcnow()

    await db.commit()

    return len(notifications)


async def delete_notification(
    db: AsyncSession,
    user_id: int,
    notification_id: int,
) -> bool:
    """
    Delete a notification.

    Returns:
        True if deleted, False if not found
    """
    query = select(models.Notification).where(
        and_(
            models.Notification.id == notification_id,
            models.Notification.user_id == user_id,
        )
    )

    result = await db.execute(query)
    notification = result.scalar_one_or_none()

    if not notification:
        return False

    await db.delete(notification)
    await db.commit()

    return True
