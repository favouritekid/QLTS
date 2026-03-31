# app/services/notification_delivery_ops_service.py
"""
Service layer for Notification Delivery Ops (read analytics + replay).

Provides the business-logic bridge between delivery ops router and repositories.
No FastAPI imports — raises domain exceptions only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
from app.utils.exceptions import BusinessRuleViolation

log = structlog.get_logger(__name__)


# =============================================================================
# Read / Analytics
# =============================================================================

async def list_deliveries(
    db: AsyncSession,
    *,
    event: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 50,
    allowed_user_ids: Optional[List[int]] = None,
    allowed_unit_ids: Optional[List[int]] = None,
    officer_id: Optional[int] = None,
) -> Tuple[list, int]:
    """List deliveries with scope filtering. Returns (records, total)."""
    repo = NotificationDeliveryRepository(db)
    return await repo.list_deliveries(
        event=event, channel=channel, status=status,
        user_id=user_id, source_type=source_type, source_id=source_id,
        date_from=date_from, date_to=date_to,
        skip=skip, limit=limit,
        allowed_user_ids=allowed_user_ids,
        allowed_unit_ids=allowed_unit_ids,
        officer_id=officer_id,
    )


async def get_aggregate_stats(
    db: AsyncSession,
    *,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    event: Optional[str] = None,
    channel: Optional[str] = None,
    allowed_user_ids: Optional[List[int]] = None,
    allowed_unit_ids: Optional[List[int]] = None,
    officer_id: Optional[int] = None,
) -> Any:
    """Aggregate delivery stats scoped by role."""
    repo = NotificationDeliveryRepository(db)
    return await repo.get_aggregate_stats(
        date_from=date_from, date_to=date_to, event=event, channel=channel,
        allowed_user_ids=allowed_user_ids,
        allowed_unit_ids=allowed_unit_ids,
        officer_id=officer_id,
    )


async def get_failure_summary(
    db: AsyncSession,
    *,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    channel: Optional[str] = None,
    limit: int = 20,
    allowed_user_ids: Optional[List[int]] = None,
    allowed_unit_ids: Optional[List[int]] = None,
    officer_id: Optional[int] = None,
) -> Any:
    """Failure analytics scoped by role."""
    repo = NotificationDeliveryRepository(db)
    return await repo.get_failure_summary(
        date_from=date_from, date_to=date_to, channel=channel, limit=limit,
        allowed_user_ids=allowed_user_ids,
        allowed_unit_ids=allowed_unit_ids,
        officer_id=officer_id,
    )


async def get_time_series(
    db: AsyncSession,
    *,
    interval: str = "hour",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    channel: Optional[str] = None,
    allowed_user_ids: Optional[List[int]] = None,
    allowed_unit_ids: Optional[List[int]] = None,
    officer_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Time series delivery counts."""
    repo = NotificationDeliveryRepository(db)
    return await repo.get_time_series(
        interval=interval, date_from=date_from, date_to=date_to, channel=channel,
        allowed_user_ids=allowed_user_ids,
        allowed_unit_ids=allowed_unit_ids,
        officer_id=officer_id,
    )


async def get_top_events(
    db: AsyncSession,
    *,
    limit: int = 10,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    allowed_user_ids: Optional[List[int]] = None,
    allowed_unit_ids: Optional[List[int]] = None,
    officer_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Top events by volume."""
    repo = NotificationDeliveryRepository(db)
    return await repo.get_top_events(
        limit=limit, date_from=date_from, date_to=date_to,
        allowed_user_ids=allowed_user_ids,
        allowed_unit_ids=allowed_unit_ids,
        officer_id=officer_id,
    )


async def get_latency_stats(
    db: AsyncSession,
    *,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Any:
    """Processing latency P50/P95."""
    repo = NotificationDeliveryRepository(db)
    return await repo.get_processing_latency_stats(
        date_from=date_from, date_to=date_to,
    )


# =============================================================================
# Replay
# =============================================================================

async def replay_and_enqueue(
    db: AsyncSession,
    delivery_id: int,
) -> Tuple[bool, str]:
    """
    Replay a failed/dead-lettered/skipped delivery and enqueue to worker.

    Returns (success, message). Caller must call db.commit() on success.
    Raises BusinessRuleViolation if delivery is not eligible for replay.
    Raises BusinessRuleViolation if Celery enqueue fails.
    """
    from app.services import notification_delivery_service

    success, message = await notification_delivery_service.replay_delivery(db, delivery_id)
    if not success:
        raise BusinessRuleViolation(message)

    return success, message


def enqueue_delivery_task(delivery_id: int) -> None:
    """
    Enqueue delivery to Celery worker.

    Raises BusinessRuleViolation if enqueue fails so the router can handle
    it as a domain error rather than raising HTTPException directly.
    """
    from app.tasks.delivery_tasks import execute_notification_delivery

    try:
        execute_notification_delivery.apply_async(args=[delivery_id])
    except Exception as e:
        log.error("Failed to enqueue replay task", delivery_id=delivery_id, error=str(e))
        raise BusinessRuleViolation(f"Delivery replayed but failed to enqueue: {e}")
