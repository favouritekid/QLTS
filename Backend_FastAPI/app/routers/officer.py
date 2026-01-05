from typing import Annotated
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..database import get_db
from ..core.deps import CasbinAuth, OfficerDashboardScope, get_officer_dashboard_scope  # ✅ Phase 2.2
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
    summary="Get weekly leaderboard for gamification"
)
async def get_leaderboard(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, CasbinAuth]
):
    """Weekly leaderboard showing top officers by consultations."""
    leaderboard = await officer_service.get_weekly_leaderboard(
        db=db, officer_id=current_user.id
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
            
    stats = await officer_service.get_team_stats(
        db=db, 
        officer_id=current_user.id, 
        days=days,
        start_date=parsed_start,
        end_date=parsed_end
    )
    return stats


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
    month: int = None,
    year: int = None
):
    """Get leads with scheduled follow-ups for the given month."""
    from datetime import datetime
    
    if month is None or year is None:
        now = datetime.now()
        month = month or now.month
        year = year or now.year
    
    result = await officer_service.get_upcoming_activities(
        db=db,
        officer_id=current_user.id,
        month=month,
        year=year
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
    limit: int = 5,
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
    from app.services.recommendation_engine import get_officer_recommendations
    
    recommendations = await get_officer_recommendations(
        db=db,
        officer_id=current_user.id,
        limit=limit,
    )
    return {"recommendations": recommendations, "count": len(recommendations)}
