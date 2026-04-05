# app/repositories/notification_consent_repository.py
"""
Repository for NotificationConsent — latest-state consent management.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.notification_consent import NotificationConsent
from app.repositories.base import BaseRepository
from app.repositories.notification_consent_history_repository import (
    NotificationConsentHistoryRepository,
)


class NotificationConsentRepository(BaseRepository[NotificationConsent]):

    def __init__(self, db: AsyncSession):
        super().__init__(db, NotificationConsent)

    async def get_filtered(
        self, skip: int = 0, limit: int = 100, **filters
    ) -> Tuple[int, List[NotificationConsent]]:
        """Required by BaseRepository. Delegates to list_consents."""
        records, total = await self.list_consents(skip=skip, limit=limit, **filters)
        return total, records

    async def get_latest(
        self, channel: str, source_type: str, source_id: int
    ) -> Optional[NotificationConsent]:
        """Get latest consent state for a specific entity+channel."""
        result = await self.db.execute(
            select(NotificationConsent).where(
                and_(
                    NotificationConsent.channel == channel,
                    NotificationConsent.source_type == source_type,
                    NotificationConsent.source_id == source_id,
                )
            )
        )
        return result.scalars().first()

    async def upsert_latest(self, data: Dict[str, Any]) -> NotificationConsent:
        """
        Upsert consent — insert or update on (channel, source_type, source_id).
        After upsert, appends a history row capturing old->new status.
        Returns the resulting row.
        """
        # H7: Capture old state with row lock to prevent race condition
        # SELECT FOR UPDATE prevents concurrent upserts from reading stale old_status
        from sqlalchemy import select
        lock_q = (
            select(NotificationConsent)
            .where(
                NotificationConsent.channel == data["channel"],
                NotificationConsent.source_type == data["source_type"],
                NotificationConsent.source_id == data["source_id"],
            )
            .with_for_update()
        )
        lock_result = await self.db.execute(lock_q)
        old_consent = lock_result.scalars().first()
        old_status = old_consent.consent_status if old_consent else None

        stmt = pg_insert(NotificationConsent).values(**data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_consent_channel_source",
            set_={
                "consent_status": stmt.excluded.consent_status,
                "consent_source": stmt.excluded.consent_source,
                "normalized_phone": stmt.excluded.normalized_phone,
                "normalized_email": stmt.excluded.normalized_email,
                "granted_by": stmt.excluded.granted_by,
                "granted_at": stmt.excluded.granted_at,
                "revoked_at": stmt.excluded.revoked_at,
                "notes": stmt.excluded.notes,
                "updated_at": func.now(),
            },
        )
        await self.db.execute(stmt)
        await self.db.flush()

        # Expire any cached identity-map entry so the next SELECT sees
        # the updated values written by ON CONFLICT DO UPDATE.
        # Without this, SQLAlchemy may return the stale pre-upsert row.
        existing = await self.get_latest(
            data["channel"], data["source_type"], data["source_id"]
        )
        if existing:
            await self.db.refresh(existing)

        # Append history row (Phase E1)
        new_status = data.get("consent_status", "granted")
        history_repo = NotificationConsentHistoryRepository(self.db)
        await history_repo.append({
            "consent_id": existing.id if existing else None,
            "channel": data["channel"],
            "source_type": data["source_type"],
            "source_id": data["source_id"],
            "action": new_status,  # granted or revoked
            "old_status": old_status,
            "new_status": new_status,
            "performed_by": data.get("granted_by"),
        })

        return existing

    async def bulk_upsert(
        self, rows: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Bulk upsert consent rows.
        Returns summary: {processed, granted, revoked, skipped, errors}.
        """
        summary = {"processed": 0, "granted": 0, "revoked": 0, "skipped": 0, "errors": []}

        for i, row in enumerate(rows):
            try:
                result = await self.upsert_latest(row)
                summary["processed"] += 1
                if result.consent_status == "granted":
                    summary["granted"] += 1
                elif result.consent_status == "revoked":
                    summary["revoked"] += 1
            except Exception as e:
                summary["errors"].append({"line": i + 1, "message": str(e)})
                summary["skipped"] += 1

        return summary

    async def list_consents(
        self,
        channel: str | None = None,
        source_type: str | None = None,
        consent_status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[NotificationConsent], int]:
        """List consents with filters."""
        conditions = []
        if channel:
            conditions.append(NotificationConsent.channel == channel)
        if source_type:
            conditions.append(NotificationConsent.source_type == source_type)
        if consent_status:
            conditions.append(NotificationConsent.consent_status == consent_status)

        where = and_(*conditions) if conditions else True

        count_q = select(func.count()).select_from(NotificationConsent).where(where)
        total = (await self.db.execute(count_q)).scalar() or 0

        query = (
            select(NotificationConsent)
            .where(where)
            .order_by(NotificationConsent.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def is_consent_granted(
        self, channel: str, source_type: str, source_id: int
    ) -> bool:
        """Check if consent is currently granted. No record = no consent."""
        consent = await self.get_latest(channel, source_type, source_id)
        return consent is not None and consent.consent_status == "granted"
