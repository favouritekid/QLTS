# app/repositories/notification_quota_repository.py
"""
Phase D1: Repository for NotificationQuota CRUD and quota checks.
"""
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, update
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

    async def get_all_quotas(
        self,
        period_starts: Optional[List[date]] = None,
    ) -> List[NotificationQuota]:
        """Get all quota records whose ``period_start`` is in ``period_starts``.

        Defaults to today's rows. Callers pass multiple dates (e.g. today +
        first-of-month) to fetch both daily and monthly channels in one query.
        """
        if not period_starts:
            period_starts = [date.today()]

        query = (
            select(NotificationQuota)
            .where(NotificationQuota.period_start.in_(period_starts))
            .order_by(NotificationQuota.channel)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
