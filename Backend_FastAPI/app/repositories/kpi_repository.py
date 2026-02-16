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
    
    # =========================================================================
    # Admin CRUD Operations (for kpi_config router)
    # =========================================================================
    
    async def list_configs(
        self,
        kpi_code: Optional[str] = None,
        unit_id: Optional[int] = None,
        is_active: Optional[bool] = True,
    ) -> List[models.KpiConfig]:
        """
        List all KPI configs with filters.
        Used by admin router.
        """
        query = select(models.KpiConfig)
        
        if kpi_code:
            query = query.where(models.KpiConfig.kpi_code == kpi_code)
        if unit_id is not None:
            query = query.where(models.KpiConfig.unit_id == unit_id)
        if is_active is not None:
            query = query.where(models.KpiConfig.is_active == is_active)
        
        query = query.order_by(
            models.KpiConfig.kpi_code,
            models.KpiConfig.unit_id,
            models.KpiConfig.officer_id
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def check_duplicate_exists(
        self,
        kpi_code: str,
        period_type: str,
        unit_id: Optional[int] = None,
        officer_id: Optional[int] = None,
    ) -> Optional[models.KpiConfig]:
        """
        Check if active config exists for this scope.
        Returns existing config or None.
        """
        query = select(models.KpiConfig).where(
            models.KpiConfig.kpi_code == kpi_code,
            models.KpiConfig.unit_id == unit_id,  # handles None correctly
            models.KpiConfig.officer_id == officer_id,
            models.KpiConfig.period_type == period_type,
            models.KpiConfig.is_active == True,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def list_targets(
        self,
        fiscal_year: Optional[int] = None,
        kpi_code: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> List[models.KpiTarget]:
        """
        List annual KPI targets with filters.
        Used by admin router.
        """
        query = select(models.KpiTarget)
        
        if is_active is not None:
            query = query.where(models.KpiTarget.is_active == is_active)
        
        if fiscal_year:
            query = query.where(models.KpiTarget.fiscal_year == fiscal_year)
        if kpi_code:
            query = query.where(models.KpiTarget.kpi_code == kpi_code)
        
        query = query.order_by(
            models.KpiTarget.fiscal_year.desc(),
            models.KpiTarget.kpi_code
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def check_duplicate_target_exists(
        self,
        kpi_code: str,
        fiscal_year: int,
        unit_id: Optional[int] = None,
        officer_id: Optional[int] = None,
    ) -> Optional[models.KpiTarget]:
        """
        Check if active annual target exists for this scope + year.
        Returns existing target or None.
        
        Uniqueness is determined by: kpi_code + fiscal_year + unit_id + officer_id
        """
        # Build conditions carefully for NULL equality
        conditions = [
            models.KpiTarget.kpi_code == kpi_code,
            models.KpiTarget.fiscal_year == fiscal_year,
            models.KpiTarget.is_active == True,
        ]
        
        # Handle NULL comparisons correctly
        if unit_id is None:
            conditions.append(models.KpiTarget.unit_id.is_(None))
        else:
            conditions.append(models.KpiTarget.unit_id == unit_id)
        
        if officer_id is None:
            conditions.append(models.KpiTarget.officer_id.is_(None))
        else:
            conditions.append(models.KpiTarget.officer_id == officer_id)
        
        query = select(models.KpiTarget).where(and_(*conditions))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    # =========================================================================
    # PHASE: KPI Service Refactoring Support Methods
    # =========================================================================

    async def get_user_unit_id(self, user_id: int) -> Optional[int]:
        """
        Get user's unit_id for KPI inheritance lookup.
        
        Args:
            user_id: User ID to lookup
            
        Returns:
            unit_id or None if user not found
        """
        result = await self.db.execute(
            select(models.User.unit_id).where(models.User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_annual_target_with_priority(
        self,
        officer_id: int,
        kpi_code: str,
        fiscal_year: int,
        unit_id: Optional[int] = None,
    ) -> Optional[models.KpiTarget]:
        """
        Get annual target with inheritance: officer → unit → global.
        
        Priority order:
        1. Officer-specific target (if exists)
        2. Unit-level target (if unit_id provided and exists)
        3. Global target (unit_id IS NULL, officer_id IS NULL)
        
        Args:
            officer_id: Officer ID
            kpi_code: KPI code (e.g., "enrollments")
            fiscal_year: Fiscal year
            unit_id: Officer's unit_id for fallback
            
        Returns:
            KpiTarget with highest priority or None
        """
        result = await self.db.execute(
            select(models.KpiTarget)
            .where(
                or_(
                    models.KpiTarget.officer_id == officer_id,
                    and_(
                        models.KpiTarget.unit_id == unit_id,
                        models.KpiTarget.officer_id.is_(None)
                    ) if unit_id else False,
                    and_(
                        models.KpiTarget.unit_id.is_(None),
                        models.KpiTarget.officer_id.is_(None)
                    )
                ),
                models.KpiTarget.kpi_code == kpi_code,
                models.KpiTarget.fiscal_year == fiscal_year,
                models.KpiTarget.is_active == True,
            )
            .order_by(
                # Priority: officer-specific first, then unit, then global
                models.KpiTarget.officer_id.desc().nulls_last(),
                models.KpiTarget.unit_id.desc().nulls_last(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_enrollments_ytd(
        self,
        officer_id: int,
        fiscal_year: int,
    ) -> int:
        """
        Count leads with final pipeline stage + positive KPI outcome.
        
        Uses:
        - PipelineStage.is_final_stage == True
        - ConsultationStatus.counts_for_funnel == True
        
        Args:
            officer_id: Officer ID
            fiscal_year: Fiscal year
            
        Returns:
            Count of qualifying enrollments
        """
        from datetime import datetime, timezone
        
        result = await self.db.execute(
            select(func.count(models.Lead.id))
            .join(models.PipelineStage, models.Lead.pipeline_stage_id == models.PipelineStage.id)
            .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.PipelineStage.is_final_stage == True,
                models.ConsultationStatus.counts_for_funnel == True,
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at >= datetime(fiscal_year, 1, 1, tzinfo=timezone.utc),
                models.Lead.updated_at < datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc),
            )
        )
        return result.scalar() or 0

    async def update_achieved_ytd(
        self,
        officer_id: int,
        kpi_code: str,
        fiscal_year: int,
        ytd_value: int,
    ) -> None:
        """
        Update achieved_ytd and last_sync_at for officer's target.
        
        Args:
            officer_id: Officer ID
            kpi_code: KPI code
            fiscal_year: Fiscal year
            ytd_value: New YTD value
        """
        from datetime import datetime, timezone
        from sqlalchemy import update
        
        await self.db.execute(
            update(models.KpiTarget)
            .where(
                models.KpiTarget.officer_id == officer_id,
                models.KpiTarget.kpi_code == kpi_code,
                models.KpiTarget.fiscal_year == fiscal_year,
            )
            .values(
                achieved_ytd=ytd_value,
                last_sync_at=datetime.now(timezone.utc),
            )
        )

    async def get_config_by_id(self, config_id: int) -> Optional[models.KpiConfig]:
        """
        Get KPI config by ID.
        
        Uses base repository get_by_id method.
        
        Args:
            config_id: Config ID
            
        Returns:
            KpiConfig or None
        """
        return await self.get_by_id(config_id)

    async def get_target_by_id(self, target_id: int) -> Optional[models.KpiTarget]:
        """
        Get KPI target by ID.
        
        Note: KpiTarget is a different model from KpiConfig.
        
        Args:
            target_id: Target ID
            
        Returns:
            KpiTarget or None
        """
        result = await self.db.execute(
            select(models.KpiTarget).where(models.KpiTarget.id == target_id)
        )
        return result.scalar_one_or_none()

