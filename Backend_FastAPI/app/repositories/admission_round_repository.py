# app/repositories/admission_round_repository.py
"""Repository for OfferingAdmissionRound (Phase 2 PR-2A)."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OfferingAdmissionRound


class AdmissionRoundRepository:
    """Data access layer for admission rounds."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, round_id: int) -> Optional[OfferingAdmissionRound]:
        return await self.db.get(OfferingAdmissionRound, round_id)

    async def list_by_academic_info(
        self, academic_info_id: int
    ) -> List[OfferingAdmissionRound]:
        result = await self.db.execute(
            select(OfferingAdmissionRound)
            .where(OfferingAdmissionRound.academic_info_id == academic_info_id)
            .order_by(OfferingAdmissionRound.round_code)
        )
        return list(result.scalars().all())

    async def get_default_dot1(
        self, academic_info_id: int
    ) -> Optional[OfferingAdmissionRound]:
        """Service shim auto-resolve target — used by PR-2B
        ``create_admission_path`` when caller omits round_id.
        """
        result = await self.db.execute(
            select(OfferingAdmissionRound).where(
                OfferingAdmissionRound.academic_info_id == academic_info_id,
                OfferingAdmissionRound.round_code == "DOT_1",
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code(
        self, academic_info_id: int, round_code: str
    ) -> Optional[OfferingAdmissionRound]:
        result = await self.db.execute(
            select(OfferingAdmissionRound).where(
                OfferingAdmissionRound.academic_info_id == academic_info_id,
                OfferingAdmissionRound.round_code == round_code,
            )
        )
        return result.scalar_one_or_none()
