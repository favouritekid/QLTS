# app/repositories/kpi_repository.py
"""
KpiRepository - Data access for KPI configuration

Provides queries for:
- KPI target retrieval with inheritance (officer → unit → global)
- Annual target progress
- YTD sync
"""

from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.base import BaseRepository


class KpiRepository(BaseRepository[models.KpiConfig]):
    """
    Repository for KPI configuration data access.
    """
    
    def __init__(self, db: AsyncSession):
        super().__init__(db, models.KpiConfig)
    
    async def get_target_by_officer(
        self,
        kpi_code: str,
        officer_id: int,
        period_type: str = "daily"
    ) -> Optional[int]:
        """Get officer-specific KPI target."""
        result = await self.db.execute(
            select(models.KpiConfig.target_value)
            .where(
                models.KpiConfig.officer_id == officer_id,
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.is_active == True,
            )
        )
        return result.scalar_one_or_none()
    
    async def get_target_by_unit(
        self,
        kpi_code: str,
        unit_id: int,
        period_type: str = "daily"
    ) -> Optional[int]:
        """Get unit-level KPI target."""
        result = await self.db.execute(
            select(models.KpiConfig.target_value)
            .where(
                models.KpiConfig.unit_id == unit_id,
                models.KpiConfig.officer_id.is_(None),
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.is_active == True,
            )
        )
        return result.scalar_one_or_none()
    
    async def get_global_target(
        self,
        kpi_code: str,
        period_type: str = "daily"
    ) -> Optional[int]:
        """Get global default KPI target."""
        result = await self.db.execute(
            select(models.KpiConfig.target_value)
            .where(
                models.KpiConfig.unit_id.is_(None),
                models.KpiConfig.officer_id.is_(None),
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.is_active == True,
            )
        )
        return result.scalar_one_or_none()
    
    async def get_kpi_target_with_inheritance(
        self,
        kpi_code: str,
        officer_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        period_type: str = "daily",
        default: int = 0
    ) -> int:
        """
        Get KPI target with inheritance chain.
        
        Priority: officer → unit → global → default
        """
        # 1. Officer-specific
        if officer_id:
            target = await self.get_target_by_officer(kpi_code, officer_id, period_type)
            if target is not None:
                return target
        
        # 2. Unit-level
        if unit_id:
            target = await self.get_target_by_unit(kpi_code, unit_id, period_type)
            if target is not None:
                return target
        
        # 3. Global
        target = await self.get_global_target(kpi_code, period_type)
        if target is not None:
            return target
        
        # 4. Default
        return default
    
    async def get_all_active_configs(
        self,
        officer_id: Optional[int] = None,
        unit_id: Optional[int] = None,
    ) -> List[models.KpiConfig]:
        """Get all active KPI configs for officer/unit."""
        conditions = [models.KpiConfig.is_active == True]
        
        if officer_id:
            conditions.append(models.KpiConfig.officer_id == officer_id)
        if unit_id:
            conditions.append(models.KpiConfig.unit_id == unit_id)
        
        result = await self.db.execute(
            select(models.KpiConfig).where(*conditions)
        )
        return list(result.scalars().all())
    
    async def get_annual_target_record(
        self,
        officer_id: int,
        kpi_code: str,
        fiscal_year: int,
    ) -> Optional[models.KpiTarget]:
        """Get annual target record for officer."""
        result = await self.db.execute(
            select(models.KpiTarget)
            .where(
                models.KpiTarget.officer_id == officer_id,
                models.KpiTarget.kpi_code == kpi_code,
                models.KpiTarget.fiscal_year == fiscal_year,
            )
        )
        return result.scalar_one_or_none()
    
    async def get_filtered(self, skip: int = 0, limit: int = 100, **filters):
        """Get filtered KPI configs."""
        query = select(models.KpiConfig).where(models.KpiConfig.is_active == True)
        if filters.get("kpi_code"):
            query = query.where(models.KpiConfig.kpi_code == filters["kpi_code"])
        
        result = await self.db.execute(query.offset(skip).limit(limit))
        configs = list(result.scalars().all())
        
        count_result = await self.db.execute(
            select(func.count(models.KpiConfig.id)).where(models.KpiConfig.is_active == True)
        )
        total = count_result.scalar() or 0
        
        return total, configs
