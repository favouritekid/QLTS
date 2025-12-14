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
# PHASE 1: Enhanced Dashboard with KPIs
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
    current_user: Annotated[models.User, PermissionDep]
):
    """
    Enhanced officer dashboard with:
    - KPI cards (consultations, active leads, conversion rate, response time)
    - Trend comparisons (vs yesterday, vs last week, vs last month)
    - AI-powered priority actions
    - Performance trends and pipeline funnel
    """
    try:
        stats = await officer_service.get_enhanced_dashboard_stats(
            db=db, officer_id=current_user.id
        )
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))