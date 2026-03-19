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
        period_type: str = "daily",
        unit_id: Optional[int] = None,
    ) -> Optional[float]:
        """Get officer-specific evergreen KPI target (effective_month IS NULL)."""
        filters = [
            models.KpiConfig.officer_id == officer_id,
            models.KpiConfig.kpi_code == kpi_code,
            models.KpiConfig.period_type == period_type,
            models.KpiConfig.effective_month.is_(None),
            models.KpiConfig.is_active == True,
        ]
        if unit_id is not None:
            filters.append(models.KpiConfig.unit_id == unit_id)
        result = await self.db.execute(
            select(models.KpiConfig.target_value).where(*filters)
        )
        return result.scalar_one_or_none()

    async def get_target_by_unit(
        self,
        kpi_code: str,
        unit_id: int,
        period_type: str = "daily"
    ) -> Optional[float]:
        """Get unit-level evergreen KPI target (effective_month IS NULL)."""
        result = await self.db.execute(
            select(models.KpiConfig.target_value)
            .where(
                models.KpiConfig.unit_id == unit_id,
                models.KpiConfig.officer_id.is_(None),
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.effective_month.is_(None),
                models.KpiConfig.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_global_target(
        self,
        kpi_code: str,
        period_type: str = "daily"
    ) -> Optional[float]:
        """Get global evergreen KPI target (effective_month IS NULL)."""
        result = await self.db.execute(
            select(models.KpiConfig.target_value)
            .where(
                models.KpiConfig.unit_id.is_(None),
                models.KpiConfig.officer_id.is_(None),
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.effective_month.is_(None),
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
        default: float = 0,
        effective_year: Optional[int] = None,
        effective_month: Optional[int] = None,
    ) -> float:
        """
        Get KPI target with inheritance chain + temporal resolution (Phase B8).

        Resolution order (spec §8.4):
        1. Monthly record matching effective_year/month (officer → unit → global)
        2. Evergreen record effective_month IS NULL (officer → unit → global)
        3. Hardcoded DEFAULT_KPIS

        If effective_year/month not provided, falls back to evergreen-only
        (original behavior — backward compatible).
        """
        # --- Phase B8: Try monthly records first (if effective_date provided) ---
        if effective_year is not None and effective_month is not None:
            target = await self._get_monthly_target(
                kpi_code, period_type, effective_year, effective_month,
                officer_id=officer_id, unit_id=unit_id,
            )
            if target is not None:
                return target

        # --- Evergreen fallback (original chain: officer → unit → global) ---
        if officer_id:
            target = await self.get_target_by_officer(kpi_code, officer_id, period_type, unit_id=unit_id)
            if target is not None:
                return target

        if unit_id:
            target = await self.get_target_by_unit(kpi_code, unit_id, period_type)
            if target is not None:
                return target

        target = await self.get_global_target(kpi_code, period_type)
        if target is not None:
            return target

        return default

    async def _get_monthly_target(
        self,
        kpi_code: str,
        period_type: str,
        effective_year: int,
        effective_month: int,
        officer_id: Optional[int] = None,
        unit_id: Optional[int] = None,
    ) -> Optional[float]:
        """
        Find monthly KpiConfig record with inheritance (Phase B8).

        Tries officer-specific → unit-level → global monthly records.
        Only matches records with effective_month IS NOT NULL.
        """
        # 1. Officer-specific monthly (scoped to unit if provided)
        if officer_id:
            filters = [
                models.KpiConfig.officer_id == officer_id,
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.effective_year == effective_year,
                models.KpiConfig.effective_month == effective_month,
                models.KpiConfig.is_active == True,  # noqa: E712
            ]
            if unit_id is not None:
                filters.append(models.KpiConfig.unit_id == unit_id)
            result = await self.db.execute(
                select(models.KpiConfig.target_value).where(*filters)
            )
            val = result.scalar_one_or_none()
            if val is not None:
                return val

        # 2. Unit-level monthly
        if unit_id:
            result = await self.db.execute(
                select(models.KpiConfig.target_value).where(
                    models.KpiConfig.unit_id == unit_id,
                    models.KpiConfig.officer_id.is_(None),
                    models.KpiConfig.kpi_code == kpi_code,
                    models.KpiConfig.period_type == period_type,
                    models.KpiConfig.effective_year == effective_year,
                    models.KpiConfig.effective_month == effective_month,
                    models.KpiConfig.is_active == True,  # noqa: E712
                )
            )
            val = result.scalar_one_or_none()
            if val is not None:
                return val

        # 3. Global monthly
        result = await self.db.execute(
            select(models.KpiConfig.target_value).where(
                models.KpiConfig.unit_id.is_(None),
                models.KpiConfig.officer_id.is_(None),
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.effective_year == effective_year,
                models.KpiConfig.effective_month == effective_month,
                models.KpiConfig.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()
    
    async def get_resolved_kpi_config(
        self,
        kpi_code: str,
        officer_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        period_type: str = "daily",
        effective_year: Optional[int] = None,
        effective_month: Optional[int] = None,
    ) -> Optional[models.KpiConfig]:
        """
        Resolve the full KpiConfig record (not just target_value) using the
        same inheritance chain as get_kpi_target_with_inheritance.

        Returns the winning KpiConfig object, or None if only default applies.
        Used by P1 to check source_plan_id for is_unit_target.
        """
        # 1. Try monthly records first
        if effective_year is not None and effective_month is not None:
            for scope_filters in self._inheritance_scopes(kpi_code, period_type, officer_id, unit_id):
                result = await self.db.execute(
                    select(models.KpiConfig).where(
                        *scope_filters,
                        models.KpiConfig.effective_year == effective_year,
                        models.KpiConfig.effective_month == effective_month,
                        models.KpiConfig.is_active == True,  # noqa: E712
                    )
                )
                config = result.scalar_one_or_none()
                if config is not None:
                    return config

        # 2. Evergreen fallback
        for scope_filters in self._inheritance_scopes(kpi_code, period_type, officer_id, unit_id):
            result = await self.db.execute(
                select(models.KpiConfig).where(
                    *scope_filters,
                    models.KpiConfig.effective_month.is_(None),
                    models.KpiConfig.is_active == True,  # noqa: E712
                )
            )
            config = result.scalar_one_or_none()
            if config is not None:
                return config

        return None

    def _inheritance_scopes(self, kpi_code, period_type, officer_id, unit_id):
        """Yield filter tuples for officer → unit → global inheritance chain."""
        base = [
            models.KpiConfig.kpi_code == kpi_code,
            models.KpiConfig.period_type == period_type,
        ]
        if officer_id:
            filters = base + [models.KpiConfig.officer_id == officer_id]
            if unit_id is not None:
                filters.append(models.KpiConfig.unit_id == unit_id)
            yield filters
        if unit_id:
            yield base + [
                models.KpiConfig.unit_id == unit_id,
                models.KpiConfig.officer_id.is_(None),
            ]
        yield base + [
            models.KpiConfig.unit_id.is_(None),
            models.KpiConfig.officer_id.is_(None),
        ]

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
        include_global: bool = False,
    ) -> List[models.KpiConfig]:
        """
        List all KPI configs with filters.
        include_global: when True + unit_id set, also returns global configs (unit_id IS NULL).
        Used by admin router (IDOR: manager sees unit + global).
        """
        query = select(models.KpiConfig)

        if kpi_code:
            query = query.where(models.KpiConfig.kpi_code == kpi_code)
        if unit_id is not None:
            if include_global:
                # Manager scope: unit's configs + "true global" (unit=NULL AND officer=NULL)
                query = query.where(
                    or_(
                        models.KpiConfig.unit_id == unit_id,
                        and_(
                            models.KpiConfig.unit_id.is_(None),
                            models.KpiConfig.officer_id.is_(None),
                        ),
                    )
                )
            else:
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
        unit_id: Optional[int] = None,
    ) -> List[models.KpiTarget]:
        """
        List annual KPI targets with filters.
        unit_id: IDOR scope filter — when set, returns only targets for this unit + global.
        Used by admin router.
        """
        query = select(models.KpiTarget)

        if is_active is not None:
            query = query.where(models.KpiTarget.is_active == is_active)

        if fiscal_year:
            query = query.where(models.KpiTarget.fiscal_year == fiscal_year)
        if kpi_code:
            query = query.where(models.KpiTarget.kpi_code == kpi_code)
        if unit_id is not None:
            # Manager scope: unit's targets + "true global" (unit=NULL AND officer=NULL)
            query = query.where(
                or_(
                    models.KpiTarget.unit_id == unit_id,
                    and_(
                        models.KpiTarget.unit_id.is_(None),
                        models.KpiTarget.officer_id.is_(None),
                    ),
                )
            )
        
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
            kpi_code: KPI code (e.g., "enrollments_annual")
            fiscal_year: Fiscal year
            unit_id: Officer's unit_id for fallback
            
        Returns:
            KpiTarget with highest priority or None
        """
        # R0.6: Auto-resolve unit_id to prevent matching stale targets
        if unit_id is None:
            unit_id = await self.get_user_unit_id(officer_id)

        # Build inheritance chain: officer (scoped to unit) → unit → global
        # When unit_id is known, constrain officer branch to current unit
        # to avoid matching stale targets from a previous unit after transfer.
        if unit_id is not None:
            officer_clause = and_(
                models.KpiTarget.officer_id == officer_id,
                models.KpiTarget.unit_id == unit_id,
            )
            unit_clause = and_(
                models.KpiTarget.unit_id == unit_id,
                models.KpiTarget.officer_id.is_(None),
            )
        else:
            # Officer has no unit — only match global-scoped targets
            officer_clause = and_(
                models.KpiTarget.officer_id == officer_id,
                models.KpiTarget.unit_id.is_(None),
            )
            unit_clause = False  # No unit to fallback to

        global_clause = and_(
            models.KpiTarget.unit_id.is_(None),
            models.KpiTarget.officer_id.is_(None),
        )

        result = await self.db.execute(
            select(models.KpiTarget)
            .where(
                or_(officer_clause, unit_clause, global_clause),
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
        as_of_date=None,
    ) -> int:
        """
        Count leads with final pipeline stage + positive outcome for enrollment KPI.

        Uses (defense-in-depth):
        - PipelineStage.is_final_stage == True
        - ConsultationStatus.counts_for_funnel == True
        - ConsultationStatus.outcome_type == "positive"  (excludes DROPPED_OUT)

        Args:
            officer_id: Officer ID
            fiscal_year: Fiscal year
            as_of_date: Optional date upper bound for historical periods (R0.5)

        Returns:
            Count of qualifying enrollments
        """
        from datetime import datetime, timezone, timedelta

        start = datetime(fiscal_year, 1, 1, tzinfo=timezone.utc)
        end = datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc)

        # R0.5: When as_of_date provided, cap upper bound
        if as_of_date is not None:
            as_of_end = datetime(as_of_date.year, as_of_date.month, as_of_date.day, tzinfo=timezone.utc) + timedelta(days=1)
            end = min(end, as_of_end)

        result = await self.db.execute(
            select(func.count(models.Lead.id))
            .join(models.PipelineStage, models.Lead.pipeline_stage_id == models.PipelineStage.id)
            .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.PipelineStage.is_final_stage == True,
                models.ConsultationStatus.counts_for_funnel == True,
                models.ConsultationStatus.outcome_type == "positive",
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at >= start,
                models.Lead.updated_at < end,
            )
        )
        return result.scalar() or 0

    async def count_enrollments_in_period(
        self,
        officer_id: int,
        start_date,
        end_date,
    ) -> int:
        """
        Count enrollments for an officer within a date range.

        Same triple-check join as count_enrollments_ytd but with arbitrary date range.
        Used by officer dashboard for enrollments_monthly metric.
        """
        result = await self.db.execute(
            select(func.count(models.Lead.id))
            .join(models.PipelineStage, models.Lead.pipeline_stage_id == models.PipelineStage.id)
            .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id == officer_id,
                models.PipelineStage.is_final_stage == True,
                models.ConsultationStatus.counts_for_funnel == True,
                models.ConsultationStatus.outcome_type == "positive",
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at >= start_date,
                models.Lead.updated_at < end_date,
            )
        )
        return result.scalar() or 0

    async def count_enrollments_in_period_batch(
        self,
        officer_ids: List[int],
        start_date,
        end_date,
    ) -> int:
        """
        Count enrollments for multiple officers within a date range.

        Same semantics as count_enrollments_in_period() but for batch aggregation.
        Uses updated_at (event-based: when enrollment happened) not created_at.
        """
        result = await self.db.execute(
            select(func.count(models.Lead.id))
            .join(models.PipelineStage, models.Lead.pipeline_stage_id == models.PipelineStage.id)
            .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.PipelineStage.is_final_stage == True,
                models.ConsultationStatus.counts_for_funnel == True,
                models.ConsultationStatus.outcome_type == "positive",
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at >= start_date,
                models.Lead.updated_at < end_date,
            )
        )
        return result.scalar() or 0

    async def count_enrollments_ytd_batch(
        self,
        officer_ids: List[int],
        fiscal_year: int,
        as_of_date=None,
    ) -> int:
        """
        Count enrollments for multiple officers in a fiscal year.

        Same semantics as count_enrollments_ytd() but for batch aggregation.
        Uses updated_at (event-based: when enrollment happened) not created_at.

        Args:
            as_of_date: Optional date upper bound for historical periods (R0.5)
        """
        from datetime import datetime, timezone, timedelta

        start = datetime(fiscal_year, 1, 1, tzinfo=timezone.utc)
        end = datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc)

        # R0.5: When as_of_date provided, cap upper bound
        if as_of_date is not None:
            as_of_end = datetime(as_of_date.year, as_of_date.month, as_of_date.day, tzinfo=timezone.utc) + timedelta(days=1)
            end = min(end, as_of_end)

        result = await self.db.execute(
            select(func.count(models.Lead.id))
            .join(models.PipelineStage, models.Lead.pipeline_stage_id == models.PipelineStage.id)
            .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.PipelineStage.is_final_stage == True,
                models.ConsultationStatus.counts_for_funnel == True,
                models.ConsultationStatus.outcome_type == "positive",
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at >= start,
                models.Lead.updated_at < end,
            )
        )
        return result.scalar() or 0

    async def count_enrollments_ytd_grouped(
        self,
        officer_ids: List[int],
        fiscal_year: int,
    ) -> Dict[int, int]:
        """
        Count enrollments per officer, returning {officer_id: count}.

        Same triple-check join as count_enrollments_ytd but with GROUP BY.
        Returns dict with entry for each officer_id in input (0 if no enrollments).
        """
        from datetime import datetime, timezone

        if not officer_ids:
            return {}

        start = datetime(fiscal_year, 1, 1, tzinfo=timezone.utc)
        end = datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc)

        result = await self.db.execute(
            select(
                models.Lead.assigned_officer_id,
                func.count(models.Lead.id),
            )
            .join(models.PipelineStage, models.Lead.pipeline_stage_id == models.PipelineStage.id)
            .join(models.ConsultationStatus, models.Lead.consultation_status_id == models.ConsultationStatus.id)
            .where(
                models.Lead.assigned_officer_id.in_(officer_ids),
                models.PipelineStage.is_final_stage == True,
                models.ConsultationStatus.counts_for_funnel == True,
                models.ConsultationStatus.outcome_type == "positive",
                models.Lead.deleted_at.is_(None),
                models.Lead.updated_at >= start,
                models.Lead.updated_at < end,
            )
            .group_by(models.Lead.assigned_officer_id)
        )
        rows = result.all()
        counts = {oid: cnt for oid, cnt in rows}
        # Ensure every officer_id in input has an entry
        return {oid: counts.get(oid, 0) for oid in officer_ids}

    async def update_achieved_ytd(
        self,
        target_id: int,
        ytd_value: int,
    ) -> None:
        """
        Update achieved_ytd and last_sync_at for a specific KpiTarget by PK.

        Uses target_id (primary key) to avoid ambiguous multi-row updates
        when an officer has multiple target records across units.

        Args:
            target_id: KpiTarget primary key
            ytd_value: New YTD value
        """
        from datetime import datetime, timezone
        from sqlalchemy import update

        await self.db.execute(
            update(models.KpiTarget)
            .where(
                models.KpiTarget.id == target_id,
                models.KpiTarget.is_active == True,
            )
            .values(
                achieved_ytd=ytd_value,
                last_sync_at=datetime.now(timezone.utc),
            )
        )

    async def get_active_plan_weights(
        self,
        officer_id: int,
        unit_id: Optional[int],
        fiscal_year: int,
    ) -> tuple[bool, Optional[list[float]]]:
        """
        Get seasonal_weights from active KpiPlan (officer → unit fallback).

        Returns (plan_found, weights):
        - (False, None): No active plan exists
        - (True, None): Plan exists but seasonal_weights is NULL (use defaults)
        - (True, [...]): Plan exists with explicit weights
        """
        from ..models.config import KpiPlan

        # 1. Try officer-specific plan (scoped to unit!)
        if unit_id is not None:
            result = await self.db.execute(
                select(KpiPlan.id, KpiPlan.seasonal_weights)
                .where(
                    KpiPlan.officer_id == officer_id,
                    KpiPlan.unit_id == unit_id,
                    KpiPlan.fiscal_year == fiscal_year,
                    KpiPlan.is_active == True,
                )
                .limit(1)
            )
            row = result.first()
            if row is not None:
                return (True, row.seasonal_weights)

        # 2. Fallback to unit plan
        if unit_id is not None:
            result = await self.db.execute(
                select(KpiPlan.id, KpiPlan.seasonal_weights)
                .where(
                    KpiPlan.unit_id == unit_id,
                    KpiPlan.officer_id.is_(None),
                    KpiPlan.fiscal_year == fiscal_year,
                    KpiPlan.is_active == True,
                )
                .limit(1)
            )
            row = result.first()
            if row is not None:
                return (True, row.seasonal_weights)

        return (False, None)

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

