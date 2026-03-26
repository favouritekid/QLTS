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
from app.core.deps import RequireAdmin
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
    current_admin: models.User = RequireAdmin,
):
    """
    List notification delivery records with filters.
    Admin-only endpoint for delivery visibility.
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
    current_admin: models.User = RequireAdmin,
):
    """Aggregate delivery stats (counts by status and channel)."""
    repo = NotificationDeliveryRepository(db)
    stats = await repo.get_aggregate_stats(
        date_from=date_from, date_to=date_to, event=event, channel=channel,
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
    current_admin: models.User = RequireAdmin,
):
    """Failure analytics — grouped by error reason."""
    repo = NotificationDeliveryRepository(db)
    summary = await repo.get_failure_summary(
        date_from=date_from, date_to=date_to, channel=channel, limit=limit,
    )
    return summary


@limiter.limit(RateLimits.DATA_READ)
@router.get("/{delivery_id}", response_model=schemas.NotificationDeliveryResponse)
async def get_delivery(
    request: Request,
    delivery_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = RequireAdmin,
):
    """Get a single delivery record by ID."""
    repo = NotificationDeliveryRepository(db)
    record = await repo.get_by_id(delivery_id)
    if not record:
        raise HTTPException(status_code=404, detail="Delivery record not found")
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
@router.post("/{delivery_id}/replay", response_model=schemas.ReplayResponse)
async def replay_delivery(
    request: Request,
    delivery_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = RequireAdmin,
):
    """
    Replay a failed/dead-lettered/skipped delivery.

    Resets status to queued and enqueues to Celery worker.
    """
    from app.services import notification_delivery_service
    from app.tasks.delivery_tasks import execute_notification_delivery

    success, message = await notification_delivery_service.replay_delivery(db, delivery_id)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    await db.commit()

    # Enqueue to worker
    execute_notification_delivery.apply_async(args=[delivery_id])

    log.info("Delivery replayed", delivery_id=delivery_id, admin_id=current_admin.id)
    return schemas.ReplayResponse(
        replayed=True,
        delivery_id=delivery_id,
        message="Delivery replayed and enqueued",
    )
