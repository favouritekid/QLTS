# app/repositories/commission_repository.py
"""
Commission Repository - Data access layer for CommissionPolicy and CommissionRecord.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.models.commission import CommissionPolicy, CommissionRecord
from app.repositories.base import BaseRepository


class CommissionPolicyRepository(BaseRepository[CommissionPolicy]):
    """Repository for CommissionPolicy CRUD and queries."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, CommissionPolicy)

    async def get_by_id(self, policy_id: int) -> Optional[CommissionPolicy]:
        result = await self.db.execute(
            select(CommissionPolicy)
            .options(
                selectinload(CommissionPolicy.unit),
                selectinload(CommissionPolicy.created_by),
            )
            .where(CommissionPolicy.id == policy_id)
        )
        return result.scalars().first()

    async def get_active_policies_for_status(
        self,
        trigger_status_id: str,
        unit_id: Optional[int] = None,
        offering_id: Optional[int] = None,
        reference_date: Optional[date] = None,
    ) -> List[CommissionPolicy]:
        """
        Find active policies matching a trigger status, scoped by unit/offering.

        Policy matching priority:
        1. Exact match (unit_id + offering_id)
        2. Unit-only match (unit_id, offering_id=NULL)
        3. Global match (unit_id=NULL, offering_id=NULL)
        """
        if reference_date is None:
            reference_date = date.today()

        query = (
            select(CommissionPolicy)
            .where(
                CommissionPolicy.trigger_status_id == trigger_status_id,
                CommissionPolicy.is_active == True,
                CommissionPolicy.effective_from <= reference_date,
                or_(
                    CommissionPolicy.effective_to.is_(None),
                    CommissionPolicy.effective_to >= reference_date,
                ),
            )
        )

        # Scope filtering: match specific or global policies
        scope_filters = [
            # Global policies
            and_(
                CommissionPolicy.unit_id.is_(None),
                CommissionPolicy.offering_id.is_(None),
            ),
        ]
        if unit_id is not None:
            scope_filters.append(
                and_(
                    CommissionPolicy.unit_id == unit_id,
                    CommissionPolicy.offering_id.is_(None),
                )
            )
        if unit_id is not None and offering_id is not None:
            scope_filters.append(
                and_(
                    CommissionPolicy.unit_id == unit_id,
                    CommissionPolicy.offering_id == offering_id,
                )
            )

        query = query.where(or_(*scope_filters))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 10,
        is_active: Optional[bool] = None,
        trigger_status_id: Optional[str] = None,
    ) -> Tuple[int, List[CommissionPolicy]]:
        """List policies with filters and pagination."""
        base_query = select(CommissionPolicy)
        count_query = select(func.count(CommissionPolicy.id))

        filters = []
        if is_active is not None:
            filters.append(CommissionPolicy.is_active == is_active)
        if trigger_status_id:
            filters.append(CommissionPolicy.trigger_status_id == trigger_status_id)

        if filters:
            base_query = base_query.where(*filters)
            count_query = count_query.where(*filters)

        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar_one_or_none() or 0

        if total_count == 0:
            return 0, []

        base_query = (
            base_query.options(
                selectinload(CommissionPolicy.unit),
                selectinload(CommissionPolicy.created_by),
            )
            .order_by(CommissionPolicy.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(base_query)
        return total_count, list(result.scalars().all())


class CommissionRecordRepository(BaseRepository[CommissionRecord]):
    """Repository for CommissionRecord queries."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, CommissionRecord)

    async def get_by_id(self, record_id: int) -> Optional[CommissionRecord]:
        result = await self.db.execute(
            select(CommissionRecord)
            .options(
                selectinload(CommissionRecord.collaborator),
                selectinload(CommissionRecord.lead),
                selectinload(CommissionRecord.policy),
            )
            .where(CommissionRecord.id == record_id)
        )
        return result.scalars().first()

    async def get_by_lead_and_policy(
        self,
        lead_id: int,
        policy_id: int,
    ) -> Optional[CommissionRecord]:
        """Check if a commission record already exists for this lead+policy pair."""
        result = await self.db.execute(
            select(CommissionRecord).where(
                CommissionRecord.lead_id == lead_id,
                CommissionRecord.policy_id == policy_id,
            )
        )
        return result.scalars().first()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 10,
        collaborator_id: Optional[int] = None,
        status: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[int, List[CommissionRecord]]:
        """List records with filters and pagination."""
        base_query = select(CommissionRecord)
        count_query = select(func.count(CommissionRecord.id))

        filters = []
        if collaborator_id is not None:
            filters.append(CommissionRecord.collaborator_id == collaborator_id)
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if statuses:
                filters.append(CommissionRecord.status.in_(statuses))
        if unit_id is not None:
            # Join through collaborator to filter by unit
            base_query = base_query.join(
                models.Collaborator,
                CommissionRecord.collaborator_id == models.Collaborator.id,
            )
            count_query = count_query.join(
                models.Collaborator,
                CommissionRecord.collaborator_id == models.Collaborator.id,
            )
            filters.append(models.Collaborator.unit_id == unit_id)

        if filters:
            base_query = base_query.where(*filters)
            count_query = count_query.where(*filters)

        total_result = await self.db.execute(count_query)
        total_count = total_result.scalar_one_or_none() or 0

        if total_count == 0:
            return 0, []

        base_query = (
            base_query.options(
                selectinload(CommissionRecord.collaborator),
                selectinload(CommissionRecord.lead),
                selectinload(CommissionRecord.policy),
            )
            .order_by(CommissionRecord.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(base_query)
        return total_count, list(result.scalars().all())

    async def get_stats_by_collaborator(self, collaborator_id: int) -> dict:
        """Aggregate commission stats for a collaborator."""
        result = await self.db.execute(
            select(
                CommissionRecord.status,
                func.count(CommissionRecord.id).label("count"),
                func.coalesce(func.sum(CommissionRecord.amount), 0).label("total"),
            )
            .where(CommissionRecord.collaborator_id == collaborator_id)
            .group_by(CommissionRecord.status)
        )
        rows = result.all()

        stats = {
            "total_earned": Decimal("0"),
            "total_pending": Decimal("0"),
            "total_paid": Decimal("0"),
            "total_rejected": Decimal("0"),
            "record_count": 0,
        }
        for row in rows:
            stats["record_count"] += row.count
            if row.status == "pending":
                stats["total_pending"] += row.total
                stats["total_earned"] += row.total
            elif row.status == "approved":
                stats["total_earned"] += row.total
                stats["total_pending"] += row.total
            elif row.status == "paid":
                stats["total_paid"] += row.total
                stats["total_earned"] += row.total
            elif row.status == "rejected":
                stats["total_rejected"] += row.total

        return stats

    async def cancel_pending_for_lead(
        self,
        lead_id: int,
        reason: str,
        cancelled_by_id: Optional[int] = None,
    ) -> int:
        """Cancel all pending/approved commission records for a lead."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(CommissionRecord)
            .where(
                CommissionRecord.lead_id == lead_id,
                CommissionRecord.status.in_(["pending", "approved"]),
            )
            .values(
                status="cancelled",
                cancelled_at=now,
                cancelled_by_id=cancelled_by_id,
                cancellation_reason=reason,
            )
        )
        return result.rowcount
