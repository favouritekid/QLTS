# app/services/kpi_planning_service.py
"""
KPI Planning Service — Reverse-Funnel Engine (Phase A4)

Core functions:
- create_plan: Create KpiPlan + 12 KpiPlanMonth records
- generate_monthly_kpis: Compute derived KPIs from M_t + factors

Architecture:
- Service NEVER commits. Only add/flush. Router commits.
- Returns Tuple[result, Optional[Callable]] per project pattern.
"""
import math
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import KpiPlan, KpiPlanMonth
from app.services.calendar_service import count_working_days, get_working_days_override
from app.utils.exceptions import BusinessRuleViolation, ResourceNotFoundError, DuplicateResourceError

log = structlog.get_logger(__name__)

Callback = Optional[Callable]

# =============================================================================
# DEFAULT SEASONAL WEIGHTS (spec §9)
# =============================================================================

DEFAULT_ENROLLMENT_WEIGHTS: Dict[int, float] = {
    1:  0.040,   # T1:  sau Tết
    2:  0.033,   # T2:  Tết
    3:  0.050,   # T3:  bắt đầu tăng
    4:  0.060,   # T4
    5:  0.073,   # T5:  trước cao điểm
    6:  0.127,   # T6:  CAO ĐIỂM
    7:  0.153,   # T7:  CAO ĐIỂM ĐỈNH
    8:  0.160,   # T8:  CAO ĐIỂM ĐỈNH
    9:  0.133,   # T9:  CAO ĐIỂM
    10: 0.093,   # T10: cao điểm cuối
    11: 0.043,   # T11: giảm
    12: 0.033,   # T12: thấp nhất
}

# Default factors for year 1 (no historical data)
DEFAULT_K_FACTOR = 7.0
DEFAULT_CONSULTATION_EFFECTIVENESS_FLOOR = 50.0


# =============================================================================
# VALIDATION (spec §4)
# =============================================================================

def validate_seasonal_weights(weights: List[float]) -> None:
    """Validate seasonal weights before saving."""
    if len(weights) != 12:
        raise BusinessRuleViolation(f"seasonal_weights phải có đúng 12 phần tử, nhận {len(weights)}")
    if not all(w > 0 for w in weights):
        raise BusinessRuleViolation("Mỗi weight phải > 0")
    total = sum(weights)
    if not (0.99 <= total <= 1.01):
        raise BusinessRuleViolation(f"Tổng weights = {total:.4f}, phải nằm trong [0.99, 1.01]")


def validate_annual_target(target: int) -> None:
    """Validate annual enrollment target."""
    if not isinstance(target, int) or target < 1:
        raise BusinessRuleViolation("annual_enrollment_target phải là số nguyên >= 1")
    if target > 10000:
        raise BusinessRuleViolation("annual_enrollment_target tối đa 10000")


# =============================================================================
# LARGEST REMAINDER METHOD (spec §1)
# =============================================================================

def distribute_by_largest_remainder(
    annual_target: int,
    weights: List[float],
) -> List[int]:
    """
    Distribute annual_target across 12 months using Largest Remainder Method.

    Guarantees: sum(result) == annual_target exactly.
    Handles both diff > 0 (weights sum < 1) and diff < 0 (weights sum > 1).
    """
    exact = [annual_target * w for w in weights]
    floored = [math.floor(x) for x in exact]

    diff = annual_target - sum(floored)

    remainders = [(i, exact[i] - floored[i]) for i in range(12)]
    remainders.sort(key=lambda x: x[1], reverse=True)

    if diff > 0:
        for i in range(diff):
            floored[remainders[i][0]] += 1
    elif diff < 0:
        for i in range(abs(diff)):
            floored[remainders[-(i + 1)][0]] -= 1

    return floored


# =============================================================================
# DERIVED KPI COMPUTATION (spec §1)
# =============================================================================

def compute_derived_kpis(
    m_t: int,
    wd_t: int,
    k_t: float,
    l_t: Optional[int],
    c_t: Optional[int],
) -> Dict[str, Any]:
    """
    Compute 4 derived KPIs for a single month.

    Division-by-zero guard: returns None when not computable.
    kpi_plan_month stores NULL; sync job will COALESCE(NULL, 0) into KpiConfig.

    Returns dict with keys: consultations_daily, conversion_rate, win_rate,
    consultation_effectiveness.
    """
    # WD_t = 0 → entire month off → ALL derived KPIs = NULL (spec §1)
    if wd_t == 0:
        return {
            "consultations_daily": None,
            "conversion_rate": None,
            "win_rate": None,
            "consultation_effectiveness": None,
        }

    # M_t = 0 → no enrollment target → daily=0, rates=NULL, effectiveness=floor
    if m_t == 0:
        return {
            "consultations_daily": 0,
            "conversion_rate": None,
            "win_rate": None,
            "consultation_effectiveness": Decimal(str(DEFAULT_CONSULTATION_EFFECTIVENESS_FLOOR)),
        }

    # L_t default = 6 * M_t, C_t default = 3 * M_t
    effective_l = l_t if l_t is not None else 6 * m_t
    effective_c = c_t if c_t is not None else 3 * m_t

    # consultations_daily = ceil(M_t * k_t / WD_t)
    consultations_daily = math.ceil(m_t * k_t / wd_t)

    # conversion_rate = (M_t / L_t) * 100
    conversion_rate = round(m_t / effective_l * 100, 2) if effective_l > 0 else None

    # win_rate = (M_t / C_t) * 100
    win_rate = round(m_t / effective_c * 100, 2) if effective_c > 0 else None

    # consultation_effectiveness = max(floor, M_t / consulted_closed_t * 100)
    # Year 1: no consulted_closed data → use floor (50%)
    consultation_effectiveness = Decimal(str(DEFAULT_CONSULTATION_EFFECTIVENESS_FLOOR))

    return {
        "consultations_daily": consultations_daily,
        "conversion_rate": Decimal(str(conversion_rate)) if conversion_rate is not None else None,
        "win_rate": Decimal(str(win_rate)) if win_rate is not None else None,
        "consultation_effectiveness": consultation_effectiveness,
    }


