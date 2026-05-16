from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..database import get_db
from ..core.deps import (
    CasbinAuth,
    DashboardScopeContext,
    get_officer_dashboard_scope,
    resolve_kpi_plan_officer_id,
)
from ..services import officer_service
from app.core.rate_limits import limiter, RateLimits

router = APIRouter(prefix="/officer", tags=["Officer Dashboard"])


# =============================================================================
# PHASE 7: Remove generic except Exception per MASTER_ARCHITECTURE
# Global exception handlers in middleware/exception_handlers.py handle all errors
# =============================================================================


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get(
    "/stats",
    response_model=schemas.OfficerDashboardStats,
    summary="Get officer dashboard statistics"
)
async def get_officer_stats(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, CasbinAuth]
):
    """Get basic stats for the current officer's dashboard."""
    stats = await officer_service.get_officer_dashboard_stats(
        db=db, officer_id=current_user.id
    )
    return stats


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/availability",
    response_model=schemas.AvailabilityResponse,
    summary="Update availability status"
)
async def update_availability(
    request: Request,
    status_data: schemas.AvailabilityUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, CasbinAuth]
):
    """Update officer's availability status."""
    updated_user, callback = await officer_service.update_officer_availability(
        db=db,
        officer_id=current_user.id,
        availability_status=status_data.availability_status
    )
    await db.commit()
    await callback()

    return {
        "status": "success",
        "availability_status": updated_user.availability_status,
        "user_id": updated_user.id
    }


# =============================================================================
# PHASE 1: Enhanced Dashboard with KPIs (+ Date Range Filter)
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/dashboard",
    response_model=schemas.OfficerDashboardEnhanced,
    summary="Get enhanced officer dashboard with KPIs and priority actions"
)
async def get_enhanced_dashboard(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    start_date: str = None,
    end_date: str = None,
):
    """
    Enhanced officer dashboard with role-based scoping.

    Scope options (enforced by DashboardScopeContext):
    - `personal`: Single officer view (officers, admin+officer_id)
    - `unit`: Unit + descendant units (managers)
    - `organization`: All officers or unit subtree (admins)

    Router is "dumb" — all scope resolution happens in the dependency.
    """
    # Single officer view: personal scope OR drill-down to specific officer
    if len(ctx.effective_officer_ids) == 1:
        stats = await officer_service.get_enhanced_dashboard_stats(
            db=db,
            officer_id=ctx.effective_officer_ids[0],
            start_date=start_date,
            end_date=end_date,
        )
    else:
        stats = await officer_service.get_aggregated_dashboard_stats(
            db=db,
            ctx=ctx,
            start_date=start_date,
            end_date=end_date,
        )
    return stats


# =============================================================================
# PHASE 4: Leaderboard
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/leaderboard",
    response_model=schemas.WeeklyLeaderboard,
    summary="Get leaderboard for gamification"
)
async def get_leaderboard(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    start_date: str = None,
    end_date: str = None,
):
    """Leaderboard showing top officers by consultations. Scope resolved by dependency."""
    from datetime import date as date_type

    parsed_start = None
    parsed_end = None
    if start_date and end_date:
        try:
            parsed_start = date_type.fromisoformat(start_date)
            parsed_end = date_type.fromisoformat(end_date)
        except ValueError:
            pass

    leaderboard = await officer_service.get_weekly_leaderboard(
        db=db,
        ctx=ctx,
        start_date=parsed_start,
        end_date=parsed_end,
    )
    return leaderboard


# =============================================================================
# PHASE 6: Team Stats for Performance Comparison
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/team-stats",
    response_model=schemas.TeamStats,
    summary="Get team average stats for performance comparison"
)
async def get_team_stats(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    days: int = 30,
    start_date: str = None,
    end_date: str = None,
):
    """Get team average statistics for performance comparison. Scope resolved by dependency."""
    from datetime import date

    parsed_start = None
    parsed_end = None
    if start_date and end_date:
        try:
            parsed_start = date.fromisoformat(start_date)
            parsed_end = date.fromisoformat(end_date)
        except ValueError:
            pass

    stats = await officer_service.get_team_stats(
        db=db,
        ctx=ctx,
        days=days,
        start_date=parsed_start,
        end_date=parsed_end,
    )
    return stats


# =============================================================================
# GAP 2: Monthly KPI Plan Breakdown
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/my-kpi-plan",
    response_model=schemas.OfficerKpiPlanResponse | None,
    summary="Get officer's monthly KPI plan breakdown"
)
async def get_my_kpi_plan(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, CasbinAuth],
    validated_officer_id: Annotated[int, Depends(resolve_kpi_plan_officer_id)],
    fiscal_year: int = None,
):
    """
    Monthly KPI plan breakdown for self-tracking.
    Officer sees own plan (or unit plan fallback).
    Manager/admin can drill-down via officer_id param.

    Returns:
    - 200 + body: plan exists
    - 200 + null: valid officer but no plan for this fiscal year
    - 400: manager/admin called without officer_id
    - 404: officer_id invalid / out of scope (IDOR)
    """
    from datetime import datetime as dt

    if fiscal_year is None:
        fiscal_year = dt.now().year

    result = await officer_service.get_officer_kpi_plan(
        db=db,
        officer_id=validated_officer_id,
        fiscal_year=fiscal_year,
    )
    return result


