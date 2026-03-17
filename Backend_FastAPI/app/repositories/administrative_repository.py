# app/repositories/administrative_repository.py
"""
Repository for administrative nodes (provinces, districts, wards).

Two distinct snapshots in DB:
- Legacy (valid_to IS NOT NULL): 63 provinces, 3-level (province → district → ward)
- Current (valid_to IS NULL):    34 provinces, 2-level (province → ward)

All public methods require an explicit `current` flag to select the snapshot.
"""

from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.administrative_node import AdministrativeNode, AdministrativeLevel
from app.repositories.base import BaseRepository


class AdministrativeRepository(BaseRepository[AdministrativeNode]):
    """Repository for administrative node queries."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, AdministrativeNode)

    # ------------------------------------------------------------------
    # PROVINCES
    # ------------------------------------------------------------------

    async def get_provinces(self, *, current: bool) -> list[AdministrativeNode]:
        """
        Get provinces for a specific era.

        current=True  → 34 provinces (valid_to IS NULL)
        current=False → 63 legacy provinces (valid_to IS NOT NULL)
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.PROVINCE)
            .where(AdministrativeNode.is_active == True)
        )
        if current:
            stmt = stmt.where(AdministrativeNode.valid_to.is_(None))
        else:
            stmt = stmt.where(AdministrativeNode.valid_to.isnot(None))
        stmt = stmt.order_by(AdministrativeNode.code)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # DISTRICTS (legacy only — current has no districts)
    # ------------------------------------------------------------------

    async def get_districts_by_province(self, province_code: str) -> list[AdministrativeNode]:
        """
        Get districts under a legacy province (3-level structure).
        Districts only exist in the legacy snapshot.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.DISTRICT)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.valid_to.isnot(None))  # legacy only
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # WARDS
    # ------------------------------------------------------------------

    async def get_wards_by_province(self, province_code: str) -> list[AdministrativeNode]:
        """
        Get wards directly under a current province (2-level structure).
        These wards have district_code = NULL and valid_to IS NULL.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.district_code.is_(None))
            .where(AdministrativeNode.valid_to.is_(None))
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_wards_by_district(
        self,
        province_code: str,
        district_code: str,
    ) -> list[AdministrativeNode]:
        """
        Get wards under a specific legacy district (3-level structure).
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.district_code == district_code)
            .where(AdministrativeNode.valid_to.isnot(None))  # legacy only
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # REVERSE LOOKUP
    # ------------------------------------------------------------------

    async def find_old_ward_by_code(self, ward_code: str) -> Optional[AdministrativeNode]:
        """
        Find the legacy (3-level) ward record by code.
        Used to lookup which district a ward belonged to.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.code == ward_code)
            .where(AdministrativeNode.valid_to.isnot(None))
            .where(AdministrativeNode.is_active == True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # GENERIC FILTERED (admin panel)
    # ------------------------------------------------------------------

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters,
    ) -> Tuple[int, List[AdministrativeNode]]:
        """
        Get filtered administrative nodes with pagination.

        Filters: level, province_code, district_code, is_active
        """
        from sqlalchemy import func

        query = select(AdministrativeNode)
        count_query = select(func.count()).select_from(AdministrativeNode)

        if filters.get("level"):
            query = query.where(AdministrativeNode.level == filters["level"])
            count_query = count_query.where(AdministrativeNode.level == filters["level"])
        if filters.get("province_code"):
            query = query.where(AdministrativeNode.province_code == filters["province_code"])
            count_query = count_query.where(AdministrativeNode.province_code == filters["province_code"])
        if filters.get("district_code"):
            query = query.where(AdministrativeNode.district_code == filters["district_code"])
            count_query = count_query.where(AdministrativeNode.district_code == filters["district_code"])
        if filters.get("is_active") is not None:
            query = query.where(AdministrativeNode.is_active == filters["is_active"])
            count_query = count_query.where(AdministrativeNode.is_active == filters["is_active"])

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        query = query.offset(skip).limit(limit).order_by(AdministrativeNode.code)
        result = await self.db.execute(query)

        return total, list(result.scalars().all())
