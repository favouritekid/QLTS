"""
V12 Phase B: Exact drill-down service for dashboard click-through.

These queries intentionally mirror the semantics of the dashboard metrics so
the record-level evidence matches the headline numbers as closely as possible.
"""
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import models


def _parse_iso_date(value: Optional[str]) -> Optional[date_type]:
    if not value:
        return None
    try:
        return date_type.fromisoformat(value)
    except ValueError:
        return None


def _date_bounds(
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[Optional[date_type], Optional[date_type], Optional[datetime], Optional[datetime]]:
    """Convert ISO date strings to timezone-aware datetime boundaries.

    Uses Asia/Ho_Chi_Minh to match KPI counting semantics
    (get_kpi_stats / get_aggregated_kpis use VN day boundaries).
    Frontend sends dates in VN context via todayVN().
    """
    from zoneinfo import ZoneInfo
    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

    parsed_start = _parse_iso_date(start_date)
    parsed_end = _parse_iso_date(end_date)

    start_dt = (
        datetime(parsed_start.year, parsed_start.month, parsed_start.day, tzinfo=VN_TZ)
        if parsed_start
        else None
    )
    end_exclusive = (
        datetime(parsed_end.year, parsed_end.month, parsed_end.day, tzinfo=VN_TZ) + timedelta(days=1)
        if parsed_end
        else None
    )
    return parsed_start, parsed_end, start_dt, end_exclusive


def _apply_datetime_bounds(
    conditions: list,
    column,
    start_dt: Optional[datetime],
    end_exclusive: Optional[datetime],
) -> None:
    if start_dt is not None:
        conditions.append(column >= start_dt)
    if end_exclusive is not None:
        conditions.append(column < end_exclusive)


def _effective_scope_payload(ctx) -> Dict[str, Any]:
    return {
        "scope_kind": ctx.scope_kind,
        "label": ctx.label,
        "forced_by_role": ctx.forced_by_role,
        "includes_descendants": ctx.includes_descendants,
    }


def _build_metadata(
    ctx,
    metric_key: str,
    start_date: Optional[str],
    end_date: Optional[str],
    page: int,
    page_size: int,
    total_count: int,
) -> Dict[str, Any]:
    return {
        "metric_key": metric_key,
        "exactness": "exact",
        "effective_scope": _effective_scope_payload(ctx),
        "effective_date_context": {
            "start_date": start_date,
            "end_date": end_date,
        } if start_date or end_date else None,
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
    }


def _normalize_outcome_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return getattr(value, "value", value)


def _row_outcome(outcome_type: Any, new_status: Optional[str]) -> str:
    normalized = _normalize_outcome_value(outcome_type)
    if normalized in {"positive", "negative", "neutral"}:
        return normalized
    if new_status in {"converted", "enrolled"}:
        return "positive"
    if new_status in {"rejected", "unqualified", "lost"}:
        return "negative"
    return "neutral"


def _cohort_result(is_final: Optional[bool], outcome_type: Any) -> str:
    normalized = _normalize_outcome_value(outcome_type)
    if is_final and normalized == "positive":
        return "converted"
    if is_final:
        return "lost"
    return "open"


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _sort_direction(column, order: str):
    return column.desc() if order == "desc" else column.asc()


def _consulted_leads_subquery(officer_ids: list[int]):
    return (
        select(models.Consultation.lead_id)
        .where(
            models.Consultation.deleted_at.is_(None),
            models.Consultation.officer_id.in_(officer_ids),
        )
        .distinct()
        .subquery()
    )


async def get_consultations_drilldown(
    db: AsyncSession,
    ctx,  # DashboardScopeContext
    metric_key: str,
    start_date: str = None,
    end_date: str = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "consultation_date",
    order: str = "desc",
    stage_id: str = None,
    loss_reason_code: str = None,
    consultation_kind: str = None,
    response_breach_only: bool = False,
) -> Dict[str, Any]:
    _, _, start_dt, end_exclusive = _date_bounds(start_date, end_date)
    officer_alias = aliased(models.User)
    # Default to human consultations for KPI-card metrics to match
    # dashboard counting (get_kpi_stats / get_aggregated_kpis exclude system).
    _human_default_metrics = {"loss_reason", "consultations_today", "consultations_avg_per_day"}
    effective_kind = consultation_kind or ("human" if metric_key in _human_default_metrics else None)

    conditions = [
        models.Consultation.deleted_at.is_(None),
        models.Lead.deleted_at.is_(None),
    ]
    if ctx.effective_officer_ids:
        conditions.append(models.Consultation.officer_id.in_(ctx.effective_officer_ids))

    _apply_datetime_bounds(conditions, models.Consultation.consultation_date, start_dt, end_exclusive)

    if stage_id:
        conditions.append(models.Lead.pipeline_stage_id == stage_id)
    if loss_reason_code:
        conditions.append(models.Consultation.loss_reason_code == loss_reason_code)
    if effective_kind == "human":
        conditions.append(models.Consultation.method.is_distinct_from("system"))
    elif effective_kind == "system":
        conditions.append(models.Consultation.method == "system")
    if response_breach_only:
        conditions.extend([
            models.Lead.assigned_at.isnot(None),
            models.Consultation.consultation_date > models.Lead.assigned_at + timedelta(hours=24),
        ])

    base_query = (
        select(
            models.Consultation.id.label("consultation_id"),
            models.Consultation.lead_id.label("lead_id"),
            models.Lead.full_name.label("lead_name"),
            models.Consultation.officer_id.label("officer_id"),
            officer_alias.full_name.label("officer_name"),
            models.Consultation.consultation_date.label("consultation_date"),
            models.Consultation.loss_reason_code.label("loss_reason_code"),
            models.Consultation.loss_reason_note.label("loss_reason_note"),
            models.Lead.status.label("status"),
        )
        .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
        .outerjoin(officer_alias, models.Consultation.officer_id == officer_alias.id)
        .where(*conditions)
    )

    count_query = select(func.count()).select_from(base_query.subquery())
    total_count = (await db.execute(count_query)).scalar() or 0

    sort_map = {
        "consultation_date": models.Consultation.consultation_date,
        "lead_name": models.Lead.full_name,
        "loss_reason_code": models.Consultation.loss_reason_code,
        "status": models.Lead.status,
    }
    sort_column = sort_map.get(sort_by, models.Consultation.consultation_date)
    data_query = (
        base_query
        .order_by(_sort_direction(sort_column, order), models.Consultation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    rows = [
        {
            "consultation_id": row.consultation_id,
            "lead_id": row.lead_id,
            "lead_name": row.lead_name,
            "officer_id": row.officer_id,
            "officer_name": row.officer_name,
            "consultation_date": _serialize_datetime(row.consultation_date),
            "loss_reason_code": row.loss_reason_code,
            "loss_reason_note": row.loss_reason_note,
            "status": row.status,
        }
        for row in (await db.execute(data_query)).mappings()
    ]

    return {
        "metadata": _build_metadata(ctx, metric_key, start_date, end_date, page, page_size, total_count),
        "rows": rows,
    }


async def get_transitions_drilldown(
    db: AsyncSession,
    ctx,  # DashboardScopeContext
    metric_key: str,
    start_date: str = None,
    end_date: str = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "changed_at",
    order: str = "desc",
    stage_id: str = None,
    outcome: str = None,
    final_only: bool = False,
    consulted_only: bool = False,
) -> Dict[str, Any]:
    _, _, start_dt, end_exclusive = _date_bounds(start_date, end_date)

    if metric_key == "high_loss":
        outcome = outcome or "negative"
        final_only = True
    if metric_key == "win_rate":
        final_only = True
    if metric_key == "consultation_effectiveness":
        final_only = True
        consulted_only = True

    old_stage_alias = aliased(models.PipelineStage)
    new_stage_alias = aliased(models.PipelineStage)
    changed_by_alias = aliased(models.User)
    new_consult_status_alias = aliased(models.ConsultationStatus)

    row_query = (
        select(
            models.LeadStatusHistory.id.label("history_id"),
            models.LeadStatusHistory.lead_id.label("lead_id"),
            models.Lead.full_name.label("lead_name"),
            models.LeadStatusHistory.changed_at.label("changed_at"),
            changed_by_alias.full_name.label("changed_by"),
            models.LeadStatusHistory.old_status.label("old_status"),
            models.LeadStatusHistory.new_status.label("new_status"),
            models.LeadStatusHistory.old_pipeline_stage_id.label("old_stage_id"),
            models.LeadStatusHistory.new_pipeline_stage_id.label("new_stage_id"),
            old_stage_alias.name.label("old_stage_name"),
            new_stage_alias.name.label("new_stage_name"),
            models.LeadStatusHistory.loss_reason_code.label("loss_reason_code"),
            new_consult_status_alias.outcome_type.label("outcome_type"),
        )
        .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
        .outerjoin(changed_by_alias, models.LeadStatusHistory.changed_by_user_id == changed_by_alias.id)
        .outerjoin(old_stage_alias, models.LeadStatusHistory.old_pipeline_stage_id == old_stage_alias.id)
        .outerjoin(new_stage_alias, models.LeadStatusHistory.new_pipeline_stage_id == new_stage_alias.id)
        .outerjoin(
            new_consult_status_alias,
            models.LeadStatusHistory.new_consultation_status_id == new_consult_status_alias.id,
        )
    )

    common_conditions = [models.Lead.deleted_at.is_(None)]
    if ctx.effective_officer_ids:
        common_conditions.append(models.Lead.assigned_officer_id.in_(ctx.effective_officer_ids))
    if stage_id:
        common_conditions.append(
            or_(
                models.LeadStatusHistory.old_pipeline_stage_id == stage_id,
                models.LeadStatusHistory.new_pipeline_stage_id == stage_id,
            )
        )

    if metric_key in {"win_rate", "consultation_effectiveness"}:
        latest_status_alias = aliased(models.ConsultationStatus)
        latest_conditions = list(common_conditions)
        latest_conditions.append(models.LeadStatusHistory.new_consultation_status_id.isnot(None))
        _apply_datetime_bounds(latest_conditions, models.LeadStatusHistory.changed_at, start_dt, end_exclusive)

        latest_ids_query = (
            select(models.LeadStatusHistory.id.label("history_id"), models.LeadStatusHistory.lead_id.label("lead_id"))
            .distinct(models.LeadStatusHistory.lead_id)
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .join(
                latest_status_alias,
                models.LeadStatusHistory.new_consultation_status_id == latest_status_alias.id,
            )
            .where(*latest_conditions)
            .order_by(
                models.LeadStatusHistory.lead_id,
                models.LeadStatusHistory.changed_at.desc(),
                models.LeadStatusHistory.id.desc(),
            )
        )
        if consulted_only:
            consulted_leads = _consulted_leads_subquery(ctx.effective_officer_ids)
            latest_ids_query = latest_ids_query.join(
                consulted_leads,
                models.LeadStatusHistory.lead_id == consulted_leads.c.lead_id,
            )

        history_ids_subq = latest_ids_query.subquery()
        base_query = row_query.where(
            models.LeadStatusHistory.id.in_(select(history_ids_subq.c.history_id))
        )
        if outcome:
            base_query = base_query.where(new_consult_status_alias.outcome_type == outcome)
        if final_only:
            base_query = base_query.where(new_consult_status_alias.is_final.is_(True))
    elif metric_key == "enrollments_monthly":
        current_stage_alias = aliased(models.PipelineStage)
        current_status_alias = aliased(models.ConsultationStatus)

        enrollment_conditions = [models.Lead.deleted_at.is_(None)]
        if ctx.effective_officer_ids:
            enrollment_conditions.append(models.Lead.assigned_officer_id.in_(ctx.effective_officer_ids))
        _apply_datetime_bounds(enrollment_conditions, models.Lead.updated_at, start_dt, end_exclusive)
        enrollment_conditions.extend([
            current_stage_alias.is_final_stage.is_(True),
            current_status_alias.counts_for_funnel.is_(True),
            current_status_alias.outcome_type == "positive",
        ])

        history_conditions = list(common_conditions)
        history_conditions.extend([
            models.LeadStatusHistory.new_consultation_status_id.isnot(None),
            new_consult_status_alias.is_final.is_(True),
            new_consult_status_alias.outcome_type == "positive",
        ])

        history_ids_subq = (
            select(models.LeadStatusHistory.id.label("history_id"), models.LeadStatusHistory.lead_id.label("lead_id"))
            .distinct(models.LeadStatusHistory.lead_id)
            .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
            .join(current_stage_alias, models.Lead.pipeline_stage_id == current_stage_alias.id)
            .join(current_status_alias, models.Lead.consultation_status_id == current_status_alias.id)
            .join(
                new_consult_status_alias,
                models.LeadStatusHistory.new_consultation_status_id == new_consult_status_alias.id,
            )
            .where(*enrollment_conditions, *history_conditions)
            .order_by(
                models.LeadStatusHistory.lead_id,
                models.LeadStatusHistory.changed_at.desc(),
                models.LeadStatusHistory.id.desc(),
            )
            .subquery()
        )

        base_query = row_query.where(
            models.LeadStatusHistory.id.in_(select(history_ids_subq.c.history_id))
        )
    else:
        generic_conditions = list(common_conditions)
        _apply_datetime_bounds(generic_conditions, models.LeadStatusHistory.changed_at, start_dt, end_exclusive)
        if outcome:
            generic_conditions.append(new_consult_status_alias.outcome_type == outcome)
        if final_only:
            generic_conditions.append(new_consult_status_alias.is_final.is_(True))

        base_query = row_query.where(*generic_conditions)
        if consulted_only:
            consulted_leads = _consulted_leads_subquery(ctx.effective_officer_ids)
            base_query = base_query.join(
                consulted_leads,
                models.LeadStatusHistory.lead_id == consulted_leads.c.lead_id,
            )

    count_query = select(func.count()).select_from(base_query.subquery())
    total_count = (await db.execute(count_query)).scalar() or 0

    sort_map = {
        "changed_at": models.LeadStatusHistory.changed_at,
        "lead_name": models.Lead.full_name,
        "old_stage_name": old_stage_alias.name,
        "new_stage_name": new_stage_alias.name,
        "outcome": new_consult_status_alias.outcome_type,
    }
    sort_column = sort_map.get(sort_by, models.LeadStatusHistory.changed_at)
    data_query = (
        base_query
        .order_by(_sort_direction(sort_column, order), models.LeadStatusHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    rows = []
    for row in (await db.execute(data_query)).mappings():
        rows.append({
            "history_id": row.history_id,
            "lead_id": row.lead_id,
            "lead_name": row.lead_name,
            "changed_at": _serialize_datetime(row.changed_at),
            "changed_by": row.changed_by,
            "old_status": row.old_status,
            "new_status": row.new_status,
            "old_stage_id": row.old_stage_id,
            "new_stage_id": row.new_stage_id,
            "old_stage_name": row.old_stage_name,
            "new_stage_name": row.new_stage_name,
            "loss_reason_code": row.loss_reason_code,
            "outcome": _row_outcome(row.outcome_type, row.new_status),
        })

    return {
        "metadata": _build_metadata(ctx, metric_key, start_date, end_date, page, page_size, total_count),
        "rows": rows,
    }


async def get_cohorts_drilldown(
    db: AsyncSession,
    ctx,  # DashboardScopeContext
    metric_key: str,
    start_date: str = None,
    end_date: str = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    order: str = "desc",
    cohort_result: str = None,
) -> Dict[str, Any]:
    _, _, start_dt, end_exclusive = _date_bounds(start_date, end_date)

    officer_alias = aliased(models.User)
    current_status_alias = aliased(models.ConsultationStatus)

    conditions = [models.Lead.deleted_at.is_(None)]
    if ctx.effective_officer_ids:
        conditions.append(models.Lead.assigned_officer_id.in_(ctx.effective_officer_ids))
    _apply_datetime_bounds(conditions, models.Lead.created_at, start_dt, end_exclusive)

    if cohort_result == "converted":
        conditions.extend([
            current_status_alias.is_final.is_(True),
            current_status_alias.outcome_type == "positive",
        ])
    elif cohort_result == "lost":
        conditions.extend([
            current_status_alias.is_final.is_(True),
            current_status_alias.outcome_type != "positive",
        ])
    elif cohort_result == "open":
        conditions.append(
            or_(
                current_status_alias.id.is_(None),
                current_status_alias.is_final.is_(False),
            )
        )

    base_query = (
        select(
            models.Lead.id.label("lead_id"),
            models.Lead.full_name.label("lead_name"),
            models.Lead.created_at.label("created_at"),
            models.Lead.status.label("current_status"),
            current_status_alias.is_final.label("is_final"),
            current_status_alias.outcome_type.label("outcome_type"),
            models.Lead.assigned_officer_id.label("officer_id"),
            officer_alias.full_name.label("officer_name"),
        )
        .select_from(models.Lead)
        .outerjoin(current_status_alias, models.Lead.consultation_status_id == current_status_alias.id)
        .outerjoin(officer_alias, models.Lead.assigned_officer_id == officer_alias.id)
        .where(*conditions)
    )

    count_query = select(func.count()).select_from(base_query.subquery())
    total_count = (await db.execute(count_query)).scalar() or 0

    sort_map = {
        "created_at": models.Lead.created_at,
        "lead_name": models.Lead.full_name,
        "current_status": models.Lead.status,
    }
    sort_column = sort_map.get(sort_by, models.Lead.created_at)
    data_query = (
        base_query
        .order_by(_sort_direction(sort_column, order), models.Lead.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    rows = []
    for row in (await db.execute(data_query)).mappings():
        rows.append({
            "lead_id": row.lead_id,
            "lead_name": row.lead_name,
            "created_at": _serialize_datetime(row.created_at),
            "current_status": row.current_status,
            "cohort_result": _cohort_result(row.is_final, row.outcome_type),
            "officer_id": row.officer_id,
            "officer_name": row.officer_name,
        })

    return {
        "metadata": _build_metadata(ctx, metric_key, start_date, end_date, page, page_size, total_count),
        "rows": rows,
    }
