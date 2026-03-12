# app/services/kpi_resolver.py
"""
KPI Target Resolver — Consolidated resolution logic for monthly + annual targets.

Consolidates duplicated target resolution from:
- kpi_service.get_kpi_target_source_info() (monthly KpiConfig)
- kpi_service.get_annual_target_progress() (annual KpiTarget)
- kpi_setup_service.get_coverage_report() (inherited officer estimates)

Two main functions:
1. resolve_target() — Monthly KpiConfig resolution with source metadata
2. resolve_annual_progress() — Annual target virtual resolution with inheritance
"""
import structlog
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

log = structlog.get_logger(__name__)


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class TargetResolution:
    """Result of monthly KpiConfig resolution with source metadata."""

    value: float
    """The resolved target value."""

    source_type: Literal["officer", "unit", "global", "default"]
    """Where the target was resolved from in the inheritance chain."""

    source_plan_id: Optional[int]
    """KpiConfig.source_plan_id — links back to the KpiPlan that generated this config."""

    is_unit_target: bool
    """True when resolved config has source_plan_id pointing to a plan with officer_id IS NULL."""

    config_record: Optional[models.KpiConfig]
    """The resolved KpiConfig object. None when falling back to catalog default."""


@dataclass
class AnnualProgressResolution:
    """Result of annual target resolution with inheritance and progress tracking."""

    annual_target: int
    """The resolved annual enrollment target."""

    achieved_ytd: int
    """Year-to-date achievement count."""

    resolution_kind: Literal["assigned", "inherited_estimate"]
    """'assigned' = direct target/plan for this officer. 'inherited_estimate' = split from unit/global."""

    source_description: str
    """Human-readable source, e.g. 'Officer KpiTarget', 'Unit plan (uoc tinh)'."""

    target_record: Optional[models.KpiTarget]
    """The officer's own KpiTarget if it exists (for last_sync_at access)."""

    seasonal_weights: Optional[List[float]]
    """Resolved seasonal weights from plan if available."""


@dataclass
class AnnualResolutionContext:
    """Pre-fetched data for batch-aware annual resolution.

    Callers build this context from either:
    - Single-officer on-demand queries (_build_single_officer_context)
    - Batch pre-fetched data (coverage report)

    The pure rule function resolve_officer_annual_from_context() runs from
    this context without any DB calls, ensuring single-path rule logic.
    """

    officer_targets: Dict[int, Any]
    """officer_id → officer-scoped KpiTarget (step 1)."""

    officer_plans: Dict[int, Any]
    """officer_id → officer-scoped KpiPlan (step 2)."""

    unit_plans: Dict[int, Any]
    """unit_id → unit-scoped KpiPlan, officer_id IS NULL (step 3)."""

    unit_targets: Dict[int, Any]
    """unit_id → unit-scoped KpiTarget, officer_id IS NULL (step 4)."""

    global_target: Optional[Any]
    """Global KpiTarget, unit_id IS NULL, officer_id IS NULL (step 5)."""

    unit_officer_counts: Dict[int, int]
    """unit_id → count of active officers in that unit."""

    total_active_officers: int
    """Total active officers across all active units (for global split)."""

    ytd_by_officer: Dict[int, int]
    """officer_id → pre-resolved achieved_ytd count."""

    officer_unit_map: Dict[int, Optional[int]]
    """officer_id → unit_id mapping."""


# =============================================================================
# 1. resolve_target() — Monthly KpiConfig resolution
# =============================================================================


