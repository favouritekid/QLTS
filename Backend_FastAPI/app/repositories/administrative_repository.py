# app/repositories/administrative_repository.py
"""Repository for administrative nodes (provinces, districts, wards)."""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.administrative_node import AdministrativeNode, AdministrativeLevel
from app.repositories.base_repository import BaseRepository


class AdministrativeRepository(BaseRepository[AdministrativeNode]):
    """Repository for administrative node queries."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(AdministrativeNode, session)
    
    async def get_provinces(self) -> list[AdministrativeNode]:
        """Get all unique provinces (current valid or permanent)."""
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.PROVINCE)
            .where(AdministrativeNode.is_active == True)
            .distinct(AdministrativeNode.code)
            .order_by(AdministrativeNode.code, AdministrativeNode.valid_from.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_districts_by_province(self, province_code: str) -> list[AdministrativeNode]:
        """
        Get districts under a province (3-level structure only).
        Districts only exist in the old (3-level) structure.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.DISTRICT)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_wards_by_province(self, province_code: str) -> list[AdministrativeNode]:
        """
        Get wards directly under a province (2-level structure).
        These wards have district_code = NULL.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.district_code.is_(None))  # 2-level
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_wards_by_district(
        self, 
        province_code: str, 
        district_code: str
    ) -> list[AdministrativeNode]:
        """
        Get wards under a specific district (3-level structure).
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.province_code == province_code)
            .where(AdministrativeNode.district_code == district_code)
            .where(AdministrativeNode.is_active == True)
            .order_by(AdministrativeNode.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def find_old_ward_by_code(self, ward_code: str) -> Optional[AdministrativeNode]:
        """
        Find the OLD (3-level) ward record by code.
        Used to lookup which district a ward belonged to.
        """
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.WARD)
            .where(AdministrativeNode.code == ward_code)
            .where(AdministrativeNode.valid_to.isnot(None))  # OLD record
            .where(AdministrativeNode.is_active == True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
