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


def build_payload_snapshot(
    title: str,
    message: str,
    link: str | None = None,
    extra: dict | None = None,
) -> dict:
    """
    Build a frozen payload snapshot for delivery records.

    This captures the rendered content at send time so delivery records
    remain interpretable even if templates change later.
    """
    snapshot = {"title": title, "message": message}
    if link:
        snapshot["link"] = link
    if extra:
        snapshot["extra"] = extra
    return snapshot


async def prepare_external_deliveries(
    db: AsyncSession,
    event: str,
    channel: str,
    recipients: list,
    dedupe_key: str | None = None,
    payload_snapshot: dict | None = None,
    rule_id: int | None = None,
    action_step: int | None = None,
    template_code: str | None = None,
    scheduled_for: "datetime | None" = None,
) -> List[int]:
    """
    Create NotificationDelivery rows for external (non-user) recipients.

    Each recipient dict must have at least:
      - source_type, source_id
      - destination (email or phone)
    Optional: normalized_phone, normalized_email

    Phase C1/P2: accepts rule_id, action_step, template_code, scheduled_for
    for parity with internal delivery metadata.

    Returns list of delivery IDs created.
    """
    repo = NotificationDeliveryRepository(db)
    deliveries_data = []

    for r in recipients:
        deliveries_data.append({
            "event": event,
            "channel": channel,
            "recipient_kind": "external",
            "user_id": None,
            "notification_id": None,
            "source_type": r.get("source_type"),
            "source_id": r.get("source_id"),
            "destination": r.get("destination"),
            "status": "queued",
            "dedupe_key": dedupe_key,
            "payload_snapshot": payload_snapshot,
            "rule_id": rule_id,
            "action_step": action_step,
            "template_code": template_code,
            "scheduled_for": scheduled_for,
        })

    if not deliveries_data:
        return []

    delivery_ids = await repo.bulk_create_deliveries(deliveries_data)

    log.info(
        "External delivery records created",
        notification_event=event,
        channel=channel,
        delivery_count=len(delivery_ids),
    )

    return delivery_ids


async def create_deliveries_for_dispatch(
    db: AsyncSession,
    event: str,
    channel_recipient_map: Dict[str, List[int]],
    notification_id_map: Dict[int, int],
    dedupe_key: str | None = None,
    payload_snapshot: dict | None = None,
    channel_snapshot_map: Dict[str, dict] | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
    rule_id: int | None = None,
    channel_step_map: Dict[str, int] | None = None,
    channel_template_map: Dict[str, str | None] | None = None,
    action_delay_map: Dict[str, int] | None = None,
) -> Dict[str, List[int]]:
    """
    Create NotificationDelivery rows for a dispatch.

    Args:
        db: Database session
        event: SystemEvents.value
        channel_recipient_map: {channel: [user_ids]} from dispatcher
        notification_id_map: {user_id: notification_id} for linking
        dedupe_key: Optional dedup key
        payload_snapshot: Default rendered content snapshot (fallback)
        channel_snapshot_map: Phase C1/G2 — per-channel snapshot with channel-specific config
            e.g. {"zalo": {title, message, link, zalo_template_id, zalo_template_data}}
        source_type: Business entity type (lead, admission_profile, etc.)
        source_id: Business entity ID
        rule_id: Phase C0 — FK to notification_rule that triggered this dispatch
        channel_step_map: Phase C0 — {channel: action_step} from action configs
        channel_template_map: Phase C0 — {channel: template_code} from action configs
        action_delay_map: Phase C1 — {channel: delay_minutes} for scheduling

    Returns:
        Dict mapping channel -> list of delivery IDs created for that channel.
        Example: {"browser": [1, 2], "email": [3]}
    """
    from datetime import timedelta

    repo = NotificationDeliveryRepository(db)
    _step_map = channel_step_map or {}
    _template_map = channel_template_map or {}
    _delay_map = action_delay_map or {}
    _snapshot_map = channel_snapshot_map or {}

    now = datetime.now(timezone.utc)

    # Build all delivery rows, tracking which indices belong to which channel
    deliveries_data: List[Dict[str, Any]] = []
    channel_ranges: Dict[str, tuple] = {}  # channel -> (start_idx, count)

    for channel, user_ids in channel_recipient_map.items():
        start = len(deliveries_data)
        delay_minutes = _delay_map.get(channel, 0)
        scheduled_for = (now + timedelta(minutes=delay_minutes)) if delay_minutes > 0 else None
        # Use per-channel snapshot if available, else fallback to base
        ch_snapshot = _snapshot_map.get(channel, payload_snapshot)

        for user_id in user_ids:
            notification_id = notification_id_map.get(user_id)
            deliveries_data.append({
                "notification_id": notification_id,
                "event": event,
                "channel": channel,
                "recipient_kind": "internal",
                "user_id": user_id,
                "source_type": source_type,
                "source_id": source_id,
                "status": "queued",
                "dedupe_key": dedupe_key,
                "payload_snapshot": ch_snapshot,
                "rule_id": rule_id,
                "action_step": _step_map.get(channel),
                "template_code": _template_map.get(channel),
                "scheduled_for": scheduled_for,
            })
        channel_ranges[channel] = (start, len(user_ids))

    if not deliveries_data:
        return {}

    all_ids = await repo.bulk_create_deliveries(deliveries_data)

    # Slice IDs back into per-channel buckets
    channel_delivery_ids: Dict[str, List[int]] = {}
    for channel, (start, count) in channel_ranges.items():
        channel_delivery_ids[channel] = all_ids[start:start + count]

    log.info(
        "Delivery records created",
        notification_event=event,
        delivery_count=len(all_ids),
        channels={ch: len(ids) for ch, ids in channel_delivery_ids.items()},
    )

    return channel_delivery_ids