async def resolve_target(
    db: AsyncSession,
    kpi_code: str,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    period_type: Optional[str] = None,
    effective_date: Optional[date] = None,
) -> TargetResolution:
    """
    Resolve a monthly KPI target value using the full inheritance chain,
    enriched with source metadata.

    Wraps KpiRepository.get_resolved_kpi_config() and adds:
    - source_type classification (officer/unit/global/default)
    - is_unit_target detection via source_plan_id -> KpiPlan.officer_id
    - Catalog default fallback with metadata

    Args:
        db: Async database session
        kpi_code: KPI identifier (e.g. "consultations_daily")
        officer_id: Officer scope (None = skip officer-level lookup)
        unit_id: Unit scope (None = skip unit-level lookup)
        period_type: Period type override. If None, auto-derived from kpi_catalog.
            If provided but mismatches catalog, logs warning and uses catalog value.
        effective_date: Date for temporal resolution. If None, uses current month.

    Returns:
        TargetResolution with value, source metadata, and the config record.
    """
    from ..repositories import KpiRepository
    from .kpi_catalog import get_period_type as catalog_get_period_type, get_default

    # --- Resolve period_type ---
    catalog_period_type = catalog_get_period_type(kpi_code)
    if period_type is None:
        period_type = catalog_period_type
    elif period_type != catalog_period_type:
        log.warning(
            "period_type mismatch with catalog, using catalog value",
            kpi_code=kpi_code,
            provided=period_type,
            catalog=catalog_period_type,
        )
        period_type = catalog_period_type

    # --- Resolve effective year/month ---
    if effective_date is not None:
        effective_year = effective_date.year
        effective_month = effective_date.month
    else:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        effective_year = now.year
        effective_month = now.month

    # --- Get the full KpiConfig record via repository ---
    repo = KpiRepository(db)
    config = await repo.get_resolved_kpi_config(
        kpi_code=kpi_code,
        officer_id=officer_id,
        unit_id=unit_id,
        period_type=period_type,
        effective_year=effective_year,
        effective_month=effective_month,
    )

    # --- Determine value ---
    if config is not None:
        value = float(config.target_value)
    else:
        value = float(get_default(kpi_code))

    # --- Determine source_type ---
    source_type = _classify_source_type(config)

    # --- Determine source_plan_id ---
    source_plan_id = config.source_plan_id if config is not None else None

    # --- Determine is_unit_target ---
    is_unit_target = False
    if config is not None and config.source_plan_id is not None:
        from ..models.config import KpiPlan

        plan_officer = (
            await db.execute(
                select(KpiPlan.officer_id).where(KpiPlan.id == config.source_plan_id)
            )
        ).scalar_one_or_none()
        if plan_officer is None:
            is_unit_target = True

    log.debug(
        "Target resolved",
        kpi_code=kpi_code,
        value=value,
        source_type=source_type,
        is_unit_target=is_unit_target,
        effective=f"{effective_year}/{effective_month}",
    )

    return TargetResolution(
        value=value,
        source_type=source_type,
        source_plan_id=source_plan_id,
        is_unit_target=is_unit_target,
        config_record=config,
    )


def _classify_source_type(
    config: Optional[models.KpiConfig],
) -> Literal["officer", "unit", "global", "default"]:
    """Classify the source type from a resolved KpiConfig record."""
    if config is None:
        return "default"
    if config.officer_id is not None:
        return "officer"
    if config.unit_id is not None:
        return "unit"
    return "global"


# =============================================================================
# 2. resolve_annual_progress() — Annual target virtual resolution
# =============================================================================


async def resolve_annual_progress(
    db: AsyncSession,
    officer_id: int,
    fiscal_year: int,
    kpi_code: str = "enrollments_annual",
    effective_date: Optional[date] = None,
) -> Optional[AnnualProgressResolution]:
    """
    Resolve annual target progress for an officer using the full priority chain.

    Builds a single-officer AnnualResolutionContext and delegates to the
    shared pure rule function resolve_officer_annual_from_context().

    Priority chain:
    1. Officer-scoped KpiTarget -> kind="assigned"
    2. Officer has own KpiPlan -> kind="assigned" (plan.annual_enrollment_target)
    3. Unit has KpiPlan -> kind="inherited_estimate" (equal split)
    4. Unit-scoped KpiTarget -> kind="inherited_estimate" (equal split)
    5. Global KpiTarget -> kind="inherited_estimate" (equal split by total org officers)
    6. None -> return None

    Args:
        db: Async database session
        officer_id: Officer to resolve for
        fiscal_year: Target fiscal year
        kpi_code: KPI code (default "enrollments_annual")
        effective_date: Optional date for historical YTD counting.
            When provided, counts enrollments up to this date instead of
            using Celery-synced snapshot.

    Returns:
        AnnualProgressResolution or None if no target can be resolved.
    """
    ctx = await _build_single_officer_context(
        db, officer_id, fiscal_year, kpi_code, effective_date
    )
    result = resolve_officer_annual_from_context(officer_id, ctx)

    if result is not None:
        log.debug(
            "Annual progress resolved",
            officer_id=officer_id,
            resolution_kind=result.resolution_kind,
            annual_target=result.annual_target,
            source=result.source_description,
        )
    else:
        log.debug(
            "No annual target resolvable for officer",
            officer_id=officer_id,
            fiscal_year=fiscal_year,
        )
    return result