# =============================================================================
# Today's Schedule Widget - Upcoming Activities
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/upcoming-activities",
    summary="Get upcoming activities for calendar widget"
)
async def get_upcoming_activities(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    month: int = None,
    year: int = None,
):
    """Get leads with scheduled follow-ups for the given month. Scope resolved by dependency."""
    from datetime import datetime

    if month is None or year is None:
        now = datetime.now()
        month = month or now.month
        year = year or now.year

    result = await officer_service.get_upcoming_activities(
        db=db,
        ctx=ctx,
        month=month,
        year=year,
    )
    return result


# =============================================================================
# PHASE 7: Auto Recommendations
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/recommendations",
    summary="Get AI-powered recommendations based on KPI performance"
)
async def get_recommendations(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    limit: int = 5,
    start_date: str = None,
    end_date: str = None,
):
    """
    AI-powered recommendations. Single-officer only in this phase.
    Aggregated unit/organization scope without single officer target → 400.
    """
    from datetime import date
    from fastapi import HTTPException
    from app.services.recommendation_engine import get_officer_recommendations

    # Recommendations require exactly 1 officer
    if len(ctx.effective_officer_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="Recommendations chỉ hỗ trợ single-officer scope trong phase này. "
                   "Vui lòng chọn một officer cụ thể."
        )

    validated_start = None
    validated_end = None
    if start_date:
        try:
            date.fromisoformat(start_date)
            validated_start = start_date
        except ValueError:
            pass
    if end_date:
        try:
            date.fromisoformat(end_date)
            validated_end = end_date
        except ValueError:
            pass

    recommendations = await get_officer_recommendations(
        db=db,
        officer_id=ctx.effective_officer_ids[0],
        limit=limit,
        start_date=validated_start,
        end_date=validated_end,
    )
    return {"recommendations": recommendations, "count": len(recommendations)}


# =============================================================================
# V12 PHASE B: Drill-down Endpoints
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/drilldowns/consultations",
    summary="Drill-down into consultation records"
)
async def drilldown_consultations(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    metric_key: str = Query(..., description="Metric being drilled into"),
    start_date: str = Query(None, alias="from"),
    end_date: str = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: Literal["consultation_date", "lead_name", "loss_reason_code", "status"] = Query("consultation_date"),  # W8-A.3.1
    order: Literal["asc", "desc"] = Query("desc"),
    stage_id: str = Query(None),
    loss_reason_code: str = Query(None),
    consultation_kind: str = Query(None),
    response_breach_only: bool = Query(False),
):
    """Consultations drill-down: consultation records with lead info, officer, loss reason."""
    from app.services.drilldown_service import get_consultations_drilldown
    return await get_consultations_drilldown(
        db=db, ctx=ctx, metric_key=metric_key,
        start_date=start_date, end_date=end_date,
        page=page, page_size=page_size, sort_by=sort_by, order=order,
        stage_id=stage_id, loss_reason_code=loss_reason_code,
        consultation_kind=consultation_kind, response_breach_only=response_breach_only,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/drilldowns/transitions",
    summary="Drill-down into status transition records"
)
async def drilldown_transitions(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    metric_key: str = Query(..., description="Metric being drilled into"),
    start_date: str = Query(None, alias="from"),
    end_date: str = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: Literal["changed_at", "lead_name", "old_stage_name", "new_stage_name", "outcome"] = Query("changed_at"),  # W8-A.3.1
    order: Literal["asc", "desc"] = Query("desc"),
    stage_id: str = Query(None),
    outcome: str = Query(None, description="positive|negative"),
    final_only: bool = Query(False),
    consulted_only: bool = Query(False),
):
    """Transitions drill-down: status changes with stage, outcome, loss reason."""
    from app.services.drilldown_service import get_transitions_drilldown
    return await get_transitions_drilldown(
        db=db, ctx=ctx, metric_key=metric_key,
        start_date=start_date, end_date=end_date,
        page=page, page_size=page_size, sort_by=sort_by, order=order,
        stage_id=stage_id, outcome=outcome,
        final_only=final_only, consulted_only=consulted_only,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/drilldowns/cohorts",
    summary="Drill-down into lead cohort (created in date range)"
)
async def drilldown_cohorts(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[DashboardScopeContext, Depends(get_officer_dashboard_scope)],
    metric_key: str = Query(..., description="Metric being drilled into"),
    start_date: str = Query(None, alias="from"),
    end_date: str = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: Literal["created_at", "lead_name", "current_status"] = Query("created_at"),  # W8-A.3.1
    order: Literal["asc", "desc"] = Query("desc"),
    cohort_result: str = Query(None, description="converted|lost|open"),
):
    """Cohorts drill-down: leads created in period with conversion result."""
    from app.services.drilldown_service import get_cohorts_drilldown
    return await get_cohorts_drilldown(
        db=db, ctx=ctx, metric_key=metric_key,
        start_date=start_date, end_date=end_date,
        page=page, page_size=page_size, sort_by=sort_by, order=order,
        cohort_result=cohort_result,
    )
