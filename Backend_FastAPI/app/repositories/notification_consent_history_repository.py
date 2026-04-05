# app/repositories/notification_consent_history_repository.py
"""
Repository for NotificationConsentHistory — append-only consent audit trail.
"""
from typing import Any, Dict, List, Tuple

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_consent_history import NotificationConsentHistory
from app.repositories.base import BaseRepository


class NotificationConsentHistoryRepository(BaseRepository[NotificationConsentHistory]):

    def __init__(self, db: AsyncSession):
        super().__init__(db, NotificationConsentHistory)

    async def get_filtered(
        self, skip: int = 0, limit: int = 100, **filters
    ) -> Tuple[int, List[NotificationConsentHistory]]:
        """Required by BaseRepository. Delegates to list_for_entity."""
        records, total = await self.list_for_entity(
            source_type=filters.get("source_type", ""),
            source_id=filters.get("source_id", 0),
            skip=skip,
            limit=limit,
        )
        return total, records

    async def append(self, data: Dict[str, Any]) -> NotificationConsentHistory:
        """
        Append a new history entry. Immutable — no updates allowed.

        Args:
            data: Dict with keys: consent_id, channel, source_type, source_id,
                  action, old_status, new_status, performed_by
        Returns:
            Created NotificationConsentHistory row.
        """
        row = NotificationConsentHistory(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def list_for_entity(
        self,
        source_type: str,
        source_id: int,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[NotificationConsentHistory], int]:
        """
        List history entries for a specific entity, newest first.
        """
        conditions = and_(
            NotificationConsentHistory.source_type == source_type,
            NotificationConsentHistory.source_id == source_id,
        )

        count_q = (
            select(func.count())
            .select_from(NotificationConsentHistory)
            .where(conditions)
        )
        total = (await self.db.execute(count_q)).scalar() or 0

        query = (
            select(NotificationConsentHistory)
            .where(conditions)
            .order_by(NotificationConsentHistory.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def list_for_consent(
        self,
        consent_id: int,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[NotificationConsentHistory], int]:
        """
        List history entries for a specific consent record, newest first.
        """
        conditions = NotificationConsentHistory.consent_id == consent_id

        count_q = (
            select(func.count())
            .select_from(NotificationConsentHistory)
            .where(conditions)
        )
        total = (await self.db.execute(count_q)).scalar() or 0

        query = (
            select(NotificationConsentHistory)
            .where(conditions)
            .order_by(NotificationConsentHistory.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all()), total