# =============================================================================
# 3. BATCH-AWARE ANNUAL RESOLUTION — Shared pure rule + context builder
# =============================================================================


def resolve_officer_annual_from_context(
    officer_id: int,
    ctx: AnnualResolutionContext,
) -> Optional[AnnualProgressResolution]:
    """
    Pure annual resolution rule — no DB calls.

    Shared between single-officer path (kpi_service.get_annual_target_progress)
    and batch path (kpi_setup_service.get_coverage_report).

    Uses pre-fetched data from AnnualResolutionContext. Priority chain:
    1. Officer KpiTarget -> kind="assigned"
    2. Officer KpiPlan -> kind="assigned"
    3. Unit KpiPlan -> kind="inherited_estimate" (equal split)
    4. Unit KpiTarget -> kind="inherited_estimate" (equal split)
    5. Global KpiTarget -> kind="inherited_estimate" (equal split)
    6. None -> return None
    """
    unit_id = ctx.officer_unit_map.get(officer_id)
    ytd = ctx.ytd_by_officer.get(officer_id, 0)

    # Step 1: Officer KpiTarget
    officer_target = ctx.officer_targets.get(officer_id)
    if officer_target is not None:
        weights = _resolve_weights_from_context(officer_id, unit_id, ctx)
        return AnnualProgressResolution(
            annual_target=officer_target.annual_target,
            achieved_ytd=ytd,
            resolution_kind="assigned",
            source_description="Officer KpiTarget",
            target_record=officer_target,
            seasonal_weights=weights,
        )

    # Step 2: Officer KpiPlan
    officer_plan = ctx.officer_plans.get(officer_id)
    if officer_plan is not None:
        weights = _extract_plan_weights(officer_plan)
        return AnnualProgressResolution(
            annual_target=officer_plan.annual_enrollment_target,
            achieved_ytd=ytd,
            resolution_kind="assigned",
            source_description="Officer KpiPlan",
            target_record=None,
            seasonal_weights=weights,
        )

    # Step 3: Unit KpiPlan (equal split)
    if unit_id is not None:
        unit_plan = ctx.unit_plans.get(unit_id)
        if unit_plan is not None:
            count = ctx.unit_officer_counts.get(unit_id, 0)
            if count > 0:
                split_target = unit_plan.annual_enrollment_target // count
                weights = _extract_plan_weights(unit_plan)
                return AnnualProgressResolution(
                    annual_target=split_target,
                    achieved_ytd=ytd,
                    resolution_kind="inherited_estimate",
                    source_description=f"Unit plan (ước tính, {count} officers)",
                    target_record=None,
                    seasonal_weights=weights,
                )

    # Step 4: Unit KpiTarget (equal split)
    if unit_id is not None:
        unit_target = ctx.unit_targets.get(unit_id)
        if unit_target is not None:
            count = ctx.unit_officer_counts.get(unit_id, 0)
            if count > 0:
                split_target = unit_target.annual_target // count
                weights = _resolve_weights_from_context(officer_id, unit_id, ctx)
                return AnnualProgressResolution(
                    annual_target=split_target,
                    achieved_ytd=ytd,
                    resolution_kind="inherited_estimate",
                    source_description=f"Unit target (ước tính, {count} officers)",
                    target_record=None,
                    seasonal_weights=weights,
                )

    # Step 5: Global KpiTarget (equal split)
    if ctx.global_target is not None and ctx.total_active_officers > 0:
        split_target = ctx.global_target.annual_target // ctx.total_active_officers
        weights = _resolve_weights_from_context(officer_id, unit_id, ctx)
        return AnnualProgressResolution(
            annual_target=split_target,
            achieved_ytd=ytd,
            resolution_kind="inherited_estimate",
            source_description=f"Global target (ước tính, {ctx.total_active_officers} officers)",
            target_record=None,
            seasonal_weights=weights,
        )

    # Step 6: Nothing found
    return None


def map_resolution_to_coverage_source(
    resolution: Optional[AnnualProgressResolution],
) -> str:
    """Map resolver output to coverage report target_source contract values.

    Mapping:
        assigned → "custom"
        inherited_estimate (unit scope) → "inherited"
        inherited_estimate (global scope) → "inherited_global"
        None → "none"
    """
    if resolution is None:
        return "none"
    if resolution.resolution_kind == "assigned":
        return "custom"
    if resolution.source_description.startswith("Global"):
        return "inherited_global"
    return "inherited"


