# app/services/notification_service.py
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.database import (
    safe_redis_lpush,
    safe_redis_ltrim,
    safe_redis_lrange,
    safe_redis_expire,
    safe_redis_delete,
)
from app.repositories import NotificationRepository
from app.services import notification_preference_service
from app.services.email_service import EmailService

log = structlog.get_logger(__name__)

# ✅ PHASE 1.2.1: Redis inbox cache configuration
INBOX_CACHE_KEY_PREFIX = "user_inbox"  # Cache key: user_inbox:{user_id}
INBOX_CACHE_MAX_SIZE = 100  # Max 100 notifications in cache
INBOX_CACHE_TTL = 7 * 24 * 60 * 60  # 7 days in seconds


# ✅ PHASE 1.2.3: Cache invalidation helper
async def invalidate_user_inbox_cache(user_id: int):
    """
    Invalidate user's notification inbox cache.

    Called when:
    - Notification is deleted
    - Any operation that changes the notification list order/content

    Note: Mark as read/unread does NOT invalidate cache since cache only stores IDs,
    not the full notification data.
    """
    cache_key = f"{INBOX_CACHE_KEY_PREFIX}:{user_id}"
    await safe_redis_delete(cache_key)
    log.info(
        "Notification inbox cache invalidated",
        user_id=user_id,
        cache_key=cache_key
    )


async def create_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    notification_type: str = "info",
    link: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Tuple[models.Notification, Callable]:
    """
    Create a new notification for a user with preference checking.

    This function:
    1. Checks user's notification preferences
    2. Creates the notification in the database (if preferences allow)
    3. Sends an email notification (if preferences allow)

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        user_id: ID of the user to notify
        title: Notification title
        message: Notification message
        notification_type: Type of notification (info, success, warning, error, admin_update, system)
        link: Optional link to navigate to
        data: Optional additional data

    Returns:
        Tuple of (notification, post_commit_callback)

    .. deprecated::
        Use dispatch() or safe_dispatch() from notification_dispatcher instead.
        This function bypasses the per-channel preference filtering and
        multi-channel delivery pipeline.
    """
    import warnings
    warnings.warn(
        "create_notification() is deprecated. "
        "Use dispatch() or safe_dispatch() from notification_dispatcher instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    log.warning(
        "DEPRECATED: create_notification() called directly — migrate to dispatcher",
        user_id=user_id,
        notification_type=notification_type,
        title=title[:50],
    )
    # Check user preferences
    should_send = await notification_preference_service.should_send_notification(
        db, user_id, notification_type
    )

    log.info(
        "Notification preference check completed",
        user_id=user_id,
        notification_type=notification_type,
        send_email=should_send["send_email"],
        create_notification=should_send["create_notification"]
    )

    # Always create the notification in the database
    # Preferences only control delivery channels (email, sound, browser)
    repo = NotificationRepository(db)
    notification = await repo.create({
        "user_id": user_id,
        "type": notification_type,
        "title": title,
        "message": message,
        "link": link,
        "data": data,
    })

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # Send email if preferences allow
        if should_send["send_email"]:
            try:
                # Get user info for email
                # Use repository for user if possible, but here we just need user.email
                # We can keep db.get(models.User) or use UserRepository
                from app.repositories import UserRepository
                user_repo = UserRepository(db)
                user = await user_repo.get_by_id(user_id)
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
                            user_id=user_id,
                            notification_id=notification.id,
                            notification_type=notification_type,
                            recipient_email=user.email
                        )
                    else:
                        log.warning(
                            "Failed to send email notification",
                            user_id=user_id,
                            notification_id=notification.id,
                            notification_type=notification_type,
                            recipient_email=user.email
                        )
            except Exception as e:
                log.error(
                    "Error sending email notification",
                    user_id=user_id,
                    notification_id=notification.id,
                    notification_type=notification_type,
                    error=str(e)
                )

    return notification, _post_commit


