# app/services/notification_delivery_service.py
"""
Notification Delivery Service — manages delivery lifecycle.

Separates delivery tracking from dispatcher to keep dispatcher focused
on routing logic, while this service handles persistence + status transitions.
"""
import structlog
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

log = structlog.get_logger(__name__)


async def create_deliveries_for_dispatch(
    db: AsyncSession,
    event: str,
    channel_recipient_map: Dict[str, List[int]],
    notification_id_map: Dict[int, int],
    dedupe_key: str | None = None,
    payload_snapshot: dict | None = None,
) -> List[int]:
    """
    Create NotificationDelivery rows for a dispatch.

    Args:
        db: Database session
        event: SystemEvents.value
        channel_recipient_map: {channel: [user_ids]} from dispatcher
        notification_id_map: {user_id: notification_id} for linking
        dedupe_key: Optional dedup key
        payload_snapshot: Rendered content snapshot

    Returns:
        List of delivery IDs created
    """
    repo = NotificationDeliveryRepository(db)
    deliveries_data = []

    for channel, user_ids in channel_recipient_map.items():
        for user_id in user_ids:
            notification_id = notification_id_map.get(user_id)
            deliveries_data.append({
                "notification_id": notification_id,
                "event": event,
                "channel": channel,
                "recipient_kind": "internal",
                "user_id": user_id,
                "status": "queued",
                "dedupe_key": dedupe_key,
                "payload_snapshot": payload_snapshot,
            })

    if not deliveries_data:
        return []

    delivery_ids = await repo.bulk_create_deliveries(deliveries_data)

    log.info(
        "Delivery records created",
        notification_event=event,
        delivery_count=len(delivery_ids),
        channels={ch: len(ids) for ch, ids in channel_recipient_map.items()},
    )

    return delivery_ids


async def mark_channel_sent(
    db: AsyncSession,
    event: str,
    channel: str,
    user_ids: List[int],
    sent_at: datetime | None = None,
) -> int:
    """Mark deliveries as sent for a channel+user_ids batch."""
    repo = NotificationDeliveryRepository(db)
    updated = 0

    # Find matching queued deliveries
    records, _ = await repo.list_deliveries(
        event=event, channel=channel, status="queued", limit=1000
    )

    user_set = set(user_ids)
    for record in records:
        if record.user_id in user_set:
            await repo.update_status(
                record.id, "sent",
                sent_at=sent_at or datetime.now(timezone.utc),
            )
            updated += 1

    return updated


async def mark_channel_failed(
    db: AsyncSession,
    event: str,
    channel: str,
    user_ids: List[int],
    error_reason: str = "",
) -> int:
    """Mark deliveries as failed for a channel+user_ids batch."""
    repo = NotificationDeliveryRepository(db)
    updated = 0

    records, _ = await repo.list_deliveries(
        event=event, channel=channel, status="queued", limit=1000
    )

    user_set = set(user_ids)
    for record in records:
        if record.user_id in user_set:
            await repo.update_status(record.id, "failed", error_reason=error_reason)
            updated += 1

    return updated


async def mark_channel_skipped(
    db: AsyncSession,
    event: str,
    channel: str,
    user_ids: List[int],
    error_reason: str = "channel_not_live",
) -> int:
    """Mark deliveries as skipped (channel not implemented, etc)."""
    repo = NotificationDeliveryRepository(db)
    updated = 0

    records, _ = await repo.list_deliveries(
        event=event, channel=channel, status="queued", limit=1000
    )

    user_set = set(user_ids)
    for record in records:
        if record.user_id in user_set:
            await repo.update_status(record.id, "skipped", error_reason=error_reason)
            updated += 1

    return updated
