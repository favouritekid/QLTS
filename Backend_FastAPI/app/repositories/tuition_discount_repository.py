# app/repositories/tuition_discount_repository.py
"""
✅ PATTERN A COMPLIANT - Tuition Discount Repository

Repository for TuitionDiscountPolicy model.
Handles all database access for tuition discount policies.
"""

from datetime import date
from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.base import BaseRepository


class TuitionDiscountRepository(BaseRepository[models.TuitionDiscountPolicy]):
    """Repository for TuitionDiscountPolicy model."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, models.TuitionDiscountPolicy)

    async def get_by_code(self, code: str) -> Optional[models.TuitionDiscountPolicy]:
        """Get policy by code."""
        result = await self.db.execute(
            select(self.model).where(self.model.code == code.upper())
        )
        return result.scalar_one_or_none()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        is_active: Optional[bool] = None,
        include_expired: bool = False,
    ) -> Tuple[int, List[models.TuitionDiscountPolicy]]:
        """
        Get filtered policies with count.
        """
        # Base queries
        query = select(self.model)
        count_query = select(func.count(self.model.id))

        # Filter by active status
        if is_active is not None:
            query = query.where(self.model.is_active == is_active)
            count_query = count_query.where(self.model.is_active == is_active)

        # Filter expired policies
        if not include_expired:
            today = date.today()
            validity_filter = or_(
                self.model.valid_to.is_(None),
                self.model.valid_to >= today
            )
            query = query.where(validity_filter)
            count_query = count_query.where(validity_filter)

        # Order by priority (desc), then by created_at (desc)
        query = query.order_by(
            self.model.priority.desc(),
            self.model.created_at.desc()
        )

        # Pagination
        query = query.offset(skip).limit(limit)

        # Execute
        total = (await self.db.execute(count_query)).scalar() or 0
        policies = (await self.db.execute(query)).scalars().all()

        return total, list(policies)

    async def get_active_within_validity(self) -> List[models.TuitionDiscountPolicy]:
        """
        Get all active policies that are within their validity period and have quota.
        Used for calculation logic.
        """
        today = date.today()
        query = select(self.model).where(
            self.model.is_active == True,
            or_(
                self.model.valid_from.is_(None),
                self.model.valid_from <= today
            ),
            or_(
                self.model.valid_to.is_(None),
                self.model.valid_to >= today
            ),
            or_(
                self.model.max_usage.is_(None),
                self.model.current_usage < self.model.max_usage
            )
        ).order_by(self.model.priority.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())