async def mark_delivery_ids_sent(
    db: AsyncSession,
    delivery_ids: List[int],
    sent_at: datetime | None = None,
) -> int:
    """Mark specific delivery IDs as sent. Scoped to exact IDs."""
    repo = NotificationDeliveryRepository(db)
    return await repo.bulk_update_status(
        delivery_ids, "sent",
        sent_at=sent_at or datetime.now(timezone.utc),
    )


async def mark_delivery_ids_failed(
    db: AsyncSession,
    delivery_ids: List[int],
    error_reason: str = "",
) -> int:
    """Mark specific delivery IDs as failed. Scoped to exact IDs."""
    repo = NotificationDeliveryRepository(db)
    return await repo.bulk_update_status(
        delivery_ids, "failed", error_reason=error_reason,
    )


async def mark_delivery_ids_skipped(
    db: AsyncSession,
    delivery_ids: List[int],
    error_reason: str = "channel_not_live",
) -> int:
    """Mark specific delivery IDs as skipped. Scoped to exact IDs."""
    repo = NotificationDeliveryRepository(db)
    return await repo.bulk_update_status(
        delivery_ids, "skipped", error_reason=error_reason,
    )


# ============================================================
# Phase C2: Retry + dead-letter lifecycle
# ============================================================

async def mark_for_retry(
    db: AsyncSession,
    delivery_id: int,
    next_retry_at: "datetime",
    error_reason: str = "",
    increment_attempt: bool = False,
) -> int:
    """
    Mark delivery as failed with a scheduled retry.

    Sets status=failed, next_retry_at, sets last_attempt_at.
    Only increments attempt_count if increment_attempt=True.
    The sweep_retry_deliveries task will pick this up when next_retry_at <= now().

    Note: The worker task (execute_notification_delivery) increments attempt_count
    before channel execution. Pre-execution deferrals (quota_exhausted,
    circuit_breaker_open) and post-execution failures should NOT increment again.
    Use increment_attempt=True only for callers that haven't already incremented.
    """
    from app.models.notification_delivery import NotificationDelivery
    delivery = await db.get(NotificationDelivery, delivery_id)
    if not delivery:
        return 0

    delivery.status = "failed"
    delivery.error_reason = error_reason
    delivery.next_retry_at = next_retry_at
    if increment_attempt:
        delivery.attempt_count = (delivery.attempt_count or 0) + 1
    delivery.last_attempt_at = datetime.now(timezone.utc)
    await db.flush()
    return 1


async def replay_delivery(
    db: AsyncSession,
    delivery_id: int,
) -> tuple:
    """
    Replay a failed/dead-lettered/skipped delivery.

    Resets status to queued, clears retry/dead-letter state, enqueues to worker.
    Returns (success: bool, message: str).
    """
    from app.models.notification_delivery import NotificationDelivery

    delivery = await db.get(NotificationDelivery, delivery_id)
    if not delivery:
        return False, "Delivery not found"

    if delivery.status not in ("failed", "dead_lettered", "skipped"):
        return False, f"Cannot replay delivery with status '{delivery.status}'"

    # Re-check eligibility before replay (M10: use local function, no tasks import)
    skip_reason = await check_delivery_eligibility(db, delivery)
    if skip_reason:
        return False, f"Replay blocked: {skip_reason}"

    # Reset delivery state
    delivery.status = "queued"
    delivery.attempt_count = 0
    delivery.next_retry_at = None
    delivery.dead_lettered_at = None
    delivery.error_reason = None
    delivery.last_attempt_at = None
    await db.flush()

    return True, "Delivery replayed"