# =============================================================================
# CREATE PLAN (spec §5.1)
# =============================================================================

async def create_plan(
    db: AsyncSession,
    unit_id: int,
    fiscal_year: int,
    annual_target: int,
    sla_target: float = 85.0,
    response_time_target: float = 2.0,
    seasonal_weights: Optional[List[float]] = None,
    officer_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> Tuple[KpiPlan, Callback]:
    """
    Create a new KPI plan and auto-generate 12 KpiPlanMonth records.

    officer_id=None → unit plan (baseline for all officers without own plan).
    officer_id=N → officer-specific plan (overrides unit plan for that officer).

    Validates inputs, distributes M_t via Largest Remainder, computes derived KPIs.
    Service does NOT commit — caller (router) commits.

    Returns: (KpiPlan with months loaded, post_commit_callback)
    """
    # --- Validation ---
    if unit_id is None:
        raise BusinessRuleViolation("unit_id bắt buộc — không hỗ trợ global plan")
    validate_annual_target(annual_target)
    if not (0 <= sla_target <= 100):
        raise BusinessRuleViolation(f"sla_target phải trong 0..100, nhận {sla_target}")
    if not (1 <= response_time_target <= 48):
        raise BusinessRuleViolation(f"response_time_target phải trong 1..48, nhận {response_time_target}")

    weights_list: List[float]
    weights_json: Optional[List[float]]

    if seasonal_weights is not None:
        validate_seasonal_weights(seasonal_weights)
        weights_list = seasonal_weights
        weights_json = seasonal_weights
    else:
        weights_list = [DEFAULT_ENROLLMENT_WEIGHTS[m] for m in range(1, 13)]
        weights_json = None  # NULL = use defaults

    # --- Check duplicate active plan (scope-aware, via repository) ---
    from app.repositories.kpi_planning_repository import KpiPlanningRepository
    repo = KpiPlanningRepository(db)

    if await repo.check_duplicate_active_plan(unit_id, fiscal_year, officer_id):
        scope_label = (
            f"officer plan (unit_id={unit_id}, officer_id={officer_id})"
            if officer_id else f"unit plan (unit_id={unit_id})"
        )
        raise DuplicateResourceError(
            f"Active {scope_label} already exists for fiscal_year={fiscal_year}"
        )

    # --- Create plan ---
    plan = KpiPlan(
        unit_id=unit_id,
        officer_id=officer_id,
        fiscal_year=fiscal_year,
        annual_enrollment_target=annual_target,
        sla_target=Decimal(str(sla_target)),
        response_time_target=Decimal(str(response_time_target)),
        seasonal_weights=weights_json,
        is_active=True,
        created_by=created_by,
    )
    db.add(plan)
    await db.flush()  # Get plan.id for FK

    # --- Generate 12 months ---
    await _generate_months_for_plan(db, plan, weights_list)

    log.info(
        "KPI plan created",
        plan_id=plan.id, unit_id=unit_id, fiscal_year=fiscal_year,
        annual_target=annual_target,
    )

    return plan, None


# =============================================================================
# GENERATE MONTHLY KPIs (spec §5.1)
# =============================================================================

async def generate_monthly_kpis(
    db: AsyncSession,
    plan_id: int,
) -> Tuple[KpiPlan, Callback]:
    """
    Regenerate derived KPIs for all 12 months of an existing plan.

    Skips fields in overridden_fields (per-field, not per-row).
    Does NOT commit — caller commits.

    Returns: (KpiPlan with refreshed months, post_commit_callback)
    """
    from app.repositories.kpi_planning_repository import KpiPlanningRepository
    repo = KpiPlanningRepository(db)

    plan = await repo.get_plan_by_id(plan_id, with_months=True)
    if plan is None:
        raise ResourceNotFoundError("KpiPlan", plan_id)

    weights_list: List[float]
    if plan.seasonal_weights:
        weights_list = plan.seasonal_weights
    else:
        weights_list = [DEFAULT_ENROLLMENT_WEIGHTS[m] for m in range(1, 13)]

    # Redistribute M_t
    monthly_targets = distribute_by_largest_remainder(
        plan.annual_enrollment_target, weights_list
    )

    # Update each month
    months_by_month = {m.month: m for m in plan.months}

    for month_idx in range(12):
        month_num = month_idx + 1
        m_t = monthly_targets[month_idx]

        plan_month = months_by_month.get(month_num)
        if plan_month is None:
            continue  # Should not happen, but guard

        overridden = plan_month.overridden_fields or {}

        # Update distributable inputs (not overridable)
        plan_month.enrollment_target = m_t
        plan_month.weight = Decimal(str(weights_list[month_idx]))

        # Working days: check override first
        override_wd = await get_working_days_override(db, plan_month.id)
        if override_wd is not None:
            wd_t = override_wd
        else:
            wd_t = await count_working_days(db, plan.fiscal_year, month_num)
            plan_month.working_days = wd_t

        # Factors (keep existing unless recalibration — not in A4 scope)
        k_t = float(plan_month.k_factor)
        l_t = plan_month.lead_forecast
        c_t = plan_month.close_forecast

        # Compute derived KPIs
        derived = compute_derived_kpis(m_t, wd_t, k_t, l_t, c_t)

        # Apply derived values, skipping overridden fields
        for field, value in derived.items():
            if field not in overridden:
                setattr(plan_month, field, value)

    await db.flush()

    log.info("Monthly KPIs regenerated", plan_id=plan_id)
    return plan, None


# =============================================================================
# INTERNAL: Generate months for new plan
# =============================================================================

async def _generate_months_for_plan(
    db: AsyncSession,
    plan: KpiPlan,
    weights: List[float],
) -> None:
    """Create 12 KpiPlanMonth records for a new plan."""
    monthly_targets = distribute_by_largest_remainder(
        plan.annual_enrollment_target, weights
    )

    for month_idx in range(12):
        month_num = month_idx + 1
        m_t = monthly_targets[month_idx]

        wd_t = await count_working_days(db, plan.fiscal_year, month_num)

        k_t = float(DEFAULT_K_FACTOR)
        l_t = None  # Year 1 default: 6 * M_t (computed in derive)
        c_t = None  # Year 1 default: 3 * M_t (computed in derive)

        derived = compute_derived_kpis(m_t, wd_t, k_t, l_t, c_t)

        plan_month = KpiPlanMonth(
            plan_id=plan.id,
            month=month_num,
            enrollment_target=m_t,
            working_days=wd_t,
            weight=Decimal(str(weights[month_idx])),
            k_factor=Decimal(str(k_t)),
            lead_forecast=l_t,
            close_forecast=c_t,
            **derived,
        )
        db.add(plan_month)

    await db.flush()


# =============================================================================
# PREVIEW PLAN — dry-run, no persist (spec §5.1, §7)
# =============================================================================

async def preview_plan(
    db: AsyncSession,
    unit_id: int,
    fiscal_year: int,
    annual_target: int,
    sla_target: float = 85.0,
    response_time_target: float = 2.0,
    seasonal_weights: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Dry-run: compute 12 monthly KPIs WITHOUT persisting.

    Returns dict matching KpiPlanPreviewResponse schema.
    Pure computation + working-days lookup (read-only DB access).
    """
    validate_annual_target(annual_target)
    if not (0 <= sla_target <= 100):
        raise BusinessRuleViolation(f"sla_target phải trong 0..100, nhận {sla_target}")
    if not (1 <= response_time_target <= 48):
        raise BusinessRuleViolation(f"response_time_target phải trong 1..48, nhận {response_time_target}")

    if seasonal_weights is not None:
        validate_seasonal_weights(seasonal_weights)
        weights_list = seasonal_weights
    else:
        weights_list = [DEFAULT_ENROLLMENT_WEIGHTS[m] for m in range(1, 13)]

    monthly_targets = distribute_by_largest_remainder(annual_target, weights_list)

    months_preview: List[Dict[str, Any]] = []
    for month_idx in range(12):
        month_num = month_idx + 1
        m_t = monthly_targets[month_idx]
        wd_t = await count_working_days(db, fiscal_year, month_num)
        k_t = DEFAULT_K_FACTOR

        derived = compute_derived_kpis(m_t, wd_t, k_t, None, None)
        # Convert Decimal to float for JSON serialization
        for key, val in derived.items():
            if isinstance(val, Decimal):
                derived[key] = float(val)

        months_preview.append({
            "month": month_num,
            "enrollment_target": m_t,
            "working_days": wd_t,
            "weight": weights_list[month_idx],
            "k_factor": k_t,
            "lead_forecast": None,
            "close_forecast": None,
            **derived,
        })

    return {
        "annual_enrollment_target": annual_target,
        "sla_target": sla_target,
        "response_time_target": response_time_target,
        "months": months_preview,
    }


# =============================================================================
# UPDATE PLAN — basic metadata update (spec §5.1, Phase A6 wiring)
# =============================================================================

async def update_plan(
    db: AsyncSession,
    plan: KpiPlan,
    annual_target: Optional[int] = None,
    sla_target: Optional[float] = None,
    response_time_target: Optional[float] = None,
    seasonal_weights: Optional[List[float]] = None,
) -> Tuple[KpiPlan, Callback]:
    """
    Update plan metadata and regenerate derived KPIs.

    Note: Full mid-year redistribute logic is Phase B6.
    This A6 implementation updates fields and regenerates all 12 months.
    """
    changed = False

    if annual_target is not None:
        validate_annual_target(annual_target)
        plan.annual_enrollment_target = annual_target
        changed = True

    if sla_target is not None:
        if not (0 <= sla_target <= 100):
            raise BusinessRuleViolation(f"sla_target phải trong 0..100, nhận {sla_target}")
        plan.sla_target = Decimal(str(sla_target))
        changed = True

    if response_time_target is not None:
        if not (1 <= response_time_target <= 48):
            raise BusinessRuleViolation(f"response_time_target phải trong 1..48, nhận {response_time_target}")
        plan.response_time_target = Decimal(str(response_time_target))
        changed = True

    if seasonal_weights is not None:
        validate_seasonal_weights(seasonal_weights)
        plan.seasonal_weights = seasonal_weights
        changed = True

    if not changed:
        return plan, None

    await db.flush()

    # Regenerate derived KPIs with updated inputs
    plan, _ = await generate_monthly_kpis(db, plan.id)

    log.info("KPI plan updated", plan_id=plan.id)
    return plan, None


# =============================================================================
# DEACTIVATE PLAN — soft delete (spec §5.1, Phase A6 wiring)
# =============================================================================

async def deactivate_plan(
    db: AsyncSession,
    plan: KpiPlan,
) -> Tuple[KpiPlan, Callback]:
    """
    Soft-delete: set is_active = FALSE.

    Note: Full cleanup of future KpiConfig records (using source_plan_id)
    is Phase B7. This A6 implementation only deactivates the plan.
    """
    plan.is_active = False
    await db.flush()

    log.info("KPI plan deactivated", plan_id=plan.id)
    return plan, None


# =============================================================================
# SYNC PLAN → KpiConfig / KpiTarget (spec §5.1, §8.3 — Phase A7)
# =============================================================================

# Mapping: kpi_plan_month fields → KpiConfig records
# source="month" reads from KpiPlanMonth, source="plan" reads from KpiPlan
KPI_SYNC_MAPPING = [
    {"kpi_code": "consultations_daily",        "period_type": "daily",   "source": "month", "field": "consultations_daily"},
    {"kpi_code": "conversion_rate",            "period_type": "monthly", "source": "month", "field": "conversion_rate"},
    {"kpi_code": "win_rate",                   "period_type": "monthly", "source": "month", "field": "win_rate"},
    {"kpi_code": "consultation_effectiveness", "period_type": "monthly", "source": "month", "field": "consultation_effectiveness"},
    {"kpi_code": "enrollments_monthly",        "period_type": "monthly", "source": "month", "field": "enrollment_target"},
    {"kpi_code": "sla_compliance_rate",        "period_type": "monthly", "source": "plan",  "field": "sla_target"},
    {"kpi_code": "response_time_hours",        "period_type": "daily",   "source": "plan",  "field": "response_time_target"},
]


async def sync_plan_to_kpi_config(
    db: AsyncSession,
    plan: KpiPlan,
    month: int,
    target_officer_id: Optional[int] = None,
) -> Dict[str, int]:
    """
    Push KPI plan targets into KpiConfig (7 monthly KPIs) + KpiTarget (1 annual KPI)
    for active officers in the plan's unit.

    Args:
        plan: KpiPlan (with months eager-loaded)
        month: Target month (1-12)
        target_officer_id: If set, sync only this officer (for orphan officer plans).
                           If None, sync all active officers in unit.

    Resolution order per officer:
      1. Officer plan (if exists) → use officer plan's month data
      2. Unit plan (fallback) → use this plan's month data

    Idempotent: upserts by unique scope (officer_id, kpi_code, period_type,
    effective_year, effective_month). Running twice produces the same result.

    NULL derived KPI → COALESCE to 0 (spec §8.3: prevents DEFAULT_KPIS fallback).
    Does NOT commit — caller (Celery task) commits.

    Returns: {"officers_synced": N, "configs_upserted": N}
    """
    from sqlalchemy import select
    from app.models.config import KpiConfig, KpiTarget
    from app.models.user import User
    from app.repositories.kpi_planning_repository import KpiPlanningRepository

    repo = KpiPlanningRepository(db)
    stats = {"officers_synced": 0, "configs_upserted": 0}

    # --- Find the target plan month ---
    plan_month = None
    if plan.months:
        plan_month = next((m for m in plan.months if m.month == month), None)
    if plan_month is None:
        log.warning("sync_plan_to_kpi_config: month not found", plan_id=plan.id, month=month)
        return stats

    # --- Get officers to sync ---
    if target_officer_id is not None:
        # Orphan officer plan: verify officer is active + belongs to this unit
        row = (await db.execute(
            select(User.id, User.unit_id)
            .where(
                User.id == target_officer_id,
                User.unit_id == plan.unit_id,
                User.role == "officer",
                User.status == "active",
            )
        )).one_or_none()
        officers = [row] if row is not None else []
    else:
        # Unit plan: sync all active officers in unit
        result = await db.execute(
            select(User.id, User.unit_id)
            .where(
                User.unit_id == plan.unit_id,
                User.role == "officer",
                User.status == "active",
            )
        )
        officers = result.all()

    if not officers:
        log.info("sync: no officers to sync", unit_id=plan.unit_id)
        return stats

    for officer_id, officer_unit_id in officers:
        # --- Resolve effective plan: officer plan > unit plan ---
        effective_plan = plan
        effective_month_data = plan_month

        officer_plan = await repo.get_active_plan_by_scope(
            unit_id=plan.unit_id,
            fiscal_year=plan.fiscal_year,
            officer_id=officer_id,
            with_months=True,
        )
        if officer_plan is not None:
            effective_plan = officer_plan
            opm = next((m for m in officer_plan.months if m.month == month), None)
            if opm is not None:
                effective_month_data = opm

        # --- Upsert 7 KPI monthly → KpiConfig ---
        for mapping in KPI_SYNC_MAPPING:
            kpi_code = mapping["kpi_code"]
            period_type = mapping["period_type"]

            # Read value from correct source
            if mapping["source"] == "month":
                raw_value = getattr(effective_month_data, mapping["field"])
            else:  # "plan"
                raw_value = getattr(effective_plan, mapping["field"])

            # COALESCE NULL → 0 (spec §8.3)
            target_value = float(raw_value) if raw_value is not None else 0.0

            # Upsert: find existing monthly record for this exact scope
            existing = await _find_monthly_kpi_config(
                db, kpi_code=kpi_code, period_type=period_type,
                officer_id=officer_id, unit_id=plan.unit_id,
                effective_year=plan.fiscal_year, effective_month=month,
            )

            if existing is not None:
                existing.target_value = target_value
                existing.source_plan_id = effective_plan.id
            else:
                db.add(KpiConfig(
                    kpi_code=kpi_code,
                    target_value=target_value,
                    period_type=period_type,
                    officer_id=officer_id,
                    unit_id=plan.unit_id,
                    effective_month=month,
                    effective_year=plan.fiscal_year,
                    source_plan_id=effective_plan.id,
                    is_active=True,
                ))
            stats["configs_upserted"] += 1

        # --- Upsert enrollments_annual → KpiTarget ---
        annual_target_value = effective_plan.annual_enrollment_target
        existing_target = await _find_annual_kpi_target(
            db, officer_id=officer_id, unit_id=plan.unit_id,
            fiscal_year=plan.fiscal_year,
        )
        if existing_target is not None:
            existing_target.annual_target = annual_target_value
        else:
            db.add(KpiTarget(
                kpi_code="enrollments_annual",
                annual_target=annual_target_value,
                fiscal_year=plan.fiscal_year,
                officer_id=officer_id,
                unit_id=plan.unit_id,
                is_active=True,
                achieved_ytd=0,
            ))
        stats["configs_upserted"] += 1

        stats["officers_synced"] += 1

    await db.flush()

    log.info(
        "sync_plan_to_kpi_config completed",
        plan_id=plan.id, month=month,
        officers=stats["officers_synced"],
        upserted=stats["configs_upserted"],
    )
    return stats


async def _find_monthly_kpi_config(
    db: AsyncSession,
    kpi_code: str,
    period_type: str,
    officer_id: int,
    unit_id: int,
    effective_year: int,
    effective_month: int,
):
    """Find existing active monthly KpiConfig record (for upsert)."""
    from sqlalchemy import select
    from app.models.config import KpiConfig

    result = await db.execute(
        select(KpiConfig).where(
            KpiConfig.kpi_code == kpi_code,
            KpiConfig.period_type == period_type,
            KpiConfig.officer_id == officer_id,
            KpiConfig.unit_id == unit_id,
            KpiConfig.effective_year == effective_year,
            KpiConfig.effective_month == effective_month,
            KpiConfig.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def _find_annual_kpi_target(
    db: AsyncSession,
    officer_id: int,
    unit_id: int,
    fiscal_year: int,
):
    """Find existing active annual KpiTarget record (for upsert)."""
    from sqlalchemy import select
    from app.models.config import KpiTarget

    result = await db.execute(
        select(KpiTarget).where(
            KpiTarget.kpi_code == "enrollments_annual",
            KpiTarget.officer_id == officer_id,
            KpiTarget.unit_id == unit_id,
            KpiTarget.fiscal_year == fiscal_year,
            KpiTarget.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


# =============================================================================
# OVERRIDE / RESET (spec §5.1 — Phase B1)
# =============================================================================

# Fields that can be overridden per-month
OVERRIDABLE_FIELDS = frozenset({
    "consultations_daily",
    "conversion_rate",
    "win_rate",
    "consultation_effectiveness",
})


async def override_month_kpi(
    db: AsyncSession,
    plan_month: KpiPlanMonth,
    overrides: Dict[str, Any],
    reason: str,
    user_id: int,
) -> Tuple[KpiPlanMonth, Callback]:
    """
    Override 1+ derived KPI fields for a specific plan month.

    Merges into overridden_fields (does not clobber existing overrides).
    Records reason, who, when. Does NOT commit.
    """
    from datetime import datetime, timezone

    # Guard: must override at least 1 field
    if not overrides:
        raise BusinessRuleViolation("overrides không được rỗng — phải override ít nhất 1 field")

    # Validate field names
    invalid = set(overrides.keys()) - OVERRIDABLE_FIELDS
    if invalid:
        raise BusinessRuleViolation(
            f"Không thể override field: {invalid}. Chỉ cho phép: {sorted(OVERRIDABLE_FIELDS)}"
        )

    # Validate values (reject None and bool)
    for field, value in overrides.items():
        if value is None or isinstance(value, bool):
            raise BusinessRuleViolation(f"Override value cho '{field}' phải là số, nhận {value!r}")
        if field == "consultations_daily":
            if not isinstance(value, (int, float)) or value != int(value) or int(value) < 0:
                raise BusinessRuleViolation(f"consultations_daily phải là integer >= 0, nhận {value}")
        else:
            # conversion_rate, win_rate, consultation_effectiveness: float 0..100
            try:
                fval = float(value)
            except (TypeError, ValueError):
                raise BusinessRuleViolation(f"'{field}' phải là số, nhận {value}")
            if not (0 <= fval <= 100):
                raise BusinessRuleViolation(f"'{field}' phải trong 0..100, nhận {fval}")

    # Merge overrides
    existing_overridden = dict(plan_month.overridden_fields or {})
    for field, value in overrides.items():
        if field == "consultations_daily":
            setattr(plan_month, field, int(value))
        else:
            setattr(plan_month, field, Decimal(str(value)))
        existing_overridden[field] = True

    plan_month.overridden_fields = existing_overridden
    plan_month.override_reason = reason
    plan_month.overridden_by = user_id
    plan_month.overridden_at = datetime.now(timezone.utc)

    await db.flush()

    log.info(
        "Month KPI overridden",
        month_id=plan_month.id, fields=list(overrides.keys()),
        reason=reason, user_id=user_id,
    )
    return plan_month, None


async def reset_month_override(
    db: AsyncSession,
    plan_month: KpiPlanMonth,
    fields: Optional[List[str]],
    user_id: int,
) -> Tuple[KpiPlanMonth, Callback]:
    """
    Reset overrides and recalculate derived KPIs.

    fields=None → clear ALL overrides, recalculate all derived fields.
    fields=["consultations_daily"] → remove only that field, recalculate it.
    Does NOT commit.
    """
    existing_overridden = dict(plan_month.overridden_fields or {})

    if fields is None:
        # Reset all — recalculate ALL derived fields (spec §5.1)
        fields_to_reset = set(OVERRIDABLE_FIELDS)
        plan_month.overridden_fields = {}
        plan_month.override_reason = None
        plan_month.overridden_by = None
        plan_month.overridden_at = None
    else:
        # Validate field names
        invalid = set(fields) - OVERRIDABLE_FIELDS
        if invalid:
            raise BusinessRuleViolation(
                f"Không thể reset field: {invalid}. Chỉ cho phép: {sorted(OVERRIDABLE_FIELDS)}"
            )
        fields_to_reset = set(fields) & set(existing_overridden.keys())
        for f in fields_to_reset:
            existing_overridden.pop(f, None)
        plan_month.overridden_fields = existing_overridden
        # Keep reason/by/at if still has other overrides, clear if empty
        if not existing_overridden:
            plan_month.override_reason = None
            plan_month.overridden_by = None
            plan_month.overridden_at = None

    # Recalculate only the reset fields
    if fields_to_reset:
        m_t = plan_month.enrollment_target
        wd_t = plan_month.working_days
        k_t = float(plan_month.k_factor)
        l_t = plan_month.lead_forecast
        c_t = plan_month.close_forecast

        derived = compute_derived_kpis(m_t, wd_t, k_t, l_t, c_t)
        for field in fields_to_reset:
            if field in derived:
                setattr(plan_month, field, derived[field])

    await db.flush()

    log.info(
        "Month override reset",
        month_id=plan_month.id,
        reset_fields=list(fields_to_reset) if fields_to_reset else "all",
        user_id=user_id,
    )
    return plan_month, None


# =============================================================================
# AUTO-CALIBRATION (spec §2.3, §5.1 — Phase B3)
# =============================================================================

def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


async def recalibrate_factors(
    db: AsyncSession,
    plan_id: int,
    up_to_month: int,
) -> Tuple[KpiPlan, Callback]:
    """
    Auto-calibration: use actual data from recent months to update k_t, L_t, C_t
    for future months. Then regenerate derived KPIs for those months.

    Damping (spec §2.3):
      - First calibration (no actuals exist): ±30%
      - Subsequent calibrations: ±15%

    Only updates months > up_to_month (future). Does NOT commit.

    Args:
        plan_id: KPI plan ID
        up_to_month: Current month (inclusive). Months after this are recalibrated.

    Returns: (KpiPlan, callback)
    """
    if not (1 <= up_to_month <= 12):
        raise BusinessRuleViolation(f"up_to_month phải trong 1..12, nhận {up_to_month}")

    from sqlalchemy import select, exists
    from app.services.historical_metrics_service import (
        get_historical_k_factor,
        get_historical_lead_count,
        get_historical_close_count,
    )
    from app.repositories.kpi_planning_repository import KpiPlanningRepository

    repo = KpiPlanningRepository(db)
    plan = await repo.get_plan_by_id(plan_id, with_months=True)
    if plan is None:
        raise ResourceNotFoundError("KpiPlan", plan_id)

    # --- Detect is_first_calibration (spec §2.3) ---
    # Check if ANY plan month in this scope has actual_enrollments filled
    has_actuals = (await db.execute(
        select(
            exists().where(
                KpiPlanMonth.plan_id == plan.id,
                KpiPlanMonth.actual_enrollments.isnot(None),
            )
        )
    )).scalar()
    is_first_calibration = not has_actuals

    # Damping bounds
    if is_first_calibration:
        damping_lo, damping_hi = 0.70, 1.30  # ±30%
    else:
        damping_lo, damping_hi = 0.85, 1.15  # ±15%

    # --- Get historical factors ---
    officer_id = plan.officer_id
    unit_id = plan.unit_id

    new_k = await get_historical_k_factor(
        db, officer_id=officer_id, unit_id=unit_id,
        reference_year=plan.fiscal_year, reference_month=up_to_month,
    )

    calibrated_count = 0

    # --- Update future months ---
    months_by_num = {m.month: m for m in plan.months}
    for month_num in range(up_to_month + 1, 13):
        pm = months_by_num.get(month_num)
        if pm is None:
            continue

        overridden = pm.overridden_fields or {}

        # k_factor: always update (not in OVERRIDABLE_FIELDS, it's an input factor)
        current_k = float(pm.k_factor)
        if current_k > 0:
            damped_k = _clamp(new_k, current_k * damping_lo, current_k * damping_hi)
        else:
            damped_k = new_k  # current=0 → pass-through (no meaningful bounds)
        pm.k_factor = Decimal(str(round(damped_k, 2)))

        # L_t: lead_forecast
        m_t = pm.enrollment_target
        new_l = await get_historical_lead_count(
            db, officer_id=officer_id, unit_id=unit_id,
            reference_year=plan.fiscal_year, reference_month=up_to_month,
            default_m_t=m_t,
        )
        if new_l is not None:
            current_l = pm.lead_forecast if pm.lead_forecast is not None else 6 * m_t
            if current_l > 0:
                damped_l = _clamp(new_l, current_l * damping_lo, current_l * damping_hi)
            else:
                damped_l = new_l
            pm.lead_forecast = max(1, round(damped_l))

        # C_t: close_forecast
        new_c = await get_historical_close_count(
            db, officer_id=officer_id, unit_id=unit_id,
            reference_year=plan.fiscal_year, reference_month=up_to_month,
            default_m_t=m_t,
        )
        if new_c is not None:
            current_c = pm.close_forecast if pm.close_forecast is not None else 3 * m_t
            if current_c > 0:
                damped_c = _clamp(new_c, current_c * damping_lo, current_c * damping_hi)
            else:
                damped_c = new_c
            pm.close_forecast = max(1, round(damped_c))

        # Regenerate derived KPIs for this month (respects overridden_fields)
        derived = compute_derived_kpis(
            m_t, pm.working_days, float(pm.k_factor),
            pm.lead_forecast, pm.close_forecast,
        )
        for field, value in derived.items():
            if field not in overridden:
                setattr(pm, field, value)

        calibrated_count += 1

    await db.flush()

    log.info(
        "recalibrate_factors completed",
        plan_id=plan_id, up_to_month=up_to_month,
        is_first=is_first_calibration,
        damping=f"{damping_lo:.0%}/{damping_hi:.0%}",
        months_calibrated=calibrated_count,
    )
    return plan, None


# =============================================================================
# FILL MONTH ACTUALS (spec §5.1 — Phase B4)
# =============================================================================

async def fill_month_actuals(
    db: AsyncSession,
    plan_id: int,
    month: int,
) -> Tuple[KpiPlan, Callback]:
    """
    Fill actual performance fields for a completed month.

    Populates 6 actual fields on KpiPlanMonth:
      - actual_enrollments
      - actual_consultations_avg  (daily avg = total / working_days)
      - actual_conversion_rate    (enrollments / new_leads * 100)
      - actual_win_rate           (enrollments / closed_leads * 100)
      - actual_consultation_effectiveness (enrollments / consulted_closed * 100)
      - actual_sla_compliance_rate (% leads with first response within SLA)

    Only fills completed months. Scoped to plan's unit/officer. Does NOT commit.
    """
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    from sqlalchemy import select, func, literal_column
    from app.models.lead import Consultation, Lead
    from app.models.pipeline import ConsultationStatus, PipelineStage
    from app.repositories.kpi_planning_repository import KpiPlanningRepository
    from app.services.calendar_service import count_working_days

    if not (1 <= month <= 12):
        raise BusinessRuleViolation(f"month phải trong 1..12, nhận {month}")

    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

    repo = KpiPlanningRepository(db)
    plan = await repo.get_plan_by_id(plan_id, with_months=True)
    if plan is None:
        raise ResourceNotFoundError("KpiPlan", plan_id)

    # Guard: only fill completed months (not current or future)
    now_local = dt.now(VN_TZ)
    if plan.fiscal_year == now_local.year and month >= now_local.month:
        raise BusinessRuleViolation(
            f"Chỉ fill actuals cho tháng đã kết thúc. Tháng {month}/{plan.fiscal_year} chưa kết thúc."
        )
    if plan.fiscal_year > now_local.year:
        raise BusinessRuleViolation(
            f"Chỉ fill actuals cho tháng đã kết thúc. Năm {plan.fiscal_year} chưa bắt đầu."
        )

    pm = next((m for m in plan.months if m.month == month), None)
    if pm is None:
        raise ResourceNotFoundError("KpiPlanMonth", f"plan={plan_id}, month={month}")

    year = plan.fiscal_year
    month_start = dt(year, month, 1, tzinfo=VN_TZ)
    month_end = dt(year + 1, 1, 1, tzinfo=VN_TZ) if month == 12 else dt(year, month + 1, 1, tzinfo=VN_TZ)

    officer_id = plan.officer_id
    unit_id = plan.unit_id

    def _lead_scope():
        f = [Lead.deleted_at.is_(None), Lead.unit_id == unit_id]
        if officer_id is not None:
            f.append(Lead.assigned_officer_id == officer_id)
        return f

    # --- 1. actual_enrollments ---
    enroll_count = (await db.execute(
        select(func.count(Lead.id))
        .join(PipelineStage, Lead.pipeline_stage_id == PipelineStage.id)
        .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
        .where(
            *_lead_scope(),
            Lead.updated_at >= month_start, Lead.updated_at < month_end,
            PipelineStage.is_final_stage == True,  # noqa: E712
            ConsultationStatus.counts_for_funnel == True,  # noqa: E712
            ConsultationStatus.outcome_type == "positive",
        )
    )).scalar_one()
    pm.actual_enrollments = enroll_count

    # --- 2. actual_consultations_avg (human consultations / working days) ---
    # Always join Lead to enforce unit scope (officer may have transferred units)
    consult_q = (
        select(func.count(Consultation.id))
        .join(Lead, Consultation.lead_id == Lead.id)
        .where(
            Consultation.deleted_at.is_(None),
            Consultation.method.is_distinct_from("system"),
            Consultation.consultation_date >= month_start,
            Consultation.consultation_date < month_end,
            Lead.unit_id == unit_id,
        )
    )
    if officer_id is not None:
        consult_q = consult_q.where(Consultation.officer_id == officer_id)
    consult_count = (await db.execute(consult_q)).scalar_one()

    wd = await count_working_days(db, year, month)
    pm.actual_consultations_avg = Decimal(str(round(consult_count / wd, 2))) if wd > 0 else None

    # --- 3. actual_conversion_rate (enrollments / new leads * 100) ---
    new_leads = (await db.execute(
        select(func.count(Lead.id)).where(
            *_lead_scope(),
            Lead.created_at >= month_start, Lead.created_at < month_end,
        )
    )).scalar_one()
    pm.actual_conversion_rate = Decimal(str(round(enroll_count / new_leads * 100, 2))) if new_leads > 0 else None

    # --- 4. actual_win_rate (enrollments / closed leads * 100) ---
    closed_leads = (await db.execute(
        select(func.count(Lead.id))
        .join(PipelineStage, Lead.pipeline_stage_id == PipelineStage.id)
        .where(
            *_lead_scope(),
            Lead.updated_at >= month_start, Lead.updated_at < month_end,
            PipelineStage.is_final_stage == True,  # noqa: E712
        )
    )).scalar_one()
    pm.actual_win_rate = Decimal(str(round(enroll_count / closed_leads * 100, 2))) if closed_leads > 0 else None

    # --- 5. actual_consultation_effectiveness (enrollments / consulted-then-closed * 100) ---
    consulted_closed = (await db.execute(
        select(func.count(func.distinct(Lead.id)))
        .join(PipelineStage, Lead.pipeline_stage_id == PipelineStage.id)
        .join(Consultation, Consultation.lead_id == Lead.id)
        .where(
            *_lead_scope(),
            Lead.updated_at >= month_start, Lead.updated_at < month_end,
            PipelineStage.is_final_stage == True,  # noqa: E712
            Consultation.deleted_at.is_(None),
            Consultation.method.is_distinct_from("system"),
        )
    )).scalar_one()
    pm.actual_consultation_effectiveness = (
        Decimal(str(round(enroll_count / consulted_closed * 100, 2))) if consulted_closed > 0 else None
    )

    # --- 6. actual_sla_compliance_rate (% leads with first response within SLA) ---
    assigned_in_month = (await db.execute(
        select(func.count(Lead.id)).where(
            *_lead_scope(),
            Lead.assigned_at >= month_start, Lead.assigned_at < month_end,
            Lead.assigned_officer_id.isnot(None),
        )
    )).scalar_one()

    if assigned_in_month > 0:
        # Keep float precision: 1.5h → 1 hour 30 min, not 1h
        response_seconds = int(float(plan.response_time_target) * 3600)
        sla_met = (await db.execute(
            select(func.count(func.distinct(Lead.id)))
            .join(Consultation, Consultation.lead_id == Lead.id)
            .where(
                *_lead_scope(),
                Lead.assigned_at >= month_start, Lead.assigned_at < month_end,
                Lead.assigned_officer_id.isnot(None),
                Consultation.deleted_at.is_(None),
                Consultation.method.is_distinct_from("system"),
                # First consultation must be AFTER assignment AND within SLA window
                Consultation.consultation_date >= Lead.assigned_at,
                Consultation.consultation_date <= Lead.assigned_at + func.make_interval(
                    0, 0, 0, 0, 0, 0, literal_column(str(response_seconds))
                ),
            )
        )).scalar_one()
        pm.actual_sla_compliance_rate = Decimal(str(round(sla_met / assigned_in_month * 100, 2)))
    else:
        pm.actual_sla_compliance_rate = None

    await db.flush()

    log.info(
        "fill_month_actuals completed",
        plan_id=plan_id, month=month,
        enrollments=enroll_count,
        consult_avg=str(pm.actual_consultations_avg),
        conv_rate=str(pm.actual_conversion_rate),
        win_rate=str(pm.actual_win_rate),
    )
    return plan, None
