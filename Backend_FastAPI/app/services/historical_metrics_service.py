# app/services/historical_metrics_service.py
"""
Historical Metrics Service — Phase B2

Computes historical factors for KPI planning calibration:
- k_t: consultations per enrollment (EMA weighted)
- L_t: lead forecast (monthly average of new leads)
- C_t: close forecast (monthly average of closed leads)

All queries use Asia/Ho_Chi_Minh timezone with range [start, end).
Service is read-only — does NOT commit.
"""
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Consultation, Lead
from app.models.pipeline import ConsultationStatus, PipelineStage

log = structlog.get_logger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Defaults from spec §2.2
DEFAULT_K_FACTOR = 7.0
DEFAULT_L_MULTIPLIER = 6  # L_t = 6 * M_t
DEFAULT_C_MULTIPLIER = 3  # C_t = 3 * M_t


# =============================================================================
# INTERNAL: Month range helpers
# =============================================================================

def _month_range(year: int, month: int) -> Tuple[datetime, datetime]:
    """Return [start, end) for a calendar month in VN timezone."""
    start = datetime(year, month, 1, tzinfo=VN_TZ)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=VN_TZ)
    else:
        end = datetime(year, month + 1, 1, tzinfo=VN_TZ)
    return start, end


def _previous_months(year: int, month: int, n: int) -> List[Tuple[int, int]]:
    """Return list of (year, month) for n months before the given month, newest first."""
    result = []
    y, m = year, month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        result.append((y, m))
    return result


# =============================================================================
# EMA WEIGHTING (spec §2.3)
# =============================================================================

def _apply_ema(values: List[float]) -> float:
    """
    Apply EMA weighting to monthly values.

    values[0] = most recent month, values[1] = month before, ...
    Fallback rules (spec §2.3):
    - 0 months: caller handles (return default)
    - 1 month:  direct value (no weighting)
    - 2 months: 0.6 * newest + 0.4 * older
    - 3+ months: 0.5 * newest + 0.3 * middle + 0.2 * oldest
    """
    n = len(values)
    if n == 0:
        raise ValueError("_apply_ema requires at least 1 value")
    if n == 1:
        return values[0]
    if n == 2:
        return 0.6 * values[0] + 0.4 * values[1]
    # n >= 3: use last 3 only
    return 0.5 * values[0] + 0.3 * values[1] + 0.2 * values[2]


# =============================================================================
# k_t — CONSULTATIONS PER ENROLLMENT (spec §5.3)
# =============================================================================

async def get_historical_k_factor(
    db: AsyncSession,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    months_back: int = 3,
    reference_year: Optional[int] = None,
    reference_month: Optional[int] = None,
) -> float:
    """
    k_t = total_consultations / total_enrollments per month, EMA weighted.

    Consultations MUST exclude method='system' (IS DISTINCT FROM).
    Guard: total_enrollments = 0 in a month → skip that month.
    Fallback: no data → return DEFAULT_K_FACTOR (7.0).
    """
    now = datetime.now(VN_TZ)
    ref_year = reference_year or now.year
    ref_month = reference_month or now.month
    prev_months = _previous_months(ref_year, ref_month, months_back)

    monthly_k: List[float] = []

    for y, m in prev_months:
        start, end = _month_range(y, m)

        # Count human consultations (exclude system)
        consult_filters = [
            Consultation.consultation_date >= start,
            Consultation.consultation_date < end,
            Consultation.deleted_at.is_(None),
            Consultation.method.is_distinct_from("system"),
        ]
        if officer_id is not None:
            consult_filters.append(Consultation.officer_id == officer_id)

        consult_count = (await db.execute(
            select(func.count(Consultation.id)).where(*consult_filters)
        )).scalar_one()

        # Count enrollments (final stage + positive outcome)
        enroll_filters = [
            Lead.updated_at >= start,
            Lead.updated_at < end,
            Lead.deleted_at.is_(None),
            PipelineStage.is_final_stage == True,  # noqa: E712
            ConsultationStatus.counts_for_funnel == True,  # noqa: E712
            ConsultationStatus.outcome_type == "positive",
        ]
        if officer_id is not None:
            enroll_filters.append(Lead.assigned_officer_id == officer_id)
        if unit_id is not None and officer_id is None:
            enroll_filters.append(Lead.unit_id == unit_id)

        enroll_count = (await db.execute(
            select(func.count(Lead.id))
            .join(PipelineStage, Lead.pipeline_stage_id == PipelineStage.id)
            .join(ConsultationStatus, Lead.consultation_status_id == ConsultationStatus.id)
            .where(*enroll_filters)
        )).scalar_one()

        if enroll_count > 0:
            monthly_k.append(consult_count / enroll_count)

    if not monthly_k:
        log.debug("k_factor: no data, using default", default=DEFAULT_K_FACTOR)
        return DEFAULT_K_FACTOR

    result = _apply_ema(monthly_k)
    log.debug("k_factor computed", months=len(monthly_k), result=round(result, 2))
    return round(result, 2)


