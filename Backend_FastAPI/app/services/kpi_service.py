# app/services/kpi_service.py
"""
KPI Service - Phase 1 & 6

Provides functions for:
1. Getting KPI targets with inheritance (global → unit → officer)
2. Calculating rolling monthly targets
3. Syncing YTD progress (for Celery job)
4. Generating auto recommendations (Phase 7)
"""
import structlog
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

log = structlog.get_logger(__name__)


# =============================================================================
# KPI DEFAULTS & PERIOD MAP — sourced from canonical catalog
# =============================================================================

from .kpi_catalog import get_default_kpis, get_period_map, get_default, get_period_type

# Backward-compatible module-level dicts (used by calculate_monthly_target etc.)
DEFAULT_KPIS = get_default_kpis()
KPI_PERIOD_MAP = get_period_map()


# =============================================================================
# PROGRESS STATUS — Pure function (no DB calls)
# =============================================================================

def compute_progress_status(
    ytd: int,
    annual: int,
    fiscal_year: int,
    ref_year: int,
    ref_month: int,
    seasonal_weights: Optional[List[float]] = None,
) -> str:
    """
    Pure function: determine KPI progress status from progress data.

    Used by both get_annual_target_progress() and kpi_setup_service coverage
    to ensure a single calculation path (no divergence).

    Returns: "completed" | "overdue" | "in_progress" | "at_risk" | "not_started"
    """
    if annual <= 0:
        return "not_started"
    if ytd >= annual:
        return "completed"
    months_left = 12 - ref_month + 1 if fiscal_year == ref_year else (12 if fiscal_year > ref_year else 0)
    if months_left <= 0:
        return "overdue"
    if fiscal_year > ref_year:
        return "in_progress"  # Haven't started yet
    if seasonal_weights and len(seasonal_weights) == 12:
        expected_ytd = annual * sum(seasonal_weights[:ref_month])
    else:
        expected_ytd = (annual / 12) * ref_month
    return "in_progress" if ytd >= expected_ytd * 0.9 else "at_risk"


# =============================================================================
# KPI CONFIG RETRIEVAL (with inheritance)
# =============================================================================

async def get_kpi_target(
    db: AsyncSession,
    kpi_code: str,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    period_type: Optional[str] = None,
    effective_date: Optional[Any] = None,
) -> float:
    """
    Get KPI target value with inheritance + temporal resolution (Phase B8).

    Returns float (NUMERIC(12,2) in DB). Backward compatible.

    Delegates to kpi_resolver.resolve_target() for the actual resolution logic.
    This function is a thin wrapper preserving the existing call signature.
    """
    from .kpi_resolver import resolve_target

    resolution = await resolve_target(
        db=db,
        kpi_code=kpi_code,
        officer_id=officer_id,
        unit_id=unit_id,
        period_type=period_type,
        effective_date=effective_date,
    )
    return resolution.value


