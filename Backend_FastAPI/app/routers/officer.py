from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..database import get_db
from ..core import deps # ✅ Import module deps chuẩn
from ..services import officer_service
from app.core.rate_limits import limiter, RateLimits

router = APIRouter(prefix="/officer", tags=["Officer Dashboard"])

# ✅ Chuẩn hóa Permission Dependency (Giống admin.py)
PermissionDep = Depends(deps.check_permission)

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get(
    "/stats",
    response_model=schemas.OfficerDashboardStats, # ✅ Validate Output
    summary="Get officer dashboard statistics"
)
async def get_officer_stats(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    # ✅ Auto-check quyền truy cập vào URL /api/officer/stats
    current_user: Annotated[models.User, PermissionDep]
):
    try:
        stats = await officer_service.get_officer_dashboard_stats(
            db=db, officer_id=current_user.id
        )
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/availability",
    response_model=schemas.AvailabilityResponse, # ✅ Validate Output
    summary="Update availability status"
)
async def update_availability(
    request: Request,
    status_data: schemas.AvailabilityUpdate, # ✅ Validate Input bằng Pydantic
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep]
):
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    current_user: Annotated[models.User, PermissionDep],
    start_date: str = None,  # ISO format YYYY-MM-DD
    end_date: str = None,    # ISO format YYYY-MM-DD
):
    """
    Enhanced officer dashboard with:
    - KPI cards (consultations, active leads, conversion rate, response time)
    - Trend comparisons (vs yesterday, vs last week, vs last month)
    - AI-powered priority actions
    - Performance trends and pipeline funnel
    
    Optional date range filter:
    - start_date: Start date in YYYY-MM-DD format
    - end_date: End date in YYYY-MM-DD format
    """
    try:
        stats = await officer_service.get_enhanced_dashboard_stats(
            db=db, 
            officer_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
        )
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



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
    current_user: Annotated[models.User, PermissionDep]
):
    """
    Weekly leaderboard showing top officers by consultations.
    Includes current user's rank even if not in top 5.
    """
    try:
        leaderboard = await officer_service.get_weekly_leaderboard(
            db=db, officer_id=current_user.id
        )
        return leaderboard
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    current_user: Annotated[models.User, PermissionDep],
    days: int = 30
):
    """
    Get team average statistics for performance comparison.
    Shows team averages for consultations and conversions.
    """
    try:
        stats = await officer_service.get_team_stats(
            db=db, officer_id=current_user.id, days=days
        )
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    current_user: Annotated[models.User, PermissionDep],
    month: int = None,
    year: int = None
):
    """
    Get leads with scheduled follow-ups (next_activity_at) for the given month.
    Returns activities list and dates with activities for calendar highlighting.
    """
    from datetime import datetime
    
    # Default to current month if not specified
    if month is None or year is None:
        now = datetime.now()
        month = month or now.month
        year = year or now.year
    
    try:
        result = await officer_service.get_upcoming_activities(
            db=db,
            officer_id=current_user.id,
            month=month,
            year=year
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))