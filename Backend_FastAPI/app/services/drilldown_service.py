"""
V12 Phase B: Drill-down service for exact dashboard click-through.

Provides consultations, transitions, and cohorts drill-down queries
that match exact dashboard metrics.
"""
from datetime import date as date_type, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, case, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.repositories.officer_repository import OfficerRepository


# Final negative statuses for outcome classification
NEGATIVE_STATUSES = {"rejected", "unqualified", "lost"}
POSITIVE_STATUSES = {"converted", "enrolled"}


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
    # Target-specific filters
    stage_id: str = None,
    loss_reason_code: str = None,
    consultation_kind: str = None,
    response_breach_only: bool = False,
) -> Dict[str, Any]:
    """
    Drill-down into consultation records.

    Row semantics: consultation + lead info + officer + date + loss reason.
    """
    from datetime import date as d_type

    # Parse dates
    filter_start = None
    filter_end = None
    if start_date and end_date:
        try:
            filter_start = d_type.fromisoformat(start_date)
            filter_end = d_type.fromisoformat(end_date)
        except ValueError:
            pass

    # Base query: consultations for officers in scope
    conditions = []

    if ctx.effective_officer_ids:
        conditions.append(models.Consultation.officer_id.in_(ctx.effective_officer_ids))

    if filter_start:
        conditions.append(models.Consultation.consultation_date >= datetime(
            filter_start.year, filter_start.month, filter_start.day, tzinfo=timezone.utc
        ))
    if filter_end:
        conditions.append(models.Consultation.consultation_date <= datetime(
            filter_end.year, filter_end.month, filter_end.day, 23, 59, 59, tzinfo=timezone.utc
        ))

    # Target-specific filters
    if stage_id:
        # Join with lead to filter by stage
        conditions.append(models.Lead.pipeline_stage_id == stage_id)

    if loss_reason_code:
        conditions.append(models.Consultation.loss_reason_code == loss_reason_code)

    # Build query with lead join
    base_query = (
        select(models.Consultation)
        .join(models.Lead, models.Consultation.lead_id == models.Lead.id)
        .where(*conditions)
    )

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0

    # Sort and paginate
    sort_col = getattr(models.Consultation, "consultation_date", models.Consultation.id)
    if sort_by == "lead_name":
        sort_col = models.Lead.full_name

    order_clause = sort_col.desc() if order == "desc" else sort_col.asc()

    data_query = (
        base_query
        .options(selectinload(models.Consultation.lead))
        .order_by(order_clause)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(data_query)
    consultations = result.scalars().all()

    rows = []
    for c in consultations:
        rows.append({
            "consultation_id": c.id,
            "lead_id": c.lead_id,
            "lead_name": c.lead.full_name if c.lead else None,
            "officer_id": c.officer_id,
            "officer_name": None,  # Could be loaded if needed
            "consultation_date": c.consultation_date.isoformat() if c.consultation_date else None,
            "loss_reason_code": c.loss_reason_code,
            "loss_reason_note": c.loss_reason_note,
            "status": c.lead.status if c.lead else None,
        })

    return {
        "metadata": {
            "metric_key": metric_key,
            "exactness": "exact",
            "effective_scope": {
                "scope_kind": ctx.scope_kind,
                "label": ctx.label,
                "forced_by_role": ctx.forced_by_role,
                "includes_descendants": ctx.includes_descendants,
            },
            "effective_date_context": {
                "start_date": start_date,
                "end_date": end_date,
            } if start_date else None,
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
        },
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
    # Target-specific filters
    stage_id: str = None,
    outcome: str = None,  # "positive" | "negative"
    final_only: bool = False,
    consulted_only: bool = False,
) -> Dict[str, Any]:
    """
    Drill-down into status transition records (LeadStatusHistory).

    Row semantics: transition + changed_at + old/new stage/status + outcome.
    """
    from datetime import date as d_type

    filter_start = None
    filter_end = None
    if start_date and end_date:
        try:
            filter_start = d_type.fromisoformat(start_date)
            filter_end = d_type.fromisoformat(end_date)
        except ValueError:
            pass

    conditions = [models.Lead.deleted_at.is_(None)]

    # Scope: filter by lead's assigned officer
    if ctx.effective_officer_ids:
        conditions.append(models.Lead.assigned_officer_id.in_(ctx.effective_officer_ids))

    # Date filter on transition time
    if filter_start:
        conditions.append(models.LeadStatusHistory.changed_at >= datetime(
            filter_start.year, filter_start.month, filter_start.day, tzinfo=timezone.utc
        ))
    if filter_end:
        conditions.append(models.LeadStatusHistory.changed_at <= datetime(
            filter_end.year, filter_end.month, filter_end.day, 23, 59, 59, tzinfo=timezone.utc
        ))

    # Stage filter (transitions involving this stage)
    if stage_id:
        conditions.append(or_(
            models.LeadStatusHistory.old_pipeline_stage_id == stage_id,
            models.LeadStatusHistory.new_pipeline_stage_id == stage_id,
        ))

    # Outcome filter
    if outcome == "positive":
        conditions.append(models.LeadStatusHistory.new_status.in_(list(POSITIVE_STATUSES)))
    elif outcome == "negative":
        conditions.append(models.LeadStatusHistory.new_status.in_(list(NEGATIVE_STATUSES)))

    # Final only: transitions to final statuses
    if final_only:
        all_final = list(POSITIVE_STATUSES | NEGATIVE_STATUSES)
        conditions.append(models.LeadStatusHistory.new_status.in_(all_final))

    # Build query
    base_query = (
        select(models.LeadStatusHistory)
        .join(models.Lead, models.LeadStatusHistory.lead_id == models.Lead.id)
        .where(*conditions)
    )

    # Count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0

    # Sort
    sort_col = models.LeadStatusHistory.changed_at
    order_clause = sort_col.desc() if order == "desc" else sort_col.asc()

    data_query = (
        base_query
        .options(
            selectinload(models.LeadStatusHistory.lead),
            selectinload(models.LeadStatusHistory.old_pipeline_stage),
            selectinload(models.LeadStatusHistory.new_pipeline_stage),
        )
        .order_by(order_clause)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(data_query)
    transitions = result.scalars().all()

    rows = []
    for t in transitions:
        # Classify outcome
        if t.new_status in POSITIVE_STATUSES:
            row_outcome = "positive"
        elif t.new_status in NEGATIVE_STATUSES:
            row_outcome = "negative"
        else:
            row_outcome = "neutral"

        rows.append({
            "history_id": t.id,
            "lead_id": t.lead_id,
            "lead_name": t.lead.full_name if t.lead else None,
            "changed_at": t.changed_at.isoformat() if t.changed_at else None,
            "changed_by": None,  # Could load user name
            "old_status": t.old_status,
            "new_status": t.new_status,
            "old_stage_id": t.old_pipeline_stage_id,
            "new_stage_id": t.new_pipeline_stage_id,
            "old_stage_name": t.old_pipeline_stage.name if t.old_pipeline_stage else None,
            "new_stage_name": t.new_pipeline_stage.name if t.new_pipeline_stage else None,
            "loss_reason_code": t.loss_reason_code,
            "outcome": row_outcome,
        })

    return {
        "metadata": {
            "metric_key": metric_key,
            "exactness": "exact",
            "effective_scope": {
                "scope_kind": ctx.scope_kind,
                "label": ctx.label,
                "forced_by_role": ctx.forced_by_role,
                "includes_descendants": ctx.includes_descendants,
            },
            "effective_date_context": {
                "start_date": start_date,
                "end_date": end_date,
            } if start_date else None,
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
        },
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
    # Target-specific filters
    cohort_result: str = None,  # "converted" | "lost" | "open"
) -> Dict[str, Any]:
    """
    Drill-down into lead cohorts (leads created in date range).

    Row semantics: lead + created_at + current status + cohort result.
    """
    from datetime import date as d_type

    filter_start = None
    filter_end = None
    if start_date and end_date:
        try:
            filter_start = d_type.fromisoformat(start_date)
            filter_end = d_type.fromisoformat(end_date)
        except ValueError:
            pass

    conditions = [models.Lead.deleted_at.is_(None)]

    # Scope
    if ctx.effective_officer_ids:
        conditions.append(models.Lead.assigned_officer_id.in_(ctx.effective_officer_ids))

    # Cohort = leads created in date range
    if filter_start:
        conditions.append(models.Lead.created_at >= datetime(
            filter_start.year, filter_start.month, filter_start.day, tzinfo=timezone.utc
        ))
    if filter_end:
        conditions.append(models.Lead.created_at <= datetime(
            filter_end.year, filter_end.month, filter_end.day, 23, 59, 59, tzinfo=timezone.utc
        ))

    # Cohort result filter
    if cohort_result == "converted":
        conditions.append(models.Lead.status.in_(list(POSITIVE_STATUSES)))
    elif cohort_result == "lost":
        conditions.append(models.Lead.status.in_(list(NEGATIVE_STATUSES)))
    elif cohort_result == "open":
        all_final = list(POSITIVE_STATUSES | NEGATIVE_STATUSES)
        conditions.append(~models.Lead.status.in_(all_final))

    base_query = select(models.Lead).where(*conditions)

    # Count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total_count = total_result.scalar() or 0

    # Sort
    sort_col = models.Lead.created_at
    order_clause = sort_col.desc() if order == "desc" else sort_col.asc()

    data_query = (
        base_query
        .order_by(order_clause)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(data_query)
    leads = result.scalars().all()

    rows = []
    for lead in leads:
        if lead.status in POSITIVE_STATUSES:
            result_label = "converted"
        elif lead.status in NEGATIVE_STATUSES:
            result_label = "lost"
        else:
            result_label = "open"

        rows.append({
            "lead_id": lead.id,
            "lead_name": lead.full_name,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
            "current_status": lead.status,
            "cohort_result": result_label,
            "officer_id": lead.assigned_officer_id,
            "officer_name": None,  # Could load
        })

    return {
        "metadata": {
            "metric_key": metric_key,
            "exactness": "exact",
            "effective_scope": {
                "scope_kind": ctx.scope_kind,
                "label": ctx.label,
                "forced_by_role": ctx.forced_by_role,
                "includes_descendants": ctx.includes_descendants,
            },
            "effective_date_context": {
                "start_date": start_date,
                "end_date": end_date,
            } if start_date else None,
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
        },
        "rows": rows,
    }
