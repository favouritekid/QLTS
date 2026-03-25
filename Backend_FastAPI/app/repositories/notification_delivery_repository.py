# app/repositories/notification_delivery_repository.py
"""
Repository for NotificationDelivery — per-channel delivery tracking.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import NotificationDelivery
from app.repositories.base import BaseRepository


class NotificationDeliveryRepository(BaseRepository[NotificationDelivery]):

    def __init__(self, db: AsyncSession):
        super().__init__(db, NotificationDelivery)

    async def get_filtered(
        self, skip: int = 0, limit: int = 100, **filters
    ) -> Tuple[List[NotificationDelivery], int]:
        """Required by BaseRepository. Delegates to list_deliveries."""
        records, total = await self.list_deliveries(skip=skip, limit=limit, **filters)
        return total, records

    async def create_delivery(self, **kwargs) -> NotificationDelivery:
        """Create a single delivery record."""
        delivery = NotificationDelivery(**kwargs)
        self.db.add(delivery)
        await self.db.flush()
        await self.db.refresh(delivery)
        return delivery

    async def bulk_create_deliveries(
        self, deliveries_data: List[Dict[str, Any]]
    ) -> List[int]:
        """Bulk insert delivery records. Returns list of IDs."""
        if not deliveries_data:
            return []

        objects = [NotificationDelivery(**d) for d in deliveries_data]
        self.db.add_all(objects)
        await self.db.flush()
        return [obj.id for obj in objects]

    async def update_status(
        self,
        delivery_id: int,
        status: str,
        error_reason: str | None = None,
        sent_at: datetime | None = None,
    ) -> Optional[NotificationDelivery]:
        """Update delivery status."""
        delivery = await self.get_by_id(delivery_id)
        if not delivery:
            return None

        delivery.status = status
        if error_reason is not None:
            delivery.error_reason = error_reason
        if sent_at is not None:
            delivery.sent_at = sent_at
        elif status == "sent" and delivery.sent_at is None:
            delivery.sent_at = datetime.now(timezone.utc)

        await self.db.flush()
        return delivery

    async def get_by_notification_id(
        self, notification_id: int
    ) -> List[NotificationDelivery]:
        """Get all delivery records for a notification."""
        result = await self.db.execute(
            select(NotificationDelivery)
            .where(NotificationDelivery.notification_id == notification_id)
            .order_by(NotificationDelivery.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_deliveries(
        self,
        event: str | None = None,
        channel: str | None = None,
        status: str | None = None,
        user_id: int | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[NotificationDelivery], int]:
        """List deliveries with filters. Returns (records, total_count)."""
        conditions = []

        if event:
            conditions.append(NotificationDelivery.event == event)
        if channel:
            conditions.append(NotificationDelivery.channel == channel)
        if status:
            conditions.append(NotificationDelivery.status == status)
        if user_id is not None:
            conditions.append(NotificationDelivery.user_id == user_id)
        if source_type:
            conditions.append(NotificationDelivery.source_type == source_type)
        if source_id is not None:
            conditions.append(NotificationDelivery.source_id == source_id)
        if date_from:
            conditions.append(NotificationDelivery.created_at >= date_from)
        if date_to:
            conditions.append(NotificationDelivery.created_at <= date_to)

        where = and_(*conditions) if conditions else True

        # Count
        count_q = select(func.count()).select_from(NotificationDelivery).where(where)
        total = (await self.db.execute(count_q)).scalar() or 0

        # Query
        query = (
            select(NotificationDelivery)
            .where(where)
            .order_by(NotificationDelivery.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        records = list(result.scalars().all())

        return records, total
