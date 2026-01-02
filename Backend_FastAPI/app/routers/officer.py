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
    # Phase 2: Scope and filter parameters
    scope: str = "personal",  # "personal", "team", "organization"
    officer_id: int = None,   # Filter to specific officer (manager/admin only)
    unit_id: int = None,      # Filter to specific unit (admin only)
):
    """
    Enhanced officer dashboard with role-based scoping.
    
    **Scope options:**
    - `personal`: Own data only (default for officers)
    - `team`: All officers in same unit (managers)
    - `organization`: All officers (admins)
    
    **Filters:**
    - `officer_id`: View specific officer's dashboard (requires manager/admin role)
    - `unit_id`: Filter by unit (requires admin role)
    
    **Security:**
    - Officers can only use scope="personal" and cannot filter
    - Managers can use scope="team" and filter officers in their unit
    - Admins can use any scope and any filters
    """
    # ==========================================================================
    # SECURITY: Role-based permission validation
    # ==========================================================================
    user_role = current_user.role
    
    # Validate scope parameter
    if scope not in ("personal", "team", "organization"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope: {scope}. Must be 'personal', 'team', or 'organization'"
        )
    
    # Officers: Can only view personal data
    if user_role == "officer":
        if scope != "personal":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Officers can only view personal dashboard"
            )
        if officer_id is not None and officer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Officers cannot view other officers' data"
            )
        if unit_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Officers cannot filter by unit"
            )
        # Force personal scope
        scope = "personal"
        officer_id = current_user.id
    
    # Managers: Can view team or drill down to specific officer in their unit
    elif user_role == "manager":
        if scope == "organization":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Managers cannot view organization-wide data"
            )
        if unit_id is not None and unit_id != current_user.unit_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Managers cannot view data from other units"
            )
        # Force manager's unit
        unit_id = current_user.unit_id
        
        # If filtering by officer, validate officer belongs to manager's unit
        if officer_id is not None:
            target_officer = await db.get(models.User, officer_id)
            if not target_officer or target_officer.unit_id != current_user.unit_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Officer not found in your unit"
                )
    
    # Admins: Full access (no restrictions)
    # elif user_role == "admin": pass
    
    # ==========================================================================
    # Fetch dashboard data based on scope
    # ==========================================================================
    try:
        if scope == "personal":
            # Personal dashboard: single officer
            target_id = officer_id if officer_id else current_user.id
            stats = await officer_service.get_enhanced_dashboard_stats(
                db=db, 
                officer_id=target_id,
                start_date=start_date,
                end_date=end_date,
            )
        else:
            # Team or Organization scope: aggregated dashboard
            stats = await officer_service.get_aggregated_dashboard_stats(
                db=db,
                scope=scope,
                requesting_user=current_user,
                officer_id=officer_id,  # Optional: drill down to specific officer
                unit_id=unit_id,        # Filter by unit (for organization scope)
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
    days: int = 30,
    start_date: str = None, # ISO format YYYY-MM-DD
    end_date: str = None,   # ISO format YYYY-MM-DD
):
    """
    Get team average statistics for performance comparison.
    Shows team averages for consultations and conversions.
    """
    from datetime import date
    
    parsed_start = None
    parsed_end = None
    
    if start_date and end_date:
        try:
            parsed_start = date.fromisoformat(start_date)
            parsed_end = date.fromisoformat(end_date)
        except ValueError:
            pass # Fallback to days param
            
    try:
        stats = await officer_service.get_team_stats(
            db=db, 
            officer_id=current_user.id, 
            days=days,
            start_date=parsed_start,
            end_date=parsed_end
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
    current_user: Annotated[models.User, PermissionDep],
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
    
    try:
        recommendations = await get_officer_recommendations(
            db=db,
            officer_id=current_user.id,
            limit=limit,
        )
        return {"recommendations": recommendations, "count": len(recommendations)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