async def check_delivery_eligibility(session: AsyncSession, delivery) -> str | None:
    """
    Re-check if delivery should proceed (consent + preference).

    Returns skip reason string if delivery should be skipped, None if OK.

    M10: Moved from delivery_tasks.py to avoid import cycle (tasks→service).
    Called by both delivery task and replay_delivery.
    """
    # External recipients: check consent
    if delivery.recipient_kind == "external" and delivery.source_type and delivery.source_id:
        from app.repositories.notification_consent_repository import NotificationConsentRepository
        consent_repo = NotificationConsentRepository(session)
        granted = await consent_repo.is_consent_granted(
            channel=delivery.channel,
            source_type=delivery.source_type,
            source_id=delivery.source_id,
        )
        if not granted:
            return "consent_revoked"

    # Internal recipients: check user preference
    if delivery.recipient_kind == "internal" and delivery.user_id:
        from app.services import notification_preference_service
        from app.core.events import SystemEvents
        from app.core.event_groups import get_event_group

        try:
            event_enum = SystemEvents(delivery.event)
            group = get_event_group(event_enum)
            filtered = await notification_preference_service.filter_users_by_group(
                db=session,
                user_ids=[delivery.user_id],
                group=group.value,
                channel=delivery.channel,
            )
            if delivery.user_id not in filtered:
                return "preference_disabled"
        except ValueError:
            pass

    return None


async def mark_delivery_ids_delivered(
    db: AsyncSession,
    delivery_ids: List[int],
) -> int:
    """Mark deliveries as delivered (provider confirmed receipt)."""
    if not delivery_ids:
        return 0
    repo = NotificationDeliveryRepository(db)
    return await repo.bulk_update_status(delivery_ids, "delivered")


async def mark_delivery_ids_read(
    db: AsyncSession,
    delivery_ids: List[int],
) -> int:
    """Mark deliveries as read (recipient opened/acknowledged)."""
    if not delivery_ids:
        return 0
    repo = NotificationDeliveryRepository(db)
    return await repo.bulk_update_status(delivery_ids, "read")


async def mark_dead_lettered(
    db: AsyncSession,
    delivery_ids: List[int],
    error_reason: str = "max_retries_exceeded",
) -> int:
    """
    Mark deliveries as permanently failed (dead-lettered). No more retries.
    """
    if not delivery_ids:
        return 0
    repo = NotificationDeliveryRepository(db)
    from sqlalchemy import update
    from app.models.notification_delivery import NotificationDelivery
    now = datetime.now(timezone.utc)
    stmt = (
        update(NotificationDelivery)
        .where(NotificationDelivery.id.in_(delivery_ids))
        .values(
            status="dead_lettered",
            error_reason=error_reason,
            dead_lettered_at=now,
            next_retry_at=None,
        )
    )
    result = await db.execute(stmt)
    return result.rowcount


# ============================================================
# Legacy API (kept for backward compatibility with existing tests)
# These delegate to the ID-scoped functions above when possible,
# but fall back to re-query if delivery_ids are not available.
# ============================================================

async def mark_channel_sent(
    db: AsyncSession,
    event: str,
    channel: str,
    user_ids: List[int],
    sent_at: datetime | None = None,
) -> int:
    """Mark deliveries as sent for a channel+user_ids batch (legacy)."""
    delivery_ids = await _resolve_delivery_ids(db, event, channel, user_ids)
    if not delivery_ids:
        return 0
    return await mark_delivery_ids_sent(db, delivery_ids, sent_at=sent_at)


async def mark_channel_failed(
    db: AsyncSession,
    event: str,
    channel: str,
    user_ids: List[int],
    error_reason: str = "",
) -> int:
    """Mark deliveries as failed for a channel+user_ids batch (legacy)."""
    delivery_ids = await _resolve_delivery_ids(db, event, channel, user_ids)
    if not delivery_ids:
        return 0
    return await mark_delivery_ids_failed(db, delivery_ids, error_reason=error_reason)


async def mark_channel_skipped(
    db: AsyncSession,
    event: str,
    channel: str,
    user_ids: List[int],
    error_reason: str = "channel_not_live",
) -> int:
    """Mark deliveries as skipped (legacy)."""
    delivery_ids = await _resolve_delivery_ids(db, event, channel, user_ids)
    if not delivery_ids:
        return 0
    return await mark_delivery_ids_skipped(db, delivery_ids, error_reason=error_reason)


async def _resolve_delivery_ids(
    db: AsyncSession,
    event: str,
    channel: str,
    user_ids: List[int],
) -> List[int]:
    """Resolve delivery IDs from event+channel+user_ids (legacy helper)."""
    repo = NotificationDeliveryRepository(db)
    records, _ = await repo.list_deliveries(
        event=event, channel=channel, status="queued", limit=1000
    )
    user_set = set(user_ids)
    return [r.id for r in records if r.user_id in user_set]
