# app/services/notification_dispatcher.py
"""
✅ NOTIFICATION 2.0 - Central Event Bus with Multi-Channel Support

The dispatcher is the entry point for publishing events. It handles:
1. Database/Registry rule lookup
2. Condition evaluation (database rules only)
3. Recipient resolution
4. Preference filtering
5. Deduplication
6. Bulk notification creation
7. Database commit
8. ✅ NOTIFICATION 2.0: Multi-channel delivery via Channel Infrastructure

Transaction Safety:
- All database operations are committed BEFORE any notifications are sent
- Channels send notifications immediately after DB commit
- If DB commit fails, no notifications are sent (prevents ghost notifications)

Channel Delivery:
- Uses unified Channel Infrastructure (Strategy Pattern)
- Each channel (socket, email, zalo, sms) handles its own delivery
- Channels are independent - failure in one doesn't affect others
- Channel results logged for monitoring

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
import asyncio
import structlog
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Tuple

# from sqlalchemy import and_, cast, insert, select, String (removed - using repository)
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.core.event_groups import get_event_group, NotificationChannel
from app.database import safe_redis_lpush, safe_redis_ltrim, safe_redis_expire
from app.services.notification_registry import get_event_config, NotificationConfig
from app.services import notification_preference_service
from app.repositories import NotificationRepository
# ✅ PHASE 2.3: Import database rule loader
from app.services.notification_rule_loader import get_rule_for_event

log = structlog.get_logger(__name__)

# ✅ PHASE 1.2: Import cache config from notification_service
from app.services.notification_service import (
    INBOX_CACHE_KEY_PREFIX,
    INBOX_CACHE_MAX_SIZE,
    INBOX_CACHE_TTL,
)

# Chunk size for bulk insert (to avoid overwhelming the DB)
BULK_INSERT_CHUNK_SIZE = 100


# =============================================================================
# DOMAIN EVENT EMITTER - Real-time UI Refresh
# =============================================================================

async def _emit_domain_event(
    event: SystemEvents,
    payload: dict,
) -> None:
    """
    ✅ REAL-TIME SYNC: Emit domain event via Socket.IO for instant UI refresh.
    
    This broadcasts to ALL connected clients, enabling real-time data sync:
    - Frontend receives event (e.g., "lead_created")
    - React Query invalidates relevant queries
    - UI automatically refetches fresh data
    
    Race condition prevention:
    - Includes timestamp for event ordering
    - Includes event_id for deduplication
    - Only called AFTER transaction commit (data is persisted)
    
    Args:
        event: SystemEvents enum (e.g., LEAD_CREATED, CONSULTATION_UPDATED)
        payload: Event payload to send to clients
    """
    from app.socket_manager import sio
    
    try:
        # Create event data with timestamp for race condition handling
        event_data = {
            **payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": f"{event.value}:{payload.get('lead_id', payload.get('consultation_id', 'unknown'))}:{int(datetime.now().timestamp() * 1000)}",
        }
        
        # Broadcast to all connected clients
        await sio.emit(event.value, event_data)
        
        log.info(
            "Domain event broadcast",
            event_type=event.value,
            payload_keys=list(payload.keys())
        )
    except Exception as e:
        # Non-critical failure - log warning but don't raise
        log.warning(
            "Failed to emit domain event (non-critical)",
            event_type=event.value,
            error=str(e)
        )


async def _send_via_channel(
    channel_name: str,
    notifications: List[Any],
    recipient_ids: List[int],
    context: dict,
    event: str
) -> Tuple[str, Optional[Any], Optional[str]]:
    """
    ✅ NOTIFICATION 2.0 - PHASE 3.1: Send notifications via a single channel with error handling.

    Helper function for parallel channel delivery using asyncio.gather().

    Args:
        channel_name: Name of the channel ("socket", "email", etc.)
        notifications: List of notification objects to send
        recipient_ids: List of recipient user IDs
        context: Event payload context
        event: Event name for logging

    Returns:
        Tuple of (channel_name, ChannelResult or None, error_message or None)
        - On success: (channel_name, ChannelResult, None)
        - On failure: (channel_name, None, error_message)
    """
    try:
        from app.services.notification_channels import get_channel

        channel = get_channel(channel_name)
        result = await channel.send(
            notifications=notifications,
            recipient_ids=recipient_ids,
            context=context
        )
        return (channel_name, result, None)

    except ValueError as e:
        # Unknown channel (not registered)
        return (channel_name, None, f"Unknown channel: {str(e)}")
    except Exception as e:
        # Channel send failed
        return (channel_name, None, f"Delivery failed: {str(e)}")


async def dispatch(
    db: AsyncSession,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None,
    skip_preference_check: bool = False,
) -> Tuple[List[int], Optional[Callable]]:
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
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().

    Flow:
        1. Lookup event config from registry
        2. Resolve recipients using configured resolver
        3. Filter recipients by preferences (unless skipped)
        4. Apply deduplication logic
        5. Bulk insert notifications
        6. Flush (caller commits)
        7. Return post-commit callback for channel delivery

    Example:
        notification_ids, callback = await dispatch(
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
        await db.commit()
        if callback:
            await callback()
    """
    log.info(
        "Dispatching notification event",
        event_type=event.value,
        dedupe_key=dedupe_key,
        payload_keys=list(payload.keys())
    )

    # Step 1: ✅ PHASE 2.3: Load rule from database (or fallback to hardcoded registry)
    # Try database first for visual management
    config = await get_rule_for_event(db, event)
    rule_source = "database" if config else None

    # Fallback to hardcoded registry if no database rule
    if not config:
        config = get_event_config(event)
        rule_source = "registry" if config else None

    if not config:
        log.warning(
            "No notification rule found for event (still emitting domain event for UI sync)",
            event_type=event.value,
            checked_sources=["database", "registry"]
        )
        # ✅ IMPORTANT: Still emit domain event for real-time UI refresh
        # Notification rules are for per-user notifications
        # Domain events are for broadcasting data changes to ALL clients
        async def _domain_only_callback():
            await _emit_domain_event(event, payload)

        return [], _domain_only_callback

    log.info(
        "Loaded notification rule",
        event_type=event.value,
        rule_source=rule_source,
        rule_id=getattr(config, 'rule_id', None),
        channels=config.channel_values
    )

    # Step 1.5: ✅ PHASE 2.3: Check activation condition (database rules only)
    if rule_source == "database" and hasattr(config, 'should_activate'):
        if not config.should_activate(payload):
            log.info(
                "Notification rule condition not met, skipping dispatch",
                event_type=event.value,
                rule_id=config.rule_id,
                condition=config.condition
            )
            async def _domain_only_callback():
                await _emit_domain_event(event, payload)
            return [], _domain_only_callback

    # Step 2: Resolve recipients
    try:
        user_ids = await config.resolver.resolve_users(db, payload)
    except Exception as e:
        log.error(
            "Failed to resolve users for event (still emitting domain event)",
            event_type=event.value,
            error=str(e),
            resolver=config.resolver.__class__.__name__
        )
        async def _domain_only_callback():
            await _emit_domain_event(event, payload)
        return [], _domain_only_callback

    if not user_ids:
        log.info("No recipients resolved for event (still emitting domain event)", event_type=event.value)
        async def _domain_only_callback():
            await _emit_domain_event(event, payload)
        return [], _domain_only_callback

    log.info(
        "Recipients resolved successfully",
        event_type=event.value,
        recipient_count=len(user_ids)
    )

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
                "All recipients filtered out by preferences (still emitting domain event)",
                event_type=event.value,
                group=group.value
            )
            async def _domain_only_callback():
                await _emit_domain_event(event, payload)
            return [], _domain_only_callback

        log.info(
            "Recipients after preference filtering",
            event_type=event.value,
            filtered_count=len(user_ids)
        )

    # Step 4: Apply deduplication
    if dedupe_key:
        original_count = len(user_ids)
        user_ids = await _apply_deduplication(db, user_ids, dedupe_key)

        if not user_ids:
            log.info(
                "All recipients filtered out by deduplication (still emitting domain event)",
                event_type=event.value,
                dedupe_key=dedupe_key
            )
            async def _domain_only_callback():
                await _emit_domain_event(event, payload)
            return [], _domain_only_callback

        log.info(
            "Recipients after deduplication",
            event_type=event.value,
            original_count=original_count,
            deduplicated_count=len(user_ids),
            filtered_out=original_count - len(user_ids)
        )

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
        log.error(
            "Failed to create notifications for event",
            event_type=event.value
        )
        # Return empty with empty callback
        async def _empty_callback():
            pass
        return [], _empty_callback

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback with all post-commit actions
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Notifications committed successfully",
            event_type=event.value,
            notification_count=len(notification_ids),
            notification_type=notification_type
        )

        # Step 7.25: ✅ REAL-TIME SYNC: Emit domain event for UI refresh
        # This broadcasts to ALL connected clients (separate from per-user notifications)
        await _emit_domain_event(event, payload)

        # Step 7.5: ✅ PHASE 1.2: Prepend new notifications to inbox cache
        await _prepend_to_inbox_cache(user_ids, notification_ids)

        # ✅ NOTIFICATION 2.0 - PHASE 3.1: Parallel Multi-Channel Delivery
        # Step 8: Send notifications through configured channels IN PARALLEL
        try:
            # Fetch notifications from database for channel delivery
            repo = NotificationRepository(db)
            notifications = await repo.get_by_ids(notification_ids)

            if not notifications:
                log.warning(
                    "No notifications found for channel delivery",
                    requested_ids=notification_ids
                )
                return

            # Create parallel tasks for all channels
            channel_tasks = [
                _send_via_channel(
                    channel_name=channel_name,
                    notifications=notifications,
                    recipient_ids=user_ids,
                    context=payload,
                    event=event.value
                )
                for channel_name in config.channel_values
            ]

            # Execute all channel deliveries in parallel
            channel_results = await asyncio.gather(*channel_tasks, return_exceptions=True)

            # Process results and log per-channel statistics
            for result in channel_results:
                if isinstance(result, Exception):
                    log.error(
                        "Unexpected channel delivery exception",
                        event_type=event.value,
                        error=str(result)
                    )
                    continue

                channel_name, channel_result, error_msg = result

                if error_msg:
                    log.error(
                        "Channel delivery failed",
                        event_type=event.value,
                        channel=channel_name,
                        error=error_msg,
                        notification_count=len(notifications)
                    )
                elif channel_result:
                    log.info(
                        "Channel delivery completed",
                        event_type=event.value,
                        channel=channel_name,
                        sent_count=channel_result.sent_count,
                        failed_count=len(channel_result.failed_ids),
                        success=channel_result.success
                    )

                    if channel_result.failed_ids:
                        log.warning(
                            "Some recipients failed for channel",
                            event_type=event.value,
                            channel=channel_name,
                            failed_ids=channel_result.failed_ids[:10],
                            failed_count=len(channel_result.failed_ids)
                        )

        except Exception as e:
            log.error(
                "Channel delivery system failed",
                event_type=event.value,
                error=str(e),
                notification_count=len(notification_ids),
                channels=config.channel_values,
                fallback="Notifications are in DB but delivery failed"
            )

    return notification_ids, _post_commit


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
        repo = NotificationRepository(db)
        existing_user_ids = await repo.get_by_dedupe_key(user_ids, dedupe_key)

        # Return users who don't have the notification yet
        filtered_ids = [uid for uid in user_ids if uid not in existing_user_ids]

        if existing_user_ids:
            log.debug(
                "Deduplication applied",
                dedupe_key=dedupe_key,
                original_count=len(user_ids),
                duplicate_count=len(existing_user_ids),
                remaining_count=len(filtered_ids)
            )

        return filtered_ids

    except Exception as e:
        log.warning(
            "Deduplication check failed, proceeding without deduplication",
            dedupe_key=dedupe_key,
            error=str(e),
            user_count=len(user_ids)
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

    repo = NotificationRepository(db)

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
            # Use repository for bulk insert
            chunk_ids = await repo.bulk_create(values)
            notification_ids.extend(chunk_ids)

            log.debug(
                "Bulk notification insert successful",
                chunk_number=i // BULK_INSERT_CHUNK_SIZE + 1,
                chunk_size=len(chunk_ids),
                notification_type=notification_type
            )

        except Exception as e:
            log.error(
                "Failed to bulk insert notifications chunk",
                chunk_number=i // BULK_INSERT_CHUNK_SIZE + 1,
                chunk_size=len(chunk),
                error=str(e),
                notification_type=notification_type
            )
            # Continue with other chunks

    log.info(
        "Bulk notification creation completed",
        total_created=len(notification_ids),
        total_recipients=len(user_ids),
        notification_type=notification_type
    )

    return notification_ids


async def _emit_notifications_immediate(
    db: AsyncSession,
    notification_ids: List[int]
):
    """
    Emit Socket.IO notifications immediately for real-time delivery.

    This function sends notifications to connected users via Socket.IO
    without waiting for Celery task processing. This ensures users see
    toast notifications instantly.

    Args:
        db: Database session
        notification_ids: List of notification IDs to emit

    Note:
        This function only handles Socket.IO emission. Email delivery
        is still handled by the Celery task for proper queueing.
    """
    if not notification_ids:
        return

    try:
        from app.socket_manager import sio

        # Fetch notifications from database
        result = await db.execute(
            select(models.Notification)
            .where(models.Notification.id.in_(notification_ids))
        )
        notifications = result.scalars().all()

        if not notifications:
            log.warning(
                "No notifications found for immediate Socket.IO emit",
                requested_ids=notification_ids
            )
            return

        # Emit each notification to the user's Socket.IO room
        emitted_count = 0
        failed_count = 0
        for notification in notifications:
            try:
                room_name = f"user_room_{notification.user_id}"
                await sio.emit(
                    "notification",
                    {
                        "id": notification.id,
                        "type": notification.type,
                        "title": notification.title,
                        "message": notification.message,
                        "link": notification.link,
                        "data": notification.data,
                        "created_at": notification.created_at.isoformat()
                        if notification.created_at else None,
                        "is_read": notification.is_read,
                    },
                    room=room_name
                )
                emitted_count += 1
            except Exception as e:
                failed_count += 1
                log.warning(
                    "Failed to emit notification via Socket.IO",
                    notification_id=notification.id,
                    user_id=notification.user_id,
                    room=room_name,
                    error=str(e)
                )

        log.info(
            "Socket.IO immediate emission completed",
            emitted_count=emitted_count,
            failed_count=failed_count,
            total_notifications=len(notifications)
        )

    except Exception as e:
        log.error(
            "Failed to emit immediate Socket.IO notifications",
            error=str(e),
            notification_count=len(notification_ids)
        )
        raise


def _dispatch_broadcast_task(
    notification_ids: List[int],
    channels: List[str],
    event: str
):
    """
    Dispatch Celery task to broadcast notifications.

    This function queues the notification delivery for async processing.
    Email sending happens in the Celery worker. Socket.IO is sent immediately
    before this task is queued (see _emit_notifications_immediate).

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
            "Celery broadcast task queued successfully",
            event=event,
            notification_count=len(notification_ids),
            channels=channels,
            queue="notifications"
        )

    except Exception as e:
        log.error(
            "Failed to queue Celery broadcast task",
            event=event,
            error=str(e),
            notification_count=len(notification_ids)
        )
        raise


async def _prepend_to_inbox_cache(user_ids: List[int], notification_ids: List[int]):
    """
    ✅ PHASE 1.2: Prepend new notification IDs to user inbox caches.

    This keeps cache warm after creating new notifications, avoiding cache miss
    on next read.

    Strategy:
    - For each user, prepend their notification ID(s) to their inbox cache
    - Trim cache to max 100 items
    - Set TTL to 7 days

    Args:
        user_ids: List of user IDs who received notifications
        notification_ids: List of notification IDs that were created (in same order as user_ids)

    Note:
        Bulk notifications create one notification per user in same order as user_ids list.
        We prepend notification_ids[i] to cache for user_ids[i].
    """
    if len(user_ids) != len(notification_ids):
        log.warning(
            "Mismatch between user_ids and notification_ids length, skipping cache prepend",
            user_count=len(user_ids),
            notification_count=len(notification_ids)
        )
        return

    try:
        # Prepend each notification to the corresponding user's inbox cache
        for user_id, notification_id in zip(user_ids, notification_ids):
            cache_key = f"{INBOX_CACHE_KEY_PREFIX}:{user_id}"

            # LPUSH to prepend notification ID to front of list
            await safe_redis_lpush(cache_key, str(notification_id))

            # LTRIM to keep only first 100 items
            await safe_redis_ltrim(cache_key, 0, INBOX_CACHE_MAX_SIZE - 1)

            # Set/refresh TTL
            await safe_redis_expire(cache_key, INBOX_CACHE_TTL)

        log.info(
            "Inbox cache prepend successful",
            user_count=len(user_ids),
            notification_count=len(notification_ids),
            cache_max_size=INBOX_CACHE_MAX_SIZE,
            cache_ttl_seconds=INBOX_CACHE_TTL
        )

    except Exception as e:
        # Log but don't fail - cache prepend is non-critical
        log.warning(
            "Failed to prepend notifications to inbox cache",
            error=str(e),
            user_count=len(user_ids),
            notification_count=len(notification_ids),
            exc_info=True
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def dispatch_to_user(
    db: AsyncSession,
    user_id: int,
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None
) -> Tuple[List[int], Optional[Callable]]:
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
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
    """
    payload["user_id"] = user_id
    return await dispatch(db, event, payload, dedupe_key)


async def dispatch_to_users(
    db: AsyncSession,
    user_ids: List[int],
    event: SystemEvents,
    payload: dict,
    dedupe_key: Optional[str] = None
) -> Tuple[List[int], Optional[Callable]]:
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
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
    """
    payload["user_ids"] = user_ids
    return await dispatch(db, event, payload, dedupe_key)


async def dispatch_system_alert(
    db: AsyncSession,
    severity: str,
    message: str,
    action_url: Optional[str] = None,
    user_ids: Optional[List[int]] = None
) -> Tuple[List[int], Optional[Callable]]:
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
        Tuple of (notification_ids, post_commit_callback)
        Caller is responsible for calling db.commit() then callback().
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
