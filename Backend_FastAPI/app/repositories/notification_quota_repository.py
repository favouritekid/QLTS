# app/repositories/notification_quota_repository.py
"""
Phase D1: Repository for NotificationQuota CRUD and quota checks.
"""
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_quota import NotificationQuota
from app.repositories.base import BaseRepository


class NotificationQuotaRepository(BaseRepository[NotificationQuota]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, NotificationQuota)

    async def get_filtered(
        self, skip: int = 0, limit: int = 100, **filters
    ) -> Tuple[List[NotificationQuota], int]:
        """Required by BaseRepository."""
        query = select(self.model).offset(skip).limit(limit)
        result = await self.db.execute(query)
        records = list(result.scalars().all())
        count_q = select(self.model)
        total = len(records)  # Simplified for quota (small table)
        return records, total

    async def get_current_quota(
        self,
        channel: str,
        provider: str = "default",
        period: str = "daily",
        period_start: Optional[date] = None,
    ) -> Optional[NotificationQuota]:
        """Get quota record for current period."""
        if period_start is None:
            period_start = date.today()

        query = select(NotificationQuota).where(
            NotificationQuota.channel == channel,
            NotificationQuota.provider == provider,
            NotificationQuota.period == period,
            NotificationQuota.period_start == period_start,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def upsert_quota(
        self,
        channel: str,
        provider: str,
        period: str,
        period_start: date,
        quota_limit: int,
        quota_used: int = 0,
        quota_remaining: Optional[int] = None,
        blocked: bool = False,
    ) -> NotificationQuota:
        """Insert or update quota record."""
        stmt = pg_insert(NotificationQuota).values(
            channel=channel,
            provider=provider,
            period=period,
            period_start=period_start,
            quota_limit=quota_limit,
            quota_used=quota_used,
            quota_remaining=quota_remaining,
            blocked=blocked,
        ).on_conflict_do_update(
            constraint="uq_quota_channel_provider_period",
            set_={
                "quota_limit": quota_limit,
                "quota_used": quota_used,
                "quota_remaining": quota_remaining,
                "blocked": blocked,
                "updated_at": datetime.now(timezone.utc),
            },
        ).returning(NotificationQuota)

        result = await self.db.execute(stmt)
        row = result.scalar_one()
        return row

    async def increment_used(
        self,
        channel: str,
        provider: str = "default",
        period: str = "daily",
        period_start: Optional[date] = None,
    ) -> Optional[NotificationQuota]:
        """Increment quota_used by 1. Returns updated record or None if not found."""
        if period_start is None:
            period_start = date.today()

        stmt = (
            update(NotificationQuota)
            .where(
                NotificationQuota.channel == channel,
                NotificationQuota.provider == provider,
                NotificationQuota.period == period,
                NotificationQuota.period_start == period_start,
            )
            .values(
                quota_used=NotificationQuota.quota_used + 1,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(NotificationQuota)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def is_over_quota(
        self,
        channel: str,
        provider: str = "default",
        period: str = "daily",
        period_start: Optional[date] = None,
    ) -> bool:
        """Check if channel is over quota for current period."""
        quota = await self.get_current_quota(channel, provider, period, period_start)
        if quota is None:
            return False  # No quota configured = unlimited
        return quota.blocked or quota.quota_used >= quota.quota_limit

    async def get_current_quotas(
        self,
        windows: Optional[List[Tuple[str, date]]] = None,
    ) -> List[NotificationQuota]:
        """Get quota records matching any ``(period, period_start)`` window.

        Each window targets one channel-class's CURRENT period exactly, so a
        stale same-``period_start`` row of a different period (e.g. a daily row
        created on the 1st of the month) is not accidentally returned alongside
        a monthly row. Defaults to today's daily window.
        """
        if not windows:
            windows = [("daily", date.today())]

        conditions = [
            (NotificationQuota.period == period)
            & (NotificationQuota.period_start == period_start)
            for period, period_start in windows
        ]
        query = (
            select(NotificationQuota)
            .where(or_(*conditions))
            .order_by(NotificationQuota.channel)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
