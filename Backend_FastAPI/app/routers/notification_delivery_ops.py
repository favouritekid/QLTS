# app/routers/notification_delivery_ops.py
"""
Notification Delivery Ops API — admin read-only access to delivery records.

Provides visibility into notification delivery status per channel.
"""
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import RequireAdmin, get_delivery_scope_filter, get_delivery_for_user, DeliveryScopeFilter
from app.core.rate_limits import limiter, RateLimits
from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

log = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/notification-deliveries",
    tags=["Notification Delivery Ops"],
)


@limiter.limit(RateLimits.DATA_READ)
@router.get("", response_model=schemas.NotificationDeliveriesPage)
async def list_deliveries(
    request: Request,
    event: Optional[str] = Query(None, description="Filter by event name"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    status: Optional[str] = Query(None, description="Filter by status"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    source_id: Optional[int] = Query(None, description="Filter by source ID"),
    date_from: Optional[datetime] = Query(None, description="From date"),
    date_to: Optional[datetime] = Query(None, description="To date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(database.get_db),
    scope: DeliveryScopeFilter = Depends(get_delivery_scope_filter),
):
    """
    List notification delivery records with filters.
    D4: Scoped by user role (admin=all, manager=unit, officer=self).
    """
    repo = NotificationDeliveryRepository(db)
    skip = (page - 1) * page_size

    records, total = await repo.list_deliveries(
        event=event,
        channel=channel,
        status=status,
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=page_size,
        allowed_user_ids=scope.allowed_user_ids,
    )

    return schemas.NotificationDeliveriesPage(
        total_count=total,
        deliveries=[
            schemas.NotificationDeliveryResponse.model_validate(r)
            for r in records
        ],
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get("/stats", response_model=schemas.DeliveryStatsResponse)
async def get_delivery_stats(
    request: Request,
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    event: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    db: AsyncSession = Depends(database.get_db),
    scope: DeliveryScopeFilter = Depends(get_delivery_scope_filter),
):
    """Aggregate delivery stats. D4: scoped by role."""
    repo = NotificationDeliveryRepository(db)
    stats = await repo.get_aggregate_stats(
        date_from=date_from, date_to=date_to, event=event, channel=channel,
        allowed_user_ids=scope.allowed_user_ids,
    )
    return stats


@limiter.limit(RateLimits.DATA_READ)
@router.get("/failures", response_model=schemas.DeliveryFailureSummary)
async def get_delivery_failures(
    request: Request,
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    channel: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(database.get_db),
    scope: DeliveryScopeFilter = Depends(get_delivery_scope_filter),
):
    """Failure analytics. D4: scoped by role."""
    repo = NotificationDeliveryRepository(db)
    summary = await repo.get_failure_summary(
        date_from=date_from, date_to=date_to, channel=channel, limit=limit,
        allowed_user_ids=scope.allowed_user_ids,
    )
    return summary


# --- D5: Dashboard analytics endpoints ---

@limiter.limit(RateLimits.DATA_READ)
@router.get("/stats/time-series", response_model=schemas.TimeSeriesResponse)
async def get_time_series(request: Request, interval: str = Query("hour", pattern="^(hour|day)$"),
    date_from: Optional[datetime] = Query(None), date_to: Optional[datetime] = Query(None),
    channel: Optional[str] = Query(None), db: AsyncSession = Depends(database.get_db),
    scope: DeliveryScopeFilter = Depends(get_delivery_scope_filter)):
    """Time series delivery counts."""
    repo = NotificationDeliveryRepository(db)
    buckets = await repo.get_time_series(interval=interval, date_from=date_from, date_to=date_to, channel=channel, allowed_user_ids=scope.allowed_user_ids)
    return schemas.TimeSeriesResponse(interval=interval, buckets=[schemas.TimeSeriesBucket(**b) for b in buckets])

@limiter.limit(RateLimits.DATA_READ)
@router.get("/stats/top-events", response_model=schemas.TopEventsResponse)
async def get_top_events(request: Request, limit: int = Query(10, ge=1, le=50),
    date_from: Optional[datetime] = Query(None), date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(database.get_db), scope: DeliveryScopeFilter = Depends(get_delivery_scope_filter)):
    """Top events by volume."""
    repo = NotificationDeliveryRepository(db)
    events = await repo.get_top_events(limit=limit, date_from=date_from, date_to=date_to, allowed_user_ids=scope.allowed_user_ids)
    return schemas.TopEventsResponse(events=[schemas.TopEventStats(**e) for e in events])

@limiter.limit(RateLimits.DATA_READ)
@router.get("/stats/latency", response_model=schemas.LatencyStats)
async def get_latency_stats(request: Request, date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None), db: AsyncSession = Depends(database.get_db),
    _: models.User = RequireAdmin):
    """Processing latency P50/P95. Admin-only."""
    repo = NotificationDeliveryRepository(db)
    return await repo.get_processing_latency_stats(date_from=date_from, date_to=date_to)

@limiter.limit(RateLimits.DATA_READ)
@router.get("/health", response_model=schemas.HealthSummaryResponse)
async def get_health_summary(request: Request, db: AsyncSession = Depends(database.get_db),
    _: models.User = RequireAdmin):
    """Combined health: quota + breaker + backlog + failure rate. Admin-only."""
    from app.services.notification_circuit_breaker import get_all_breaker_states
    from app.services import notification_quota_service
    repo = NotificationDeliveryRepository(db)
    breaker_states = get_all_breaker_states()
    breaker_map = {s["channel"]: s["state"] for s in breaker_states}
    quota_summary = await notification_quota_service.get_quota_summary(db)
    quota_map = {q["channel"]: q for q in quota_summary}
    channels = []
    for ch in ("browser", "email", "zalo", "sms"):
        item = {"channel": ch, "breaker_state": breaker_map.get(ch, "closed")}
        if ch in quota_map:
            item["quota_used"] = quota_map[ch]["quota_used"]
            item["quota_limit"] = quota_map[ch]["quota_limit"]
            item["quota_blocked"] = quota_map[ch]["blocked"]
        channels.append(item)
    backlog = await repo.get_queued_backlog_count()
    failure_rate = await repo.get_failure_rate(minutes=30)
    alerts_active = sum(1 for s in breaker_states if s["state"] == "open")
    return schemas.HealthSummaryResponse(channels=[schemas.ChannelHealthItem(**c) for c in channels],
        total_queued=backlog, failure_rate_30m=failure_rate, alerts_active=alerts_active)

@limiter.limit(RateLimits.DATA_READ)
@router.get("/{delivery_id}", response_model=schemas.NotificationDeliveryResponse)
async def get_delivery(
    request: Request,
    record=Depends(get_delivery_for_user),
):
    """Get a single delivery record by ID. D4: IDOR-scoped."""
    return schemas.NotificationDeliveryResponse.model_validate(record)


@limiter.limit(RateLimits.DATA_READ)
@router.get("/quotas", response_model=schemas.QuotaListResponse)
async def get_quotas(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = RequireAdmin,
):
    """Get quota summary for all channels (today). Admin-only."""
    from app.services import notification_quota_service

    summary = await notification_quota_service.get_quota_summary(db)
    return schemas.QuotaListResponse(
        quotas=[schemas.QuotaResponse(**q) for q in summary],
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get("/circuit-breakers", response_model=schemas.CircuitBreakerListResponse)
async def get_circuit_breakers(
    request: Request,
    current_admin: models.User = RequireAdmin,
):
    """Get circuit breaker states for all channels. Admin-only."""
    from app.services.notification_circuit_breaker import get_all_breaker_states

    states = get_all_breaker_states()
    return schemas.CircuitBreakerListResponse(
        breakers=[schemas.CircuitBreakerState(**s) for s in states],
    )


@limiter.limit(RateLimits.DATA_READ)
@router.post("/circuit-breakers/{channel}/reset")
async def reset_circuit_breaker(
    request: Request,
    channel: str,
    current_admin: models.User = RequireAdmin,
):
    """Manually reset a channel's circuit breaker. Admin-only."""
    from app.services.notification_circuit_breaker import reset_breaker

    await reset_breaker(channel)
    log.info("Circuit breaker reset by admin", channel=channel, admin_id=current_admin.id)
    return {"channel": channel, "state": "closed", "message": f"Breaker for {channel} reset"}


@limiter.limit(RateLimits.DATA_READ)
@router.post("/{delivery_id}/replay", response_model=schemas.ReplayResponse)
async def replay_delivery(
    request: Request,
    delivery_id: int,
    db: AsyncSession = Depends(database.get_db),
    record=Depends(get_delivery_for_user),
):
    """
    Replay a failed/dead-lettered/skipped delivery.
    D4: IDOR-scoped — user can only replay deliveries they can see.
    """
    from app.services import notification_delivery_service
    from app.tasks.delivery_tasks import execute_notification_delivery

    success, message = await notification_delivery_service.replay_delivery(db, delivery_id)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    await db.commit()

    # Enqueue to worker
    execute_notification_delivery.apply_async(args=[delivery_id])

    log.info("Delivery replayed", delivery_id=delivery_id)
    return schemas.ReplayResponse(
        replayed=True,
        delivery_id=delivery_id,
        message="Delivery replayed and enqueued",
    )
