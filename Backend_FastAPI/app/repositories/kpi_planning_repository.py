# app/repositories/kpi_planning_repository.py
"""
KPI Planning Repository — Data access for KPI Plans and Plan Months (Phase A5)

Provides queries for:
- Plan CRUD with scope filtering (IDOR: manager sees only own unit)
- Plan month retrieval with plan eager loading
- Active plan lookup by scope (unit/officer/fiscal_year)
- Pagination support for list endpoints
"""
from typing import Any, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.config import KpiPlan, KpiPlanMonth
from app.repositories.base import BaseRepository


class KpiPlanningRepository(BaseRepository[KpiPlan]):
    """Repository for KPI Plan data access."""

    def __init__(self, db: AsyncSession):
        super().__init__(db, KpiPlan)

    async def get_filtered(
        self, skip: int = 0, limit: int = 100, **filters
    ) -> Tuple[int, List[KpiPlan]]:
        """Implementation of abstract method — delegates to list_plans."""
        plans, total = await self.list_plans(
            fiscal_year=filters.get("fiscal_year"),
            unit_id=filters.get("unit_id"),
            officer_id=filters.get("officer_id"),
            is_active=filters.get("is_active", True),
            scope_unit_id=filters.get("scope_unit_id"),
            skip=skip,
            limit=limit,
        )
        return total, plans

    # =========================================================================
    # PLAN RETRIEVAL
    # =========================================================================

    async def get_plan_by_id(
        self,
        plan_id: int,
        include_inactive: bool = False,
        with_months: bool = False,
    ) -> Optional[KpiPlan]:
        """
        Get a single plan by ID.

        Args:
            plan_id: Plan ID
            include_inactive: If False (default), only return active plans
            with_months: If True, eager-load KpiPlanMonth records
        """
        query = select(KpiPlan).where(KpiPlan.id == plan_id)

        if not include_inactive:
            query = query.where(KpiPlan.is_active == True)  # noqa: E712

        if with_months:
            query = query.options(selectinload(KpiPlan.months))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_month_with_plan(
        self,
        month_id: int,
        include_inactive_plan: bool = False,
    ) -> Optional[KpiPlanMonth]:
        """
        Get a plan month by ID, eager-loading the parent plan.
        Used by IDOR dependency to check plan.unit_id against manager scope.

        Args:
            month_id: KpiPlanMonth ID
            include_inactive_plan: If False, only return if parent plan is active
        """
        query = (
            select(KpiPlanMonth)
            .options(selectinload(KpiPlanMonth.plan))
            .where(KpiPlanMonth.id == month_id)
        )

        result = await self.db.execute(query)
        month = result.scalar_one_or_none()

        if month is None:
            return None

        # Filter by parent plan active status
        if not include_inactive_plan and not month.plan.is_active:
            return None

        return month

    # =========================================================================
    # PLAN LISTING (with IDOR scope + pagination)
    # =========================================================================

    async def list_plans(
        self,
        fiscal_year: Optional[int] = None,
        unit_id: Optional[int] = None,
        officer_id: Optional[int] = None,
        is_active: Optional[bool] = True,
        scope_unit_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[KpiPlan], int]:
        """
        List plans with filters and pagination.

        Args:
            fiscal_year: Filter by year
            unit_id: Filter by specific unit (admin use)
            officer_id: Filter by specific officer
            is_active: Filter by active status (None = all)
            scope_unit_id: IDOR scope — when set, forces unit_id filter
                          (manager can only see own unit's plans)
            skip: Pagination offset
            limit: Pagination page size

        Returns:
            Tuple of (plans list, total count)
        """
        filters: list[Any] = []

        # IDOR: scope_unit_id overrides unit_id filter
        effective_unit_id = scope_unit_id if scope_unit_id is not None else unit_id
        if effective_unit_id is not None:
            filters.append(KpiPlan.unit_id == effective_unit_id)

        if fiscal_year is not None:
            filters.append(KpiPlan.fiscal_year == fiscal_year)
        if officer_id is not None:
            filters.append(KpiPlan.officer_id == officer_id)
        if is_active is not None:
            filters.append(KpiPlan.is_active == is_active)

        # Count query
        count_query = select(func.count(KpiPlan.id))
        if filters:
            count_query = count_query.where(*filters)
        total = (await self.db.execute(count_query)).scalar_one()

        # Data query
        data_query = (
            select(KpiPlan)
            .options(selectinload(KpiPlan.months))
            .order_by(KpiPlan.fiscal_year.desc(), KpiPlan.unit_id, KpiPlan.officer_id)
        )
        if filters:
            data_query = data_query.where(*filters)
        data_query = data_query.offset(skip).limit(limit)

        result = await self.db.execute(data_query)
        plans = list(result.scalars().unique().all())

        return plans, total

    # =========================================================================
    # SCOPE LOOKUP
    # =========================================================================

    async def get_active_plan_by_scope(
        self,
        unit_id: int,
        fiscal_year: int,
        officer_id: Optional[int] = None,
        with_months: bool = True,
    ) -> Optional[KpiPlan]:
        """
        Find the active plan for a specific scope.

        Args:
            unit_id: Organization unit ID
            fiscal_year: Fiscal year
            officer_id: Officer ID (None = unit plan)
            with_months: Eager-load months
        """
        query = select(KpiPlan).where(
            KpiPlan.unit_id == unit_id,
            KpiPlan.fiscal_year == fiscal_year,
            KpiPlan.is_active == True,  # noqa: E712
        )

        if officer_id is not None:
            query = query.where(KpiPlan.officer_id == officer_id)
        else:
            query = query.where(KpiPlan.officer_id.is_(None))

        if with_months:
            query = query.options(selectinload(KpiPlan.months))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def check_duplicate_active_plan(
        self,
        unit_id: int,
        fiscal_year: int,
        officer_id: Optional[int] = None,
        exclude_plan_id: Optional[int] = None,
    ) -> bool:
        """
        Check if an active plan already exists for the given scope.
        Used by service before create/update.

        Args:
            exclude_plan_id: Exclude this plan from check (for updates)

        Returns:
            True if duplicate exists
        """
        filters = [
            KpiPlan.unit_id == unit_id,
            KpiPlan.fiscal_year == fiscal_year,
            KpiPlan.is_active == True,  # noqa: E712
        ]
        if officer_id is not None:
            filters.append(KpiPlan.officer_id == officer_id)
        else:
            filters.append(KpiPlan.officer_id.is_(None))

        if exclude_plan_id is not None:
            filters.append(KpiPlan.id != exclude_plan_id)

        result = await self.db.execute(
            select(func.count(KpiPlan.id)).where(*filters)
        )
        return result.scalar_one() > 0

    async def sum_officer_quotas(
        self,
        unit_id: int,
        fiscal_year: int,
        exclude_officer_id: Optional[int] = None,
        lock_unit_plan: bool = False,
    ) -> int:
        """
        Sum annual_enrollment_target for all active officer plans in a unit/year.

        Args:
            exclude_officer_id: Exclude this officer from sum (for update validation)
            lock_unit_plan: If True, SELECT FOR UPDATE on unit plan row to serialize
                           concurrent inserts (prevents race in quota validation)
        Returns:
            Sum of officer quotas (0 if no officer plans exist)
        """
        if lock_unit_plan:
            # Lock unit plan row to serialize concurrent quota operations
            await self.db.execute(
                select(KpiPlan.id)
                .where(
                    KpiPlan.unit_id == unit_id,
                    KpiPlan.fiscal_year == fiscal_year,
                    KpiPlan.officer_id.is_(None),
                    KpiPlan.is_active == True,  # noqa: E712
                )
                .with_for_update()
            )

        query = select(func.coalesce(func.sum(KpiPlan.annual_enrollment_target), 0)).where(
            KpiPlan.unit_id == unit_id,
            KpiPlan.fiscal_year == fiscal_year,
            KpiPlan.officer_id.isnot(None),
            KpiPlan.is_active == True,  # noqa: E712
        )
        if exclude_officer_id is not None:
            query = query.where(KpiPlan.officer_id != exclude_officer_id)
        result = (await self.db.execute(query)).scalar()
        return int(result)

    # =========================================================================
    # PLAN MONTHS
    # =========================================================================

    async def list_plan_months(
        self,
        plan_id: int,
    ) -> List[KpiPlanMonth]:
        """
        Get all 12 months for a plan, ordered by month asc.
        """
        result = await self.db.execute(
            select(KpiPlanMonth)
            .where(KpiPlanMonth.plan_id == plan_id)
            .order_by(KpiPlanMonth.month.asc())
        )
        return list(result.scalars().all())
