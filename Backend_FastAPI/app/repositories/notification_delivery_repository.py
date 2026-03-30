# app/repositories/notification_delivery_repository.py
"""
Repository for NotificationDelivery — per-channel delivery tracking.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import NotificationDelivery
from app.repositories.base import BaseRepository


def _build_scope_condition(allowed_user_ids: list[int]):
    """Build scope filter that includes internal rows by user_id AND external rows (user_id IS NULL).

    External deliveries have user_id=NULL and recipient_kind='external'.
    Without this, scoped queries silently drop all external delivery data.
    """
    return or_(
        NotificationDelivery.user_id.in_(allowed_user_ids),
        and_(
            NotificationDelivery.user_id.is_(None),
            NotificationDelivery.recipient_kind == "external",
        ),
    )


class NotificationDeliveryRepository(BaseRepository[NotificationDelivery]):

    def __init__(self, db: AsyncSession):
        super().__init__(db, NotificationDelivery)

    async def get_filtered(
        self, skip: int = 0, limit: int = 100, **filters
    ) -> Tuple[int, List[NotificationDelivery]]:
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

    async def bulk_update_status(
        self,
        delivery_ids: List[int],
        status: str,
        error_reason: str | None = None,
        sent_at: datetime | None = None,
    ) -> int:
        """
        Bulk update status for a list of delivery IDs.

        Uses a single UPDATE statement for efficiency and correctness —
        scoped to exact IDs, not re-queried by event/channel.
        """
        if not delivery_ids:
            return 0

        values: Dict[str, Any] = {"status": status}
        if error_reason is not None:
            values["error_reason"] = error_reason
        if sent_at is not None:
            values["sent_at"] = sent_at
        elif status == "sent":
            values["sent_at"] = datetime.now(timezone.utc)

        stmt = (
            update(NotificationDelivery)
            .where(NotificationDelivery.id.in_(delivery_ids))
            .values(**values)
        )
        result = await self.db.execute(stmt)
        return result.rowcount

    async def find_stale_deliveries(
        self,
        status: str,
        channels: list[str],
        max_age_minutes: int,
        limit: int = 100,
        age_column: str = "created_at",
    ) -> List[NotificationDelivery]:
        """
        Find stale deliveries: status matches, channel in list, older than max_age_minutes.

        Args:
            age_column: Which timestamp column to age against.
                - "created_at" (default): for queued deliveries stuck without execution.
                - "sent_at": for sent deliveries awaiting webhook confirmation.

        Used by reconciliation sweep for:
        - queued deliveries stuck without execution (age by created_at)
        - sent deliveries without webhook confirmation (age by sent_at)
        """
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        col = getattr(NotificationDelivery, age_column)
        result = await self.db.execute(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == status,
                NotificationDelivery.channel.in_(channels),
                col.isnot(None),
                col < cutoff,
            )
            .order_by(col.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_ready_for_retry(self, limit: int = 100) -> List[NotificationDelivery]:
        """
        Find deliveries ready for retry: status IN (queued, failed) AND next_retry_at <= now.

        Used by sweep_retry_deliveries Beat task.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status.in_(["queued", "failed"]),
                NotificationDelivery.next_retry_at.isnot(None),
                NotificationDelivery.next_retry_at <= now,
            )
            .order_by(NotificationDelivery.next_retry_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

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
        allowed_user_ids: list[int] | None = None,
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
        if allowed_user_ids is not None:
            conditions.append(_build_scope_condition(allowed_user_ids))

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

    async def get_aggregate_stats(
        self,
        date_from: "datetime | None" = None,
        date_to: "datetime | None" = None,
        event: str | None = None,
        channel: str | None = None,
        allowed_user_ids: list[int] | None = None,
    ) -> dict:
        """
        Aggregate delivery stats: counts by status and channel.

        Returns dict compatible with DeliveryStatsResponse schema.
        """
        conditions = []
        if date_from:
            conditions.append(NotificationDelivery.created_at >= date_from)
        if date_to:
            conditions.append(NotificationDelivery.created_at <= date_to)
        if event:
            conditions.append(NotificationDelivery.event == event)
        if channel:
            conditions.append(NotificationDelivery.channel == channel)
        if allowed_user_ids is not None:
            conditions.append(_build_scope_condition(allowed_user_ids))

        where = and_(*conditions) if conditions else True

        # Count by status
        status_q = (
            select(NotificationDelivery.status, func.count())
            .where(where)
            .group_by(NotificationDelivery.status)
        )
        status_rows = (await self.db.execute(status_q)).all()
        by_status = {row[0]: row[1] for row in status_rows}

        # Count by channel
        channel_q = (
            select(NotificationDelivery.channel, func.count())
            .where(where)
            .group_by(NotificationDelivery.channel)
        )
        channel_rows = (await self.db.execute(channel_q)).all()
        by_channel = {row[0]: row[1] for row in channel_rows}

        total = sum(by_status.values())
        sent = by_status.get("sent", 0) + by_status.get("delivered", 0) + by_status.get("read", 0)
        success_rate = round((sent / total * 100), 1) if total > 0 else 0.0

        return {
            "total": total,
            "by_status": by_status,
            "by_channel": by_channel,
            "success_rate": success_rate,
        }

    async def get_failure_summary(
        self,
        date_from: "datetime | None" = None,
        date_to: "datetime | None" = None,
        channel: str | None = None,
        limit: int = 20,
        allowed_user_ids: list[int] | None = None,
    ) -> dict:
        """
        Failure analytics: grouped by error_reason.

        Returns dict compatible with DeliveryFailureSummary schema.
        """
        conditions = [
            NotificationDelivery.status.in_(["failed", "dead_lettered"]),
        ]
        if date_from:
            conditions.append(NotificationDelivery.created_at >= date_from)
        if date_to:
            conditions.append(NotificationDelivery.created_at <= date_to)
        if channel:
            conditions.append(NotificationDelivery.channel == channel)
        if allowed_user_ids is not None:
            conditions.append(_build_scope_condition(allowed_user_ids))

        where = and_(*conditions)

        # Total failures
        total_q = select(func.count()).select_from(NotificationDelivery).where(where)
        total_failures = (await self.db.execute(total_q)).scalar() or 0

        # Group by reason
        reason_q = (
            select(
                NotificationDelivery.error_reason,
                func.count().label("count"),
                func.max(NotificationDelivery.created_at).label("latest_at"),
            )
            .where(where)
            .group_by(NotificationDelivery.error_reason)
            .order_by(func.count().desc())
            .limit(limit)
        )
        reason_rows = (await self.db.execute(reason_q)).all()

        by_reason = [
            {
                "error_reason": row[0] or "unknown",
                "count": row[1],
                "latest_at": row[2],
            }
            for row in reason_rows
        ]

        return {
            "total_failures": total_failures,
            "by_reason": by_reason,
        }

    # --- D3: Alerting helper methods ---

    async def get_failure_rate(self, minutes: int = 30) -> float | None:
        """Get failure rate for last N minutes. None if no deliveries."""
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        where = NotificationDelivery.created_at >= since
        total_q = select(func.count()).select_from(NotificationDelivery).where(where)
        total = (await self.db.execute(total_q)).scalar() or 0
        if total == 0:
            return None
        fail_q = (
            select(func.count()).select_from(NotificationDelivery)
            .where(where, NotificationDelivery.status.in_(["failed", "dead_lettered"]))
        )
        failures = (await self.db.execute(fail_q)).scalar() or 0
        return failures / total

    async def get_queued_backlog_count(self) -> int:
        """Count deliveries currently in queued status."""
        q = select(func.count()).select_from(NotificationDelivery).where(
            NotificationDelivery.status == "queued"
        )
        return (await self.db.execute(q)).scalar() or 0

    async def get_stale_sent_count(self, lag_minutes: int = 60) -> int:
        """Count deliveries sent > lag_minutes ago without webhook confirmation."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=lag_minutes)
        q = (
            select(func.count()).select_from(NotificationDelivery)
            .where(
                NotificationDelivery.status == "sent",
                NotificationDelivery.channel.in_(["zalo", "sms"]),
                NotificationDelivery.sent_at <= cutoff,
            )
        )
        return (await self.db.execute(q)).scalar() or 0

    # --- D5: Dashboard analytics ---

    # Status constants for analytics queries
    _SUCCESS_STATUSES = ("sent", "delivered", "read")
    _FAILURE_STATUSES = ("failed", "dead_lettered")

    async def get_time_series(
        self,
        interval: str = "hour",
        date_from: "datetime | None" = None,
        date_to: "datetime | None" = None,
        channel: str | None = None,
        allowed_user_ids: list[int] | None = None,
    ) -> list[dict]:
        """Delivery counts bucketed by hour/day. Max 30-day range."""
        from sqlalchemy import case

        if interval not in ("hour", "day"):
            interval = "hour"
        if not date_from:
            date_from = datetime.now(timezone.utc) - timedelta(days=7)
        if not date_to:
            date_to = datetime.now(timezone.utc)
        if (date_to - date_from).days > 30:
            date_from = date_to - timedelta(days=30)

        trunc = func.date_trunc(interval, NotificationDelivery.created_at)
        conds = [
            NotificationDelivery.created_at >= date_from,
            NotificationDelivery.created_at <= date_to,
        ]
        if channel:
            conds.append(NotificationDelivery.channel == channel)
        if allowed_user_ids is not None:
            conds.append(_build_scope_condition(allowed_user_ids))

        q = (
            select(
                trunc.label("bucket"),
                func.count().label("total"),
                func.count(case((NotificationDelivery.status.in_(self._SUCCESS_STATUSES), 1))).label("sent"),
                func.count(case((NotificationDelivery.status.in_(self._FAILURE_STATUSES), 1))).label("failed"),
                func.count(case((NotificationDelivery.status == "queued", 1))).label("queued"),
            )
            .where(and_(*conds))
            .group_by(trunc)
            .order_by(trunc)
        )
        rows = (await self.db.execute(q)).all()
        return [
            {"bucket": r[0], "total": r[1], "sent": r[2], "failed": r[3], "queued": r[4]}
            for r in rows
        ]

    async def get_top_events(
        self,
        limit: int = 10,
        date_from: "datetime | None" = None,
        date_to: "datetime | None" = None,
        allowed_user_ids: list[int] | None = None,
    ) -> list[dict]:
        """Top events by volume with failure rates."""
        from sqlalchemy import case

        if not date_from:
            date_from = datetime.now(timezone.utc) - timedelta(days=7)
        conds = [NotificationDelivery.created_at >= date_from]
        if date_to:
            conds.append(NotificationDelivery.created_at <= date_to)
        if allowed_user_ids is not None:
            conds.append(_build_scope_condition(allowed_user_ids))

        q = (
            select(
                NotificationDelivery.event,
                func.count().label("total"),
                func.count(case((NotificationDelivery.status.in_(self._FAILURE_STATUSES), 1))).label("failed"),
            )
            .where(and_(*conds))
            .group_by(NotificationDelivery.event)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.db.execute(q)).all()
        return [
            {
                "event": r[0],
                "total": r[1],
                "failed": r[2],
                "fail_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0.0,
            }
            for r in rows
        ]

    async def get_processing_latency_stats(
        self,
        date_from: "datetime | None" = None,
        date_to: "datetime | None" = None,
    ) -> dict:
        """P50/P95 processing latency (created_at → sent_at). PostgreSQL only."""
        from sqlalchemy import extract

        if not date_from:
            date_from = datetime.now(timezone.utc) - timedelta(days=1)
        conds = [
            NotificationDelivery.status.in_(self._SUCCESS_STATUSES),
            NotificationDelivery.sent_at.isnot(None),
            NotificationDelivery.created_at >= date_from,
        ]
        if date_to:
            conds.append(NotificationDelivery.created_at <= date_to)

        lat = extract("epoch", NotificationDelivery.sent_at - NotificationDelivery.created_at)
        q = select(
            func.percentile_cont(0.5).within_group(lat),
            func.percentile_cont(0.95).within_group(lat),
            func.count(),
        ).where(and_(*conds))

        r = (await self.db.execute(q)).first()
        if not r or r[2] == 0:
            return {"p50_seconds": None, "p95_seconds": None, "sample_count": 0}
        return {
            "p50_seconds": round(float(r[0]), 2) if r[0] else None,
            "p95_seconds": round(float(r[1]), 2) if r[1] else None,
            "sample_count": r[2],
        }
