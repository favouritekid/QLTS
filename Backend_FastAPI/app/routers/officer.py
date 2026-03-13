from typing import Annotated
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..database import get_db
from ..core.deps import CasbinAuth, OfficerDashboardScope, get_officer_dashboard_scope, resolve_drill_down_officer_id  # ✅ Phase 2.2
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
    scope_params: Annotated[OfficerDashboardScope, Depends(get_officer_dashboard_scope)],
    start_date: str = None,
    end_date: str = None,
):
    """
    Enhanced officer dashboard with role-based scoping.
    
    **Scope options (enforced by Security Gateway):**
    - `personal`: Own data only (default for officers)
    - `team`: All officers in same unit (managers)
    - `organization`: All officers (admins)
    
    **Security:**
    All role-based access control is handled by deps.get_officer_dashboard_scope.
    Router receives pre-validated parameters.
    """
    if scope_params.scope == "personal":
        target_id = scope_params.officer_id if scope_params.officer_id else scope_params.requesting_user.id
        stats = await officer_service.get_enhanced_dashboard_stats(
            db=db, 
            officer_id=target_id,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        stats = await officer_service.get_aggregated_dashboard_stats(
            db=db,
            scope=scope_params.scope,
            requesting_user=scope_params.requesting_user,
            officer_id=scope_params.officer_id,
            unit_id=scope_params.unit_id,
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
    current_user: Annotated[models.User, CasbinAuth],
    validated_officer_id: Annotated[int, Depends(resolve_drill_down_officer_id)],
    start_date: str = None,
    end_date: str = None,
    scope: str = None,
    unit_id: int = None,
):
    """
    Leaderboard showing top officers by consultations.

    Args:
        start_date: Start date (YYYY-MM-DD). Defaults to this week's Monday.
        end_date: End date (YYYY-MM-DD). Defaults to today.
        scope: "personal" | "team" | "organization". Affects unit filtering.
        unit_id: Filter by specific unit (for organization scope).
        officer_id: Drill-down target (validated by resolve_drill_down_officer_id).
    """
    from datetime import date as date_type

    # Parse dates
    parsed_start = None
    parsed_end = None
    if start_date and end_date:
        try:
            parsed_start = date_type.fromisoformat(start_date)
            parsed_end = date_type.fromisoformat(end_date)
        except ValueError:
            pass  # Use defaults

    leaderboard = await officer_service.get_weekly_leaderboard(
        db=db,
        officer_id=validated_officer_id,
        start_date=parsed_start,
        end_date=parsed_end,
        scope=scope,
        unit_id=unit_id,
        requesting_user=current_user,
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
    current_user: Annotated[models.User, CasbinAuth],
    validated_officer_id: Annotated[int, Depends(resolve_drill_down_officer_id)],
    days: int = 30,
    start_date: str = None,
    end_date: str = None,
):
    """Get team average statistics for performance comparison."""
    from datetime import date

    parsed_start = None
    parsed_end = None

    if start_date and end_date:
        try:
            parsed_start = date.fromisoformat(start_date)
            parsed_end = date.fromisoformat(end_date)
        except ValueError:
            pass  # Fallback to days param

    # Resolve unit_id from validated officer (not raw officer_id)
    if validated_officer_id != current_user.id:
        target_user = await db.get(models.User, validated_officer_id)
        resolved_unit_id = target_user.unit_id if target_user else current_user.unit_id
    else:
        resolved_unit_id = current_user.unit_id

    stats = await officer_service.get_team_stats(
        db=db,
        officer_id=validated_officer_id,
        days=days,
        start_date=parsed_start,
        end_date=parsed_end,
        unit_id=resolved_unit_id,
    )
    return stats


# =============================================================================
# GAP 2: Monthly KPI Plan Breakdown
# =============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/my-kpi-plan",
    response_model=schemas.OfficerKpiPlanResponse,
    summary="Get officer's monthly KPI plan breakdown"
)
async def get_my_kpi_plan(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, CasbinAuth],
    validated_officer_id: Annotated[int, Depends(resolve_drill_down_officer_id)],
    fiscal_year: int = None,
):
    """
    Monthly KPI plan breakdown for self-tracking.
    Officer sees own plan (or unit plan fallback).
    Manager/admin can drill-down via officer_id param.
    Returns 404 if no plan exists.
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
    current_user: Annotated[models.User, CasbinAuth],
    validated_officer_id: Annotated[int, Depends(resolve_drill_down_officer_id)],
    month: int = None,
    year: int = None,
    scope: str = "personal",
    unit_id: int = None,
):
    """Get leads with scheduled follow-ups for the given month. Supports scope and officer drill-down."""
    from datetime import datetime

    if month is None or year is None:
        now = datetime.now()
        month = month or now.month
        year = year or now.year

    result = await officer_service.get_upcoming_activities(
        db=db,
        officer_id=validated_officer_id,
        month=month,
        year=year,
        scope=scope,
        unit_id=unit_id,
        requesting_user=current_user,
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
    current_user: Annotated[models.User, CasbinAuth],
    validated_officer_id: Annotated[int, Depends(resolve_drill_down_officer_id)],
    limit: int = 5,
    start_date: str = None,
    end_date: str = None,
):
    """
    Phase 7: Auto Recommendations

    Returns actionable recommendations based on:
    - KPI gaps (consultations vs target)
    - Conversion rate analysis
    - Response time optimization
    - Hot leads needing attention
    - Stale leads cleanup

    Recommendations are prioritized: CRITICAL > HIGH > MEDIUM > LOW
    """
    from datetime import date
    from app.services.recommendation_engine import get_officer_recommendations

    # Validate date format at router boundary
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
        officer_id=validated_officer_id,
        limit=limit,
        start_date=validated_start,
        end_date=validated_end,
    )
    return {"recommendations": recommendations, "count": len(recommendations)}
