# app/services/notification_dispatcher.py
"""
Notification Dispatcher - Central Event Bus for the notification system.

The dispatcher is the entry point for publishing events. It handles:
1. Registry lookup
2. Recipient resolution
3. Preference filtering
4. Deduplication
5. Bulk notification creation
6. Celery task dispatch for async delivery

Transaction Safety:
- All database operations are committed BEFORE Celery tasks are dispatched
- If DB commit fails, no Celery tasks are sent (prevents ghost notifications)

Usage:
    from app.services.notification_dispatcher import dispatch

    notification_ids = await dispatch(
        db=db,
        event=SystemEvents.LEAD_ASSIGNED,
        payload={
            "lead_id": 123,
            "officer_id": 456,
            "actor_id": 789,
            "lead_name": "John Doe"
        }
    )
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import and_, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.core.event_groups import get_event_group, NotificationChannel
from app.services.notification_registry import get_event_config, NotificationConfig
from app.services import notification_preference_service

log = logging.getLogger(__name__)

# Chunk size for bulk insert (to avoid overwhelming the DB)
BULK_INSERT_CHUNK_SIZE = 100


async def dispatch(
    db: AsyncSession,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    skip_preference_check: bool = False,
) -> List[int]:
    """
    Dispatch a notification event.

    This is the main entry point for the event-driven notification system.
    It handles the complete flow from event to notification delivery.

    Args:
        db: Async database session
        event: The system event to dispatch
        payload: Event payload with data for resolution and templates
        dedupe_key: Optional key for deduplication (e.g., "lead_assigned:123:456")
                   If provided, prevents duplicate notifications for same key+user
        skip_preference_check: If True, skip user preference filtering
                              Use for critical system notifications

    Returns:
        List of created notification IDs

    Flow:
        1. Lookup event config from registry
        2. Resolve recipients using configured resolver
        3. Filter recipients by preferences (unless skipped)
        4. Apply deduplication logic
        5. Bulk insert notifications
        6. Commit transaction
        7. Dispatch Celery task for async delivery

    Example:
        notification_ids = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload={
                "lead_id": 123,
                "officer_id": 456,
                "lead_name": "John Doe",
                "actor_id": 789
            },
            dedupe_key="lead_assigned:123:456"
        )
    """
    log.info(
        f"Dispatching event: {event.value}",
        extra={"event": event.value, "dedupe_key": dedupe_key}
    )

    # Step 1: Lookup registry
    config = get_event_config(event)
    if not config:
        log.error(f"Event {event} not found in registry, skipping dispatch")
        return []

    # Step 2: Resolve recipients
    try:
        user_ids = await config.resolver.resolve_users(db, payload)
    except Exception as e:
        log.error(
            f"Failed to resolve users for event {event}: {str(e)}",
            extra={"payload": payload}
        )
        return []

    if not user_ids:
        log.info(f"No recipients resolved for event {event}")
        return []

    log.info(f"Resolved {len(user_ids)} recipients for event {event}")

    # Step 3: Filter by preferences
    if not skip_preference_check:
        group = get_event_group(event)
        user_ids = await notification_preference_service.filter_users_by_group(
            db=db,
            user_ids=user_ids,
            group=group.value,
            channel=NotificationChannel.BROWSER.value
        )

        if not user_ids:
            log.info(
                f"All recipients filtered out by preferences for event {event}"
            )
            return []

        log.info(f"After preference filtering: {len(user_ids)} recipients")

    # Step 4: Apply deduplication
    if dedupe_key:
        user_ids = await _apply_deduplication(db, user_ids, dedupe_key)

        if not user_ids:
            log.info(f"All recipients filtered out by deduplication for event {event}")
            return []

        log.info(f"After deduplication: {len(user_ids)} recipients")

    # Step 5: Render notification content
    title = config.render_title(payload)
    message = config.render_message(payload)
    link = config.render_link(payload)

    # Determine notification type (can be overridden by payload for alerts)
    notification_type = payload.get("severity", config.notification_type)

    # Build data payload for notification (exclude large fields)
    notification_data = {
        "event": event.value,
        "group": config.group.value,
        **{k: v for k, v in payload.items() if k not in ["message", "description"]}
    }
    if dedupe_key:
        notification_data["dedupe_key"] = dedupe_key

    # Step 6: Bulk insert notifications
    notification_ids = await _bulk_create_notifications(
        db=db,
        user_ids=user_ids,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link,
        data=notification_data
    )

    if not notification_ids:
        log.error(f"Failed to create notifications for event {event}")
        return []

    # Step 7: Commit transaction BEFORE dispatching Celery tasks
    try:
        await db.commit()
        log.info(f"Committed {len(notification_ids)} notifications for event {event}")
    except Exception as e:
        log.error(
            f"Failed to commit notifications for event {event}: {str(e)}"
        )
        await db.rollback()
        return []

    # Step 8: Dispatch Celery task for async delivery
    try:
        _dispatch_broadcast_task(
            notification_ids=notification_ids,
            channels=config.channels,
            event=event.value
        )
    except Exception as e:
        # Log but don't fail - notifications are already in DB
        log.error(
            f"Failed to dispatch Celery task for event {event}: {str(e)}. "
            "Notifications are saved but won't be pushed."
        )

    return notification_ids


async def _apply_deduplication(
    db: AsyncSession,
    user_ids: List[int],
    dedupe_key: str
) -> List[int]:
    """
    Filter out users who already have a notification with the same dedupe_key.

    This prevents duplicate notifications when the same event is dispatched
    multiple times (e.g., retries, race conditions).

    Args:
        db: Database session
        user_ids: List of user IDs to check
        dedupe_key: The deduplication key

    Returns:
        Filtered list of user IDs who don't have the notification yet
    """
    try:
        # Find users who already have notification with this dedupe_key
        # The dedupe_key is stored in the data JSON column
        result = await db.execute(
            select(models.Notification.user_id)
            .where(
                and_(
                    models.Notification.user_id.in_(user_ids),
                    models.Notification.data["dedupe_key"].astext == dedupe_key
                )
            )
        )
        existing_user_ids = {row[0] for row in result.fetchall()}

        # Return users who don't have the notification yet
        return [uid for uid in user_ids if uid not in existing_user_ids]

    except Exception as e:
        log.warning(
            f"Deduplication check failed, proceeding without: {str(e)}"
        )
        # On failure, proceed without deduplication to avoid losing notifications
        return user_ids


async def _bulk_create_notifications(
    db: AsyncSession,
    user_ids: List[int],
    title: str,
    message: str,
    notification_type: str,
    link: Optional[str],
    data: dict
) -> List[int]:
    """
    Bulk insert notifications for multiple users.

    Uses SQLAlchemy Core insert for efficiency with large recipient lists.
    Processes in chunks to avoid DB timeout.

    Args:
        db: Database session
        user_ids: List of recipient user IDs
        title: Notification title
        message: Notification message
        notification_type: Type (info, success, warning, error)
        link: Optional navigation link
        data: Additional data payload

    Returns:
        List of created notification IDs
    """
    notification_ids = []
    now = datetime.now(timezone.utc)

    # Process in chunks
    for i in range(0, len(user_ids), BULK_INSERT_CHUNK_SIZE):
        chunk = user_ids[i:i + BULK_INSERT_CHUNK_SIZE]

        # Build insert values
        values = [
            {
                "user_id": user_id,
                "type": notification_type,
                "title": title,
                "message": message,
                "link": link,
                "data": data,
                "is_read": False,
                "created_at": now
            }
            for user_id in chunk
        ]

        try:
            # Use insert with RETURNING to get IDs
            result = await db.execute(
                insert(models.Notification)
                .values(values)
                .returning(models.Notification.id)
            )
            chunk_ids = [row[0] for row in result.fetchall()]
            notification_ids.extend(chunk_ids)

            log.debug(f"Created {len(chunk_ids)} notifications in chunk {i // BULK_INSERT_CHUNK_SIZE + 1}")

        except Exception as e:
            log.error(
                f"Failed to bulk insert notifications (chunk {i // BULK_INSERT_CHUNK_SIZE + 1}): {str(e)}"
            )
            # Continue with other chunks

    return notification_ids


def _dispatch_broadcast_task(
    notification_ids: List[int],
    channels: List[str],
    event: str
):
    """
    Dispatch Celery task to broadcast notifications.

    This function queues the notification delivery for async processing.
    Socket.IO push and email sending happen in the Celery worker.

    Args:
        notification_ids: List of notification IDs to broadcast
        channels: List of channels to use (browser, email, sms)
        event: Event name for logging/metrics
    """
    try:
        from app.celery_utils import celery_app

        # Queue the broadcast task
        celery_app.send_task(
            "broadcast_notification_task",
            kwargs={
                "notification_ids": notification_ids,
                "channels": channels,
                "event": event
            },
            queue="notifications"  # Use dedicated queue if available
        )

        log.info(
            f"Queued broadcast task for {len(notification_ids)} notifications "
            f"(event: {event}, channels: {channels})"
        )

    except Exception as e:
        log.error(f"Failed to queue broadcast task: {str(e)}")
        raise


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def dispatch_to_user(
    db: AsyncSession,
    user_id: int,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None
) -> List[int]:
    """
    Dispatch a notification to a specific user.

    Convenience wrapper that ensures the user_id is in the payload
    for SpecificUsersResolver.

    Args:
        db: Database session
        user_id: Target user ID
        event: System event
        payload: Event payload
        dedupe_key: Optional deduplication key

    Returns:
        List of created notification IDs (typically [id] or [])
    """
    payload["user_id"] = user_id
    return await dispatch(db, event, payload, dedupe_key)


async def dispatch_to_users(
    db: AsyncSession,
    user_ids: List[int],
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None
) -> List[int]:
    """
    Dispatch a notification to multiple specific users.

    Convenience wrapper that ensures user_ids is in the payload
    for SpecificUsersResolver.

    Args:
        db: Database session
        user_ids: Target user IDs
        event: System event
        payload: Event payload
        dedupe_key: Optional deduplication key

    Returns:
        List of created notification IDs
    """
    payload["user_ids"] = user_ids
    return await dispatch(db, event, payload, dedupe_key)


async def dispatch_system_alert(
    db: AsyncSession,
    severity: str,
    message: str,
    action_url: Optional[str] = None,
    user_ids: Optional[List[int]] = None
) -> List[int]:
    """
    Dispatch a system alert to all users or specific users.

    Convenience wrapper for SYSTEM_ALERT event.

    Args:
        db: Database session
        severity: Alert severity (info, warning, error)
        message: Alert message
        action_url: Optional URL for action
        user_ids: Optional list of specific users (default: all users)

    Returns:
        List of created notification IDs
    """
    payload = {
        "severity": severity,
        "message": message,
        "action_url": action_url or ""
    }

    if user_ids:
        payload["user_ids"] = user_ids

    return await dispatch(
        db=db,
        event=SystemEvents.SYSTEM_ALERT,
        payload=payload,
        skip_preference_check=(severity == "error")  # Don't skip critical alerts
    )