def _resolve_weights_from_context(
    officer_id: int,
    unit_id: Optional[int],
    ctx: AnnualResolutionContext,
) -> Optional[List[float]]:
    """Resolve seasonal weights from context: officer plan -> unit plan -> None."""
    officer_plan = ctx.officer_plans.get(officer_id)
    if officer_plan is not None:
        return _extract_plan_weights(officer_plan)

    if unit_id is not None:
        unit_plan = ctx.unit_plans.get(unit_id)
        if unit_plan is not None:
            return _extract_plan_weights(unit_plan)

    return None  # No plan found -> linear fallback


async def _build_single_officer_context(
    db: AsyncSession,
    officer_id: int,
    fiscal_year: int,
    kpi_code: str,
    effective_date: Optional[date],
) -> AnnualResolutionContext:
    """Build AnnualResolutionContext for a single officer (on-demand queries).

    Same query count as the old resolve_annual_progress() — no regression.
    """
    from ..repositories import KpiRepository, KpiPlanningRepository

    kpi_repo = KpiRepository(db)

    # 1. Officer -> unit mapping
    unit_id = await kpi_repo.get_user_unit_id(officer_id)

    # 2. Officer-scoped KpiTarget
    officer_target = await _get_officer_scoped_target(
        db, officer_id, kpi_code, fiscal_year, unit_id
    )
    officer_targets = {officer_id: officer_target} if officer_target else {}

    # 3-4. Plans and targets (need unit_id)
    officer_plans: Dict[int, Any] = {}
    unit_plans: Dict[int, Any] = {}
    unit_targets: Dict[int, Any] = {}
    unit_officer_counts: Dict[int, int] = {}

    if unit_id is not None:
        planning_repo = KpiPlanningRepository(db)

        # Officer's own plan
        op = await planning_repo.get_active_plan_by_scope(
            unit_id=unit_id, fiscal_year=fiscal_year,
            officer_id=officer_id, with_months=False,
        )
        if op:
            officer_plans[officer_id] = op

        # Unit plan (officer_id IS NULL)
        up = await planning_repo.get_active_plan_by_scope(
            unit_id=unit_id, fiscal_year=fiscal_year,
            officer_id=None, with_months=False,
        )
        if up:
            unit_plans[unit_id] = up

        # Unit-scoped KpiTarget
        ut = await _get_unit_scoped_target(db, kpi_code, fiscal_year, unit_id)
        if ut:
            unit_targets[unit_id] = ut

        # Active officer count for unit
        unit_officer_counts[unit_id] = await _count_active_officers_in_unit(
            db, unit_id
        )

    # 5. Global target
    global_target = await _get_global_target(db, kpi_code, fiscal_year)

    # 6. Total active officers (for global split)
    total_active = await _count_total_active_officers(db)

    # 7. Resolve YTD
    ytd = await _resolve_achieved_ytd(
        kpi_repo, officer_id, fiscal_year, effective_date, officer_target
    )

    return AnnualResolutionContext(
        officer_targets=officer_targets,
        officer_plans=officer_plans,
        unit_plans=unit_plans,
        unit_targets=unit_targets,
        global_target=global_target,
        unit_officer_counts=unit_officer_counts,
        total_active_officers=total_active,
        ytd_by_officer={officer_id: ytd},
        officer_unit_map={officer_id: unit_id},
    )


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


