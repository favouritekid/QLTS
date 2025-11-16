from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..database import get_db
from ..core import deps # ✅ Import module deps chuẩn
from ..services import officer_service

router = APIRouter(prefix="/officer", tags=["Officer Dashboard"])

# ✅ Chuẩn hóa Permission Dependency (Giống admin.py)
PermissionDep = Depends(deps.check_permission)

@router.get(
    "/stats",
    response_model=schemas.OfficerDashboardStats, # ✅ Validate Output
    summary="Get officer dashboard statistics"
)
async def get_officer_stats(
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

@router.post(
    "/availability",
    response_model=schemas.AvailabilityResponse, # ✅ Validate Output
    summary="Update availability status"
)
async def update_availability(
    status_data: schemas.AvailabilityUpdate, # ✅ Validate Input bằng Pydantic
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep]
):
    try:
        updated_user = await officer_service.update_officer_availability(
            db=db,
            officer_id=current_user.id,
            new_status=status_data.availability_status
        )
        
        return {
            "status": "success",
            "availability_status": updated_user.availability_status,
            "user_id": updated_user.id
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))