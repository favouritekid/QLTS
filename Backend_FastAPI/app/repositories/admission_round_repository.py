# app/repositories/admission_round_repository.py
"""Repository for OfferingAdmissionRound year-level (Phase 2 v8.2 PR-2A v2)."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OfferingAdmissionRound


class AdmissionRoundRepository:
    """Data access layer for admission rounds (year-level)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, round_id: int) -> Optional[OfferingAdmissionRound]:
        return await self.db.get(OfferingAdmissionRound, round_id)

    async def list_by_year(
        self, academic_year: int
    ) -> List[OfferingAdmissionRound]:
        """List all rounds for a given academic_year, ordered by round_code."""
        result = await self.db.execute(
            select(OfferingAdmissionRound)
            .where(OfferingAdmissionRound.academic_year == academic_year)
            .order_by(OfferingAdmissionRound.round_code)
        )
        return list(result.scalars().all())

    async def get_default_dot1(
        self, academic_year: int
    ) -> Optional[OfferingAdmissionRound]:
        """Service shim auto-resolve target — used by PR-2B v2
        ``create_admission_path`` when caller omits round_id.

        Q1 v8.2 year-level lookup: 1 DOT_1 row per academic_year (cho cả trường).
        """
        result = await self.db.execute(
            select(OfferingAdmissionRound).where(
                OfferingAdmissionRound.academic_year == academic_year,
                OfferingAdmissionRound.round_code == "DOT_1",
            )
        )
        return result.scalar_one_or_none()

    async def get_by_year_and_code(
        self, academic_year: int, round_code: str
    ) -> Optional[OfferingAdmissionRound]:
        result = await self.db.execute(
            select(OfferingAdmissionRound).where(
                OfferingAdmissionRound.academic_year == academic_year,
                OfferingAdmissionRound.round_code == round_code,
            )
        )
        return result.scalar_one_or_none()