async def get_user_notifications(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 50,
    unread_only: bool = False,
) -> Tuple[int, int, List[models.Notification]]:
    """
    Get notifications for a user with Redis inbox caching.

    ✅ PHASE 1.2.2: Cache-first read pattern
    - Cache hit: Fetch notification IDs from Redis, then hydrate from DB
    - Cache miss: Query DB, populate cache with LPUSH + LTRIM

    Benefits:
    - Reduces DB load for frequent notification checks
    - P95 latency < 500ms (vs 1-2s without cache)
    - Memory usage: ~100KB per user (100 notification IDs)

    Returns:
        Tuple of (total_count, unread_count, notifications list)
    """
    # Always count from DB (counts are lightweight queries)
    # ✅ Counts not cached to avoid staleness issues
    repo = NotificationRepository(db)
    total_count = await repo.get_total_count(user_id)
    unread_count = await repo.get_unread_count(user_id)

    # ✅ PHASE 1.2.2: Try cache first (only for non-filtered queries)
    notifications = []
    if not unread_only:
        cache_key = f"{INBOX_CACHE_KEY_PREFIX}:{user_id}"

        # Get notification IDs from cache
        cached_ids = await safe_redis_lrange(cache_key, skip, skip + limit - 1)

        if cached_ids:
            # Cache hit! Fetch notifications by IDs from DB
            log.info(
                "Notification inbox cache HIT",
                user_id=user_id,
                cached_count=len(cached_ids),
                skip=skip,
                limit=limit
            )

            # Convert string IDs to integers
            notification_ids = [int(nid) for nid in cached_ids]

            # Query notifications by IDs (preserve order from cache)
            # Redis KHÔNG được là nguồn chứng minh chủ quyền: khoá
            # ``user_inbox:{user_id}`` có thể chứa ID của người khác (do lỗi
            # ghép cặp ở đường dispatch, do sửa tay, do một khoá cũ còn sót).
            # Ràng buộc ``user_id`` ở đây là hàng rào CUỐI, độc lập với cache.
            notifications_from_db = await repo.get_by_ids(
                notification_ids, owner_user_id=user_id
            )
            notification_dict = {n.id: n for n in notifications_from_db}

            # Preserve cache order
            notifications = [notification_dict[nid] for nid in notification_ids if nid in notification_dict]
        else:
            # Cache miss - query DB and populate cache
            log.info(
                "Notification inbox cache MISS",
                user_id=user_id,
                cache_key=cache_key
            )

            # Fetch max items for cache via repository
            _, all_notifications = await repo.get_filtered(
                user_id=user_id,
                unread_only=False,
                skip=0,
                limit=INBOX_CACHE_MAX_SIZE
            )

            if all_notifications:
                # Populate cache with notification IDs
                notification_ids = [str(n.id) for n in all_notifications]
                await safe_redis_lpush(cache_key, *notification_ids)

                # Trim to max size
                await safe_redis_ltrim(cache_key, 0, INBOX_CACHE_MAX_SIZE - 1)

                # Set TTL
                await safe_redis_expire(cache_key, INBOX_CACHE_TTL)

                log.info(
                    "Notification inbox cache POPULATED",
                    user_id=user_id,
                    notification_count=len(notification_ids),
                    cache_max_size=INBOX_CACHE_MAX_SIZE,
                    cache_ttl_seconds=INBOX_CACHE_TTL
                )

            # Return paginated slice
            notifications = all_notifications[skip:skip + limit]
    else:
        # For filtered queries (unread_only), skip cache and query DB directly via repository
        _, notifications = await repo.get_filtered(
            user_id=user_id,
            unread_only=unread_only,
            skip=skip,
            limit=limit
        )

    return total_count, unread_count, list(notifications)