# =============================================================================
# L_t — LEAD FORECAST (spec §5.3)
# =============================================================================

async def get_historical_lead_count(
    db: AsyncSession,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    months_back: int = 3,
    reference_year: Optional[int] = None,
    reference_month: Optional[int] = None,
    default_m_t: Optional[int] = None,
) -> Optional[int]:
    """
    L_t = average new leads per month over the last N months, EMA weighted.

    "New lead" = Lead.created_at falls within the month range.
    Guard: no data → return 6 * M_t (default) or None if M_t not provided.
    """
    now = datetime.now(VN_TZ)
    ref_year = reference_year or now.year
    ref_month = reference_month or now.month
    prev_months = _previous_months(ref_year, ref_month, months_back)

    monthly_leads: List[float] = []

    for y, m in prev_months:
        start, end = _month_range(y, m)

        lead_filters = [
            Lead.created_at >= start,
            Lead.created_at < end,
            Lead.deleted_at.is_(None),
        ]
        if officer_id is not None:
            lead_filters.append(Lead.assigned_officer_id == officer_id)
        if unit_id is not None and officer_id is None:
            lead_filters.append(Lead.unit_id == unit_id)

        count = (await db.execute(
            select(func.count(Lead.id)).where(*lead_filters)
        )).scalar_one()

        monthly_leads.append(float(count))

    # Filter out zero-months only if ALL are zero (treat sparse data as valid)
    if not monthly_leads or all(v == 0 for v in monthly_leads):
        if default_m_t is not None:
            return DEFAULT_L_MULTIPLIER * default_m_t
        return None

    result = _apply_ema(monthly_leads)
    return max(1, round(result))


# =============================================================================
# C_t — CLOSE FORECAST (spec §5.3)
# =============================================================================

async def get_historical_close_count(
    db: AsyncSession,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    months_back: int = 3,
    reference_year: Optional[int] = None,
    reference_month: Optional[int] = None,
    default_m_t: Optional[int] = None,
) -> Optional[int]:
    """
    C_t = average closed leads per month (won + lost), EMA weighted.

    "Closed" = Lead reached a final pipeline stage (is_final_stage=TRUE)
    with updated_at in the month range.
    Guard: no data → return 3 * M_t (default) or None if M_t not provided.
    """
    now = datetime.now(VN_TZ)
    ref_year = reference_year or now.year
    ref_month = reference_month or now.month
    prev_months = _previous_months(ref_year, ref_month, months_back)

    monthly_closed: List[float] = []

    for y, m in prev_months:
        start, end = _month_range(y, m)

        close_filters = [
            Lead.updated_at >= start,
            Lead.updated_at < end,
            Lead.deleted_at.is_(None),
            PipelineStage.is_final_stage == True,  # noqa: E712
        ]
        if officer_id is not None:
            close_filters.append(Lead.assigned_officer_id == officer_id)
        if unit_id is not None and officer_id is None:
            close_filters.append(Lead.unit_id == unit_id)

        count = (await db.execute(
            select(func.count(Lead.id))
            .join(PipelineStage, Lead.pipeline_stage_id == PipelineStage.id)
            .where(*close_filters)
        )).scalar_one()

        monthly_closed.append(float(count))

    if not monthly_closed or all(v == 0 for v in monthly_closed):
        if default_m_t is not None:
            return DEFAULT_C_MULTIPLIER * default_m_t
        return None

    result = _apply_ema(monthly_closed)
    return max(1, round(result))
