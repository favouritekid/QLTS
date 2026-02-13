# app/repositories/lead_claim_repository.py
"""
LeadClaim Repository - Data access layer for LeadClaim model.
"""
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.base import BaseRepository


class LeadClaimRepository(BaseRepository[models.LeadClaim]):
    """Repository for LeadClaim model operations."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.LeadClaim)

    async def get_by_id(self, claim_id: int) -> Optional[models.LeadClaim]:
        """Get claim by ID with relationships."""
        result = await self.db.execute(
            select(models.LeadClaim)
            .options(
                selectinload(models.LeadClaim.collaborator),
                selectinload(models.LeadClaim.lead),
                selectinload(models.LeadClaim.reviewed_by),
            )
            .where(models.LeadClaim.id == claim_id)
        )
        return result.scalars().first()

    async def get_by_id_for_update(self, claim_id: int) -> Optional[models.LeadClaim]:
        """Get claim by ID with FOR UPDATE lock."""
        result = await self.db.execute(
            select(models.LeadClaim)
            .options(
                selectinload(models.LeadClaim.collaborator),
                selectinload(models.LeadClaim.lead),
                selectinload(models.LeadClaim.reviewed_by),
            )
            .where(models.LeadClaim.id == claim_id)
            .with_for_update()
        )
        return result.scalars().first()

    async def get_pending_by_lead_id(self, lead_id: int) -> Optional[models.LeadClaim]:
        """Get pending claim for a lead."""
        result = await self.db.execute(
            select(models.LeadClaim).where(
                models.LeadClaim.lead_id == lead_id,
                models.LeadClaim.status == "pending",
            )
        )
        return result.scalars().first()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 10,
        status: Optional[str] = None,
        collaborator_id: Optional[int] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[int, List[models.LeadClaim]]:
        """Get filtered list of claims with pagination."""
        base_query = select(models.LeadClaim)
        count_query = select(func.count(models.LeadClaim.id))

        filters = []

        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if statuses:
                filters.append(models.LeadClaim.status.in_(statuses))

        if collaborator_id is not None:
            filters.append(models.LeadClaim.collaborator_id == collaborator_id)

        if unit_id is not None:
            # Filter claims by collaborator's unit
            base_query = base_query.join(
                models.Collaborator,
                models.LeadClaim.collaborator_id == models.Collaborator.id,
            )
            count_query = count_query.join(
                models.Collaborator,
                models.LeadClaim.collaborator_id == models.Collaborator.id,
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
                selectinload(models.LeadClaim.collaborator),
                selectinload(models.LeadClaim.lead),
                selectinload(models.LeadClaim.reviewed_by),
            )
            .order_by(models.LeadClaim.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        result = await self.db.execute(base_query)
        claims = list(result.scalars().all())

        return total_count, claims

    async def get_claims_by_collaborator(
        self,
        collaborator_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> Tuple[int, List[models.LeadClaim]]:
        """Get claims by collaborator with pagination."""
        return await self.get_filtered(
            skip=skip, limit=limit, collaborator_id=collaborator_id
        )
