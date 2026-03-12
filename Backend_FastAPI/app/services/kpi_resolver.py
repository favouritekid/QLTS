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

    Combines logic from:
    - kpi_service.get_annual_target_progress() (KpiTarget inheritance)
    - kpi_setup_service.get_coverage_report() (equal split for inherited officers)

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
    from ..repositories import KpiRepository, KpiPlanningRepository

    kpi_repo = KpiRepository(db)

    # --- Resolve officer's unit_id ---
    unit_id = await kpi_repo.get_user_unit_id(officer_id)

    # --- Step 1: Officer-scoped KpiTarget ---
    officer_target = await _get_officer_scoped_target(
        db, officer_id, kpi_code, fiscal_year, unit_id
    )
    if officer_target is not None:
        achieved_ytd = await _resolve_achieved_ytd(
            kpi_repo, officer_id, fiscal_year, effective_date, officer_target
        )
        seasonal_weights = await _resolve_seasonal_weights(
            kpi_repo, officer_id, unit_id, fiscal_year
        )

        log.debug(
            "Annual progress resolved from officer KpiTarget",
            officer_id=officer_id,
            annual_target=officer_target.annual_target,
            achieved_ytd=achieved_ytd,
        )

        return AnnualProgressResolution(
            annual_target=officer_target.annual_target,
            achieved_ytd=achieved_ytd,
            resolution_kind="assigned",
            source_description="Officer KpiTarget",
            target_record=officer_target,
            seasonal_weights=seasonal_weights,
        )

    # --- Step 2: Officer has own KpiPlan ---
    if unit_id is not None:
        planning_repo = KpiPlanningRepository(db)
        officer_plan = await planning_repo.get_active_plan_by_scope(
            unit_id=unit_id,
            fiscal_year=fiscal_year,
            officer_id=officer_id,
            with_months=False,
        )
        if officer_plan is not None:
            achieved_ytd = await _resolve_achieved_ytd(
                kpi_repo, officer_id, fiscal_year, effective_date, None
            )
            seasonal_weights = _extract_plan_weights(officer_plan)

            log.debug(
                "Annual progress resolved from officer KpiPlan",
                officer_id=officer_id,
                plan_id=officer_plan.id,
                annual_target=officer_plan.annual_enrollment_target,
            )

            return AnnualProgressResolution(
                annual_target=officer_plan.annual_enrollment_target,
                achieved_ytd=achieved_ytd,
                resolution_kind="assigned",
                source_description="Officer KpiPlan",
                target_record=None,
                seasonal_weights=seasonal_weights,
            )

    # --- Steps 3-5: Inherited estimates (require officer count for split) ---

    # Step 3: Unit has KpiPlan
    if unit_id is not None:
        planning_repo = KpiPlanningRepository(db)
        unit_plan = await planning_repo.get_active_plan_by_scope(
            unit_id=unit_id,
            fiscal_year=fiscal_year,
            officer_id=None,
            with_months=False,
        )
        if unit_plan is not None:
            active_count = await _count_active_officers_in_unit(db, unit_id)
            if active_count > 0:
                split_target = unit_plan.annual_enrollment_target // active_count
                achieved_ytd = await _resolve_achieved_ytd(
                    kpi_repo, officer_id, fiscal_year, effective_date, None
                )
                seasonal_weights = _extract_plan_weights(unit_plan)

                log.debug(
                    "Annual progress resolved from unit KpiPlan (inherited)",
                    officer_id=officer_id,
                    plan_id=unit_plan.id,
                    split_target=split_target,
                    active_officers=active_count,
                )

                return AnnualProgressResolution(
                    annual_target=split_target,
                    achieved_ytd=achieved_ytd,
                    resolution_kind="inherited_estimate",
                    source_description=f"Unit plan (ước tính, {active_count} officers)",
                    target_record=None,
                    seasonal_weights=seasonal_weights,
                )

    # Step 4: Unit-scoped KpiTarget
    if unit_id is not None:
        unit_target = await _get_unit_scoped_target(
            db, kpi_code, fiscal_year, unit_id
        )
        if unit_target is not None:
            active_count = await _count_active_officers_in_unit(db, unit_id)
            if active_count > 0:
                split_target = unit_target.annual_target // active_count
                achieved_ytd = await _resolve_achieved_ytd(
                    kpi_repo, officer_id, fiscal_year, effective_date, None
                )
                seasonal_weights = await _resolve_seasonal_weights(
                    kpi_repo, officer_id, unit_id, fiscal_year
                )

                log.debug(
                    "Annual progress resolved from unit KpiTarget (inherited)",
                    officer_id=officer_id,
                    unit_target_id=unit_target.id,
                    split_target=split_target,
                    active_officers=active_count,
                )

                return AnnualProgressResolution(
                    annual_target=split_target,
                    achieved_ytd=achieved_ytd,
                    resolution_kind="inherited_estimate",
                    source_description=f"Unit target (ước tính, {active_count} officers)",
                    target_record=None,
                    seasonal_weights=seasonal_weights,
                )

    # Step 5: Global KpiTarget
    global_target = await _get_global_target(db, kpi_code, fiscal_year)
    if global_target is not None:
        total_count = await _count_total_active_officers(db)
        if total_count > 0:
            split_target = global_target.annual_target // total_count
            achieved_ytd = await _resolve_achieved_ytd(
                kpi_repo, officer_id, fiscal_year, effective_date, None
            )
            seasonal_weights = await _resolve_seasonal_weights(
                kpi_repo, officer_id, unit_id, fiscal_year
            )

            log.debug(
                "Annual progress resolved from global KpiTarget (inherited)",
                officer_id=officer_id,
                global_target_id=global_target.id,
                split_target=split_target,
                total_officers=total_count,
            )

            return AnnualProgressResolution(
                annual_target=split_target,
                achieved_ytd=achieved_ytd,
                resolution_kind="inherited_estimate",
                source_description=f"Global target (ước tính, {total_count} officers)",
                target_record=None,
                seasonal_weights=seasonal_weights,
            )

    # Step 6: Nothing found
    log.debug(
        "No annual target resolvable for officer",
        officer_id=officer_id,
        fiscal_year=fiscal_year,
    )
    return None


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
