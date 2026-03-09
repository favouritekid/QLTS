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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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

    # --- Check duplicate active plan (scope-aware) ---
    dup_filters = [
        KpiPlan.unit_id == unit_id,
        KpiPlan.fiscal_year == fiscal_year,
        KpiPlan.is_active == True,  # noqa: E712
    ]
    if officer_id is None:
        dup_filters.append(KpiPlan.officer_id.is_(None))
        scope_label = f"unit plan (unit_id={unit_id})"
    else:
        dup_filters.append(KpiPlan.officer_id == officer_id)
        scope_label = f"officer plan (unit_id={unit_id}, officer_id={officer_id})"

    existing = await db.execute(select(KpiPlan.id).where(*dup_filters))
    if existing.scalar_one_or_none() is not None:
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
    plan = await db.execute(
        select(KpiPlan)
        .options(selectinload(KpiPlan.months))
        .where(KpiPlan.id == plan_id, KpiPlan.is_active == True)  # noqa: E712
    )
    plan = plan.scalar_one_or_none()
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