async def _get_officer_scoped_target(
    db: AsyncSession,
    officer_id: int,
    kpi_code: str,
    fiscal_year: int,
    unit_id: Optional[int],
) -> Optional[models.KpiTarget]:
    """Get officer-scoped KpiTarget (officer_id is unique enough, no unit filter).

    Note: unit_id param kept for signature compat but not used in query.
    Officer may have been transferred — their KpiTarget still references old unit.
    Filtering by unit_id would miss the target in that case, diverging from coverage
    report which loads all officer targets regardless of unit (admin view).
    """
    result = await db.execute(
        select(models.KpiTarget).where(
            models.KpiTarget.officer_id == officer_id,
            models.KpiTarget.kpi_code == kpi_code,
            models.KpiTarget.fiscal_year == fiscal_year,
            models.KpiTarget.is_active == True,  # noqa: E712
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _get_unit_scoped_target(
    db: AsyncSession,
    kpi_code: str,
    fiscal_year: int,
    unit_id: int,
) -> Optional[models.KpiTarget]:
    """Get unit-scoped KpiTarget (unit_id matches, officer_id IS NULL)."""
    result = await db.execute(
        select(models.KpiTarget).where(
            models.KpiTarget.unit_id == unit_id,
            models.KpiTarget.officer_id.is_(None),
            models.KpiTarget.kpi_code == kpi_code,
            models.KpiTarget.fiscal_year == fiscal_year,
            models.KpiTarget.is_active == True,  # noqa: E712
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _get_global_target(
    db: AsyncSession,
    kpi_code: str,
    fiscal_year: int,
) -> Optional[models.KpiTarget]:
    """Get global KpiTarget (unit_id IS NULL, officer_id IS NULL)."""
    result = await db.execute(
        select(models.KpiTarget).where(
            models.KpiTarget.unit_id.is_(None),
            models.KpiTarget.officer_id.is_(None),
            models.KpiTarget.kpi_code == kpi_code,
            models.KpiTarget.fiscal_year == fiscal_year,
            models.KpiTarget.is_active == True,  # noqa: E712
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _resolve_achieved_ytd(
    kpi_repo: Any,
    officer_id: int,
    fiscal_year: int,
    effective_date: Optional[date],
    target_record: Optional[models.KpiTarget],
) -> int:
    """
    Resolve achieved_ytd using the correct strategy.

    Priority:
    1. If effective_date provided -> count from repo (historical query)
    2. If officer has own KpiTarget -> use target_record.achieved_ytd (Celery snapshot)
    3. Else -> count from repo (live query)
    """
    if effective_date is not None:
        return await kpi_repo.count_enrollments_ytd(
            officer_id, fiscal_year, as_of_date=effective_date
        )

    if target_record is not None:
        return target_record.achieved_ytd

    return await kpi_repo.count_enrollments_ytd(officer_id, fiscal_year)


async def _resolve_seasonal_weights(
    kpi_repo: Any,
    officer_id: int,
    unit_id: Optional[int],
    fiscal_year: int,
) -> Optional[List[float]]:
    """
    Resolve seasonal weights: officer plan -> unit plan -> default weights.

    Returns None if no plan exists (caller should use linear fallback).
    """
    from .kpi_planning_service import DEFAULT_ENROLLMENT_WEIGHTS

    plan_found, weights = await kpi_repo.get_active_plan_weights(
        officer_id, unit_id, fiscal_year
    )
    if plan_found:
        if weights and len(weights) == 12:
            return weights
        # Plan exists but seasonal_weights=NULL -> use defaults
        return [DEFAULT_ENROLLMENT_WEIGHTS[m] for m in range(1, 13)]

    # No plan found -> return None (linear fallback)
    return None


def _extract_plan_weights(plan: models.KpiPlan) -> Optional[List[float]]:
    """Extract seasonal weights from a KpiPlan, falling back to defaults."""
    from .kpi_planning_service import DEFAULT_ENROLLMENT_WEIGHTS

    if plan.seasonal_weights and len(plan.seasonal_weights) == 12:
        return list(plan.seasonal_weights)
    # Plan exists but no explicit weights -> use defaults
    return [DEFAULT_ENROLLMENT_WEIGHTS[m] for m in range(1, 13)]


async def _count_active_officers_in_unit(
    db: AsyncSession,
    unit_id: int,
) -> int:
    """Count active officers in a unit."""
    result = await db.execute(
        select(func.count(models.User.id)).where(
            models.User.unit_id == unit_id,
            models.User.role == "officer",
            models.User.status == "active",
        )
    )
    return result.scalar() or 0


async def _count_total_active_officers(
    db: AsyncSession,
) -> int:
    """Count total active officers in active units (matches coverage report scope).

    Coverage report loads officers from OrganizationUnit.is_active == True only.
    Must use same scope here to avoid split divergence on global target.
    """
    result = await db.execute(
        select(func.count(models.User.id))
        .join(
            models.OrganizationUnit,
            models.User.unit_id == models.OrganizationUnit.id,
        )
        .where(
            models.User.role == "officer",
            models.User.status == "active",
            models.OrganizationUnit.is_active == True,  # noqa: E712
        )
    )
    return result.scalar() or 0