async def mark_as_read(
    db: AsyncSession,
    user_id: int,
    notification_ids: List[int],
) -> Tuple[int, Callable]:
    """
    Mark notifications as read.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (count, post_commit_callback)
    """
    repo = NotificationRepository(db)
    notifications = await repo.get_unread_for_user(user_id, notification_ids)

    # Mark as read
    from datetime import timezone
    now = datetime.now(timezone.utc)
    for notification in notifications:
        notification.is_read = True
        notification.read_at = now

    # Phase C2: Also mark linked delivery rows as "read"
    marked_notification_ids = [n.id for n in notifications]
    if marked_notification_ids:
        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        from app.services import notification_delivery_service
        delivery_repo = NotificationDeliveryRepository(db)
        for nid in marked_notification_ids:
            linked = await delivery_repo.get_by_notification_id(nid)
            read_ids = [
                d.id for d in linked
                if d.channel == "browser" and d.status in ("sent", "delivered")
            ]
            if read_ids:
                await notification_delivery_service.mark_delivery_ids_read(db, read_ids)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    count = len(notifications)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Notifications marked as read",
            user_id=user_id,
            count=count,
            notification_ids=notification_ids
        )

    return count, _post_commit


async def mark_all_as_read(
    db: AsyncSession,
    user_id: int,
) -> Tuple[int, Callable]:
    """
    Mark all notifications as read for a user.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (count, post_commit_callback)
    """
    # Bulk UPDATE instead of loading all ORM objects (E8 fix)
    from datetime import timezone
    from sqlalchemy import update
    now = datetime.now(timezone.utc)

    # Count first for callback
    repo = NotificationRepository(db)
    count_result = await db.execute(
        select(func.count()).select_from(models.Notification).where(
            models.Notification.user_id == user_id,
            models.Notification.is_read == False,  # noqa: E712
        )
    )
    count = count_result.scalar() or 0

    if count > 0:
        # Bulk update notifications
        await db.execute(
            update(models.Notification)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True, read_at=now)
        )

        # Phase C2: Bulk update linked browser delivery rows to "read"
        from app.models.notification_delivery import NotificationDelivery
        await db.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.notification_id.in_(
                    select(models.Notification.id).where(
                        models.Notification.user_id == user_id,
                        models.Notification.read_at == now,  # just marked
                    )
                ),
                NotificationDelivery.channel == "browser",
                NotificationDelivery.status.in_(["sent", "delivered"]),
            )
            .values(status="read")
        )

    await db.flush()

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "All notifications marked as read",
            user_id=user_id,
            count=count
        )

    return count, _post_commit


async def delete_notification(
    db: AsyncSession,
    user_id: int,
    notification_id: int,
) -> Tuple[bool, Callable]:
    """
    Delete a notification and invalidate cache.

    ✅ PHASE 1.2.3: Cache invalidation on delete

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (success, post_commit_callback)
    """
    repo = NotificationRepository(db)
    notification = await repo.get_for_user_by_id(user_id, notification_id)

    if not notification:
        # Return False with empty callback
        async def _empty_callback():
            pass
        return False, _empty_callback

    await repo.delete(notification)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # ✅ PHASE 1.2.3: Invalidate cache after successful delete
        await invalidate_user_inbox_cache(user_id)
        log.info(
            "Notification deleted and cache invalidated",
            user_id=user_id,
            notification_id=notification_id
        )

    return True, _post_commit


async def bulk_delete_notifications(
    db: AsyncSession,
    user_id: int,
    notification_ids: List[int],
) -> Tuple[int, Callable]:
    """
    Delete multiple notifications at once.

    ✅ TECHNICAL DEBT FIX: Single bulk operation instead of multiple single deletes.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (deleted_count, post_commit_callback)
    """
    if not notification_ids:
        async def _empty_callback():
            pass
        return 0, _empty_callback

    repo = NotificationRepository(db)
    deleted_count = await repo.bulk_delete_for_user(user_id, notification_ids)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        # Invalidate cache after successful bulk delete
        await invalidate_user_inbox_cache(user_id)
        log.info(
            "Bulk notifications deleted and cache invalidated",
            user_id=user_id,
            requested_count=len(notification_ids),
            deleted_count=deleted_count
        )

    return deleted_count, _post_commit
