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
