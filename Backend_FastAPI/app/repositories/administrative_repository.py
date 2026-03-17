# app/repositories/administrative_repository.py
"""Repository for administrative nodes (provinces, districts, wards)."""

from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.administrative_node import AdministrativeNode, AdministrativeLevel
from app.repositories.base import BaseRepository


class AdministrativeRepository(BaseRepository[AdministrativeNode]):
    """Repository for administrative node queries."""
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, AdministrativeNode)
    
    async def get_provinces(self) -> list[AdministrativeNode]:
        """Get one selectable province record per code, preserving legacy codes."""
        stmt = (
            select(AdministrativeNode)
            .where(AdministrativeNode.level == AdministrativeLevel.PROVINCE)
            .where(AdministrativeNode.is_active == True)
            .distinct(AdministrativeNode.code)
            .order_by(AdministrativeNode.code, AdministrativeNode.valid_from.desc())
        )
        result = await self.db.execute(stmt)
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
        result = await self.db.execute(stmt)
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
        result = await self.db.execute(stmt)
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
        result = await self.db.execute(stmt)
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
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters
    ) -> Tuple[int, List[AdministrativeNode]]:
        """
        Get filtered administrative nodes with pagination.
        
        Filters supported:
        - level: AdministrativeLevel
        - province_code: str
        - district_code: str
        - is_active: bool
        """
        from sqlalchemy import func
        
        query = select(AdministrativeNode)
        count_query = select(func.count()).select_from(AdministrativeNode)
        
        # Apply filters
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
        
        # Get total count
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0
        
        # Get paginated results
        query = query.offset(skip).limit(limit).order_by(AdministrativeNode.code)
        result = await self.db.execute(query)
        
        return total, list(result.scalars().all())