async def get_kpi_target_source_info(
    db: AsyncSession,
    kpi_code: str,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    period_type: Optional[str] = None,
    effective_date: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Get KPI target value with inheritance + source information.

    Returns: {"value": float, "is_unit_target": bool}

    Delegates to kpi_resolver.resolve_target() — eliminates the second
    DB round-trip that the old implementation required.
    """
    from .kpi_resolver import resolve_target

    resolution = await resolve_target(
        db=db,
        kpi_code=kpi_code,
        officer_id=officer_id,
        unit_id=unit_id,
        period_type=period_type,
        effective_date=effective_date,
    )
    return {"value": resolution.value, "is_unit_target": resolution.is_unit_target}


async def get_all_kpi_targets(
    db: AsyncSession,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    effective_date: Optional[Any] = None,
) -> Dict[str, float]:
    """
    Get all configured KPI targets for an officer/unit.

    Catalog-driven: loops over METRIC_CATALOG instead of hardcoded DEFAULT_KPIS.
    period_type derived from catalog via resolver (no hardcode).

    Returns dict of kpi_code -> target_value
    """
    from .kpi_catalog import METRIC_CATALOG

    targets = {}
    for kpi_code in METRIC_CATALOG:
        targets[kpi_code] = await get_kpi_target(
            db, kpi_code, officer_id, unit_id,
            effective_date=effective_date,
        )
    return targets


# =============================================================================
# ROLLING TARGET CALCULATION (Phase 6)
# =============================================================================

async def get_annual_target_progress(
    db: AsyncSession,
    officer_id: int,
    kpi_code: str = "enrollments_annual",
    fiscal_year: Optional[int] = None,
    effective_date: Optional[Any] = None,
    seasonal_weights: Optional[List[float]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get annual target progress for an officer.

    Delegates to kpi_resolver.resolve_annual_progress() for the resolution logic,
    then formats the result into the existing response dict shape.

    Returns the same dict shape as before, plus `resolution_kind` field.
    """
    from .kpi_resolver import resolve_annual_progress

    if fiscal_year is None:
        fiscal_year = datetime.now(timezone.utc).year

    # Convert effective_date to date if it's a datetime
    eff_date = None
    if effective_date is not None:
        if hasattr(effective_date, 'date') and callable(effective_date.date):
            eff_date = effective_date.date()
        else:
            eff_date = effective_date

    # Delegate to resolver
    resolution = await resolve_annual_progress(
        db=db,
        officer_id=officer_id,
        fiscal_year=fiscal_year,
        kpi_code=kpi_code,
        effective_date=eff_date,
    )

    if resolution is None:
        return None

    annual = resolution.annual_target
    if annual <= 0:
        return None  # No meaningful target configured

    ytd = resolution.achieved_ytd
    remaining = max(0, annual - ytd)

    # Use caller-injected weights, else resolver-provided weights
    sw = seasonal_weights if seasonal_weights is not None else resolution.seasonal_weights

    # Calculate months remaining
    if effective_date is not None:
        ref_year = effective_date.year
        ref_month = effective_date.month
    else:
        now = datetime.now(timezone.utc)
        ref_year = now.year
        ref_month = now.month

    if fiscal_year < ref_year:
        months_left = 0
    elif fiscal_year > ref_year:
        months_left = 12
    else:
        months_left = 12 - ref_month + 1

    status = compute_progress_status(
        ytd=ytd, annual=annual,
        fiscal_year=fiscal_year, ref_year=ref_year, ref_month=ref_month,
        seasonal_weights=sw,
    )
    if status == "completed":
        monthly_target = 0
        surplus = ytd - annual
    elif status == "overdue":
        monthly_target = remaining
        surplus = 0
    else:
        monthly_target = remaining / months_left
        surplus = 0

    progress_pct = (ytd / annual * 100) if annual > 0 else 0
    on_track = status in ("in_progress", "completed")

    # Compute seasonal-aware expected progress for frontend marker
    if annual > 0 and fiscal_year == ref_year:
        months_elapsed = ref_month
        if sw and len(sw) == 12:
            expected_ytd = annual * sum(sw[:months_elapsed])
        else:
            expected_ytd = (annual / 12) * months_elapsed
        expected_progress_pct = round((expected_ytd / annual) * 100, 1)
    elif annual > 0 and fiscal_year > ref_year:
        expected_progress_pct = 0.0
    else:
        expected_progress_pct = 100.0

    return {
        "kpi_code": kpi_code,
        "fiscal_year": fiscal_year,
        "annual_target": annual,
        "achieved_ytd": ytd,
        "remaining": remaining,
        "progress_pct": round(progress_pct, 1),
        "months_left": months_left,
        "monthly_target": round(monthly_target, 1),
        "status": status,
        "on_track": on_track,
        "surplus": surplus if status == "completed" else None,
        "last_sync_at": resolution.target_record.last_sync_at if resolution.target_record else None,
        "resolution_kind": resolution.resolution_kind,
        "expected_progress_pct": expected_progress_pct,
    }


def aggregate_annual_progresses(
    progresses: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Aggregate per-officer annual progress for manager/admin team view.

    Returns None when no progresses (preserves empty-state semantics).
    Uses worst-case status and per-officer breakdown.
    """
    if not progresses:
        return None

    total_annual = sum(p["annual_target"] for p in progresses)
    total_ytd = sum(p["achieved_ytd"] for p in progresses)
    total_remaining = max(0, total_annual - total_ytd)
    months_left = progresses[0]["months_left"]  # Same fiscal year → same months_left

    # Worst-case status
    STATUS_PRIORITY = {"overdue": 0, "at_risk": 1, "in_progress": 2, "completed": 3}
    worst = min(
        (p["status"] for p in progresses),
        key=lambda s: STATUS_PRIORITY.get(s, 2),
    )
    all_on_track = all(p["on_track"] for p in progresses)
    progress_pct = round((total_ytd / total_annual * 100), 1) if total_annual > 0 else 0

    # resolution_kind: if ANY member is inherited_estimate, aggregate is too
    has_estimate = any(
        p.get("resolution_kind") == "inherited_estimate" for p in progresses
    )
    all_assigned = all(
        p.get("resolution_kind") == "assigned" for p in progresses
    )
    aggregate_kind = "assigned" if all_assigned else (
        "inherited_estimate" if has_estimate else None
    )

    # Weighted expected_progress_pct: weighted by annual_target per officer
    if total_annual > 0:
        weighted_expected = sum(
            p.get("expected_progress_pct", 0) * p["annual_target"]
            for p in progresses
        )
        agg_expected_pct = round(weighted_expected / total_annual, 1)
    else:
        agg_expected_pct = 0.0

    return {
        "kpi_code": "enrollments_annual",
        "fiscal_year": progresses[0]["fiscal_year"],
        "annual_target": total_annual,
        "achieved_ytd": total_ytd,
        "remaining": total_remaining,
        "progress_pct": progress_pct,
        "months_left": months_left,
        "monthly_target": round(total_remaining / max(1, months_left), 1),
        "status": worst,
        "on_track": all_on_track,
        "surplus": total_ytd - total_annual if worst == "completed" else None,
        "last_sync_at": None,
        "resolution_kind": aggregate_kind,
        "expected_progress_pct": agg_expected_pct,
        # R1: Team breakdown for manager drill-down
        "officer_count": len(progresses),
        "officers_at_risk": sum(1 for p in progresses if p["status"] == "at_risk"),
        "officers_overdue": sum(1 for p in progresses if p["status"] == "overdue"),
    }


async def calculate_monthly_target(
    db: AsyncSession,
    officer_id: int,
    kpi_code: str,
    month: int,
    year: int
) -> Dict[str, Any]:
    """
    Calculate rolling monthly target based on annual target and YTD progress.
    
    Formula: (annual_target - achieved_ytd) / months_remaining
    
    Returns:
        {
            "status": "in_progress" | "completed" | "overdue",
            "target": float,  # If in_progress
            "surplus": float,  # If completed
            "remaining": float,  # If overdue
        }
    """
    progress = await get_annual_target_progress(db, officer_id, kpi_code, year)
    
    if not progress:
        # No annual target configured, use default monthly
        default_monthly = DEFAULT_KPIS.get(f"{kpi_code}_monthly", 7)
        return {
            "status": "in_progress",
            "target": default_monthly,
        }
    
    if progress["status"] == "completed":
        return {
            "status": "completed",
            "surplus": progress["surplus"],
        }
    
    if month > 12:
        return {
            "status": "overdue",
            "remaining": progress["remaining"],
        }
    
    months_left = 12 - month + 1
    remaining = progress["remaining"]
    
    return {
        "status": "in_progress",
        "target": round(remaining / months_left, 1) if months_left > 0 else remaining,
    }


# =============================================================================
# YTD SYNC (for Celery job)
# =============================================================================

async def sync_officer_ytd(
    db: AsyncSession,
    officer_id: int,
    fiscal_year: Optional[int] = None,
) -> Dict[str, int]:
    """
    Sync achieved_ytd for an officer from actual data.
    Should be called by Celery job daily.
    
    ✅ REFACTORED: Uses KpiRepository for data access.
    
    Uses PipelineStage + ConsultationStatus for consistency with funnel chart:
    - PipelineStage.is_final_stage == True (lead has completed the funnel)
    - ConsultationStatus.counts_for_funnel == True (successful conversion)
    
    Returns:
        Dict of kpi_code -> actual YTD value
    """
    from ..repositories import KpiRepository
    
    if fiscal_year is None:
        fiscal_year = datetime.now(timezone.utc).year
    
    synced = {}
    repo = KpiRepository(db)

    # Resolve officer's unit for correct target lookup
    unit_id = await repo.get_user_unit_id(officer_id)

    # Find the specific KpiTarget to update (officer → unit → global inheritance)
    target_record = await repo.get_annual_target_with_priority(
        officer_id=officer_id,
        kpi_code="enrollments_annual",
        fiscal_year=fiscal_year,
        unit_id=unit_id,
    )

    if not target_record:
        log.debug("No annual target found for officer, skipping YTD sync",
                   officer_id=officer_id, fiscal_year=fiscal_year)
        return synced

    # R0.4: Only update officer-scoped targets. Never overwrite shared unit/global rows.
    if target_record.officer_id != officer_id:
        from ..models.config import KpiTarget as KpiTargetModel
        from sqlalchemy.exc import IntegrityError

        # Step 1: Check for existing row (including inactive) at exact scope
        existing = (await db.execute(
            select(KpiTargetModel).where(
                KpiTargetModel.officer_id == officer_id,
                KpiTargetModel.unit_id == unit_id,
                KpiTargetModel.kpi_code == "enrollments_annual",
                KpiTargetModel.fiscal_year == fiscal_year,
            )
        )).scalar_one_or_none()

        if existing:
            # Reactivate/update existing row
            existing.is_active = True
            existing.annual_target = target_record.annual_target
            await db.flush()
            log.info(
                "Reactivated existing officer-scoped KpiTarget",
                officer_id=officer_id, fiscal_year=fiscal_year,
                target_id=existing.id,
            )
            target_record = existing
        else:
            # Step 2: Create new row using savepoint for race safety
            new_target = KpiTargetModel(
                officer_id=officer_id,
                unit_id=unit_id,
                kpi_code="enrollments_annual",
                fiscal_year=fiscal_year,
                annual_target=target_record.annual_target,
                achieved_ytd=0,
                is_active=True,
            )
            try:
                async with db.begin_nested():
                    db.add(new_target)
                    await db.flush()
                log.info(
                    "Auto-created officer-scoped KpiTarget from inherited row",
                    officer_id=officer_id, fiscal_year=fiscal_year,
                    inherited_target_id=target_record.id,
                    new_target_id=new_target.id,
                )
                target_record = new_target
            except IntegrityError:
                # Race: another task created it — re-fetch (including inactive)
                existing = (await db.execute(
                    select(KpiTargetModel).where(
                        KpiTargetModel.officer_id == officer_id,
                        KpiTargetModel.unit_id == unit_id,
                        KpiTargetModel.kpi_code == "enrollments_annual",
                        KpiTargetModel.fiscal_year == fiscal_year,
                    )
                )).scalar_one_or_none()
                if not existing:
                    log.warning("Race: re-fetch after IntegrityError failed",
                                officer_id=officer_id, fiscal_year=fiscal_year)
                    return synced
                existing.is_active = True
                await db.flush()
                target_record = existing
                log.info("Race: re-fetched existing officer-scoped KpiTarget",
                         officer_id=officer_id, target_id=target_record.id)

    # Count leads that reached FINAL pipeline stage with counts_for_funnel=True
    enrollments_ytd = await repo.count_enrollments_ytd(officer_id, fiscal_year)
    synced["enrollments_annual"] = enrollments_ytd

    # Update by target PK — avoids ambiguous multi-row updates
    await repo.update_achieved_ytd(
        target_id=target_record.id,
        ytd_value=enrollments_ytd,
    )

    log.info(
        "Synced officer YTD",
        officer_id=officer_id,
        fiscal_year=fiscal_year,
        target_id=target_record.id,
        synced=synced,
    )

    return synced


# =============================================================================
# KPI CONFIG CRUD (Admin Operations) - Pattern A
# =============================================================================

# Custom Exceptions
class DuplicateConfigError(Exception):
    """Raised when attempting to create a duplicate KPI config."""
    pass


class ConfigNotFoundError(Exception):
    """Raised when KPI config is not found."""
    pass


class TargetNotFoundError(Exception):
    """Raised when KPI target is not found."""
    pass


class DuplicateTargetError(Exception):
    """Raised when attempting to create a duplicate KPI target."""
    pass


# Type alias for callback
from typing import Callable, Awaitable, Tuple
Callback = Callable[[], Awaitable[None]]


async def list_kpi_configs(
    db: AsyncSession,
    kpi_code: Optional[str] = None,
    unit_id: Optional[int] = None,
    is_active: bool = True,
    include_global: bool = False,
) -> List[models.KpiConfig]:
    """List KPI configurations with filters.
    include_global: when True + unit_id set, includes global configs (unit_id IS NULL)."""
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    return await repo.list_configs(
        kpi_code=kpi_code, unit_id=unit_id, is_active=is_active,
        include_global=include_global,
    )


async def create_kpi_config(
    db: AsyncSession,
    kpi_code: str,
    target_value: float,
    period_type: str = "daily",
    unit_id: Optional[int] = None,
    officer_id: Optional[int] = None,
    created_by: Optional[models.User] = None,
) -> Tuple[models.KpiConfig, Callback]:
    """
    Create a new KPI configuration.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        DuplicateConfigError: If active config already exists for this scope
    """
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    # Check for duplicates
    existing = await repo.check_duplicate_exists(
        kpi_code=kpi_code,
        period_type=period_type,
        unit_id=unit_id,
        officer_id=officer_id,
    )
    
    if existing:
        raise DuplicateConfigError(
            f"Active config already exists for {kpi_code} with this scope"
        )
    
    # Create config
    config = models.KpiConfig(
        kpi_code=kpi_code,
        target_value=target_value,
        period_type=period_type,
        unit_id=unit_id,
        officer_id=officer_id,
        is_active=True,
    )
    db.add(config)
    
    # ✅ REFACTORED: Add flush/refresh as per guidelines
    await db.flush()
    await db.refresh(config)
    
    async def callback():
        log.info(
            "KPI config created",
            config_id=config.id,
            kpi_code=kpi_code,
            created_by=created_by.id if created_by else None,
        )
    
    return config, callback


async def update_kpi_config(
    db: AsyncSession,
    config_id: int,
    target_value: Optional[float] = None,
    is_active: Optional[bool] = None,
    updated_by: Optional[models.User] = None,
) -> Tuple[models.KpiConfig, Callback]:
    """
    Update an existing KPI configuration.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        ConfigNotFoundError: If config not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    config = await repo.get_config_by_id(config_id)
    if not config:
        raise ConfigNotFoundError(f"Config {config_id} not found")
    
    changes = []
    if target_value is not None and config.target_value != target_value:
        old_value = config.target_value
        config.target_value = target_value
        changes.append(f"target_value: {old_value} → {target_value}")
    
    if is_active is not None and config.is_active != is_active:
        config.is_active = is_active
        changes.append(f"is_active: {is_active}")
    
    async def callback():
        if changes:
            log.info(
                "KPI config updated",
                config_id=config_id,
                changes=changes,
                updated_by=updated_by.id if updated_by else None,
            )
    
    return config, callback


async def delete_kpi_config(
    db: AsyncSession,
    config_id: int,
    deleted_by: Optional[models.User] = None,
) -> Tuple[models.KpiConfig, Callback]:
    """
    Soft delete a KPI configuration (set is_active=False).
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        ConfigNotFoundError: If config not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    config = await repo.get_config_by_id(config_id)
    if not config:
        raise ConfigNotFoundError(f"Config {config_id} not found")
    
    config.is_active = False
    
    async def callback():
        log.info(
            "KPI config deleted",
            config_id=config_id,
            deleted_by=deleted_by.id if deleted_by else None,
        )
    
    return config, callback


async def list_kpi_targets(
    db: AsyncSession,
    fiscal_year: Optional[int] = None,
    kpi_code: Optional[str] = None,
    is_active: bool = True,
    unit_id: Optional[int] = None,
) -> List[models.KpiTarget]:
    """List annual KPI targets with filters. unit_id for IDOR scope filtering."""
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    return await repo.list_targets(
        fiscal_year=fiscal_year, kpi_code=kpi_code, is_active=is_active, unit_id=unit_id
    )


async def create_kpi_target(
    db: AsyncSession,
    kpi_code: str,
    annual_target: int,
    fiscal_year: int,
    unit_id: Optional[int] = None,
    officer_id: Optional[int] = None,
    created_by: Optional[models.User] = None,
) -> Tuple[models.KpiTarget, Callback]:
    """
    Create an annual KPI target.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        DuplicateTargetError: If active target already exists for this scope + year
    """
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    # Check for duplicates
    existing = await repo.check_duplicate_target_exists(
        kpi_code=kpi_code,
        fiscal_year=fiscal_year,
        unit_id=unit_id,
        officer_id=officer_id,
    )
    
    if existing:
        # Build scope description for error message
        if officer_id:
            scope = f"Cán bộ #{officer_id}"
        elif unit_id:
            scope = f"Đơn vị #{unit_id}"
        else:
            scope = "Toàn cục"
        
        raise DuplicateTargetError(
            f"Mục tiêu năm {fiscal_year} cho '{kpi_code}' phạm vi {scope} đã tồn tại"
        )
    
    target = models.KpiTarget(
        kpi_code=kpi_code,
        annual_target=annual_target,
        fiscal_year=fiscal_year,
        unit_id=unit_id,
        officer_id=officer_id,
        is_active=True,
        achieved_ytd=0,
    )
    db.add(target)
    
    # ✅ REFACTORED: Add flush/refresh as per guidelines
    await db.flush()
    await db.refresh(target)
    
    async def callback():
        log.info(
            "KPI target created",
            target_id=target.id,
            kpi_code=kpi_code,
            fiscal_year=fiscal_year,
            created_by=created_by.id if created_by else None,
        )
    
    return target, callback


async def update_kpi_target(
    db: AsyncSession,
    target_id: int,
    annual_target: Optional[int] = None,
    is_active: Optional[bool] = None,
    updated_by: Optional[models.User] = None,
) -> Tuple[models.KpiTarget, Callback]:
    """
    Update an existing KPI target.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        TargetNotFoundError: If target not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    target = await repo.get_target_by_id(target_id)
    if not target:
        raise TargetNotFoundError(f"Target {target_id} not found")
    
    changes = []
    if annual_target is not None and target.annual_target != annual_target:
        old_value = target.annual_target
        target.annual_target = annual_target
        changes.append(f"annual_target: {old_value} → {annual_target}")
    
    if is_active is not None and target.is_active != is_active:
        target.is_active = is_active
        changes.append(f"is_active: {is_active}")
    
    async def callback():
        if changes:
            log.info(
                "KPI target updated",
                target_id=target_id,
                changes=changes,
                updated_by=updated_by.id if updated_by else None,
            )
    
    return target, callback


async def delete_kpi_target(
    db: AsyncSession,
    target_id: int,
    deleted_by: Optional[models.User] = None,
) -> Tuple[models.KpiTarget, Callback]:
    """
    Soft delete a KPI target (set is_active=False).
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        TargetNotFoundError: If target not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    target = await repo.get_target_by_id(target_id)
    if not target:
        raise TargetNotFoundError(f"Target {target_id} not found")
    
    target.is_active = False
    
    async def callback():
        log.info(
            "KPI target deleted",
            target_id=target_id,
            deleted_by=deleted_by.id if deleted_by else None,
        )
    
    return target, callback

