# app/routers/administrative.py
"""
API endpoints for administrative nodes (provinces, districts, wards).
Supports adaptive 2-level/3-level address selection.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core import deps
from app.repositories.administrative_repository import AdministrativeRepository
from app.schemas.administrative import (
    ProvinceResponse, 
    DistrictResponse, 
    WardResponse,
)

router = APIRouter(prefix="/administrative", tags=["Administrative"])


@router.get("/provinces", response_model=List[ProvinceResponse])
async def get_provinces(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Get all provinces/cities.
    Returns 63 provinces with TCTK codes.
    """
    repo = AdministrativeRepository(db)
    provinces = await repo.get_provinces()
    return [ProvinceResponse(code=p.code, name=p.name) for p in provinces]


@router.get("/districts", response_model=List[DistrictResponse])
async def get_districts(
    province_code: str = Query(..., description="Province code (e.g., '54' for Phú Yên)"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Get districts/counties under a province.
    
    Only returns districts for OLD (3-level) structure.
    If province has no districts (2-level only), returns empty list.
    
    Frontend hint: If empty, skip district selection and go directly to wards.
    """
    repo = AdministrativeRepository(db)
    districts = await repo.get_districts_by_province(province_code)
    return [
        DistrictResponse(
            code=d.code, 
            name=d.name,
            province_code=d.province_code
        ) 
        for d in districts
    ]


@router.get("/wards", response_model=List[WardResponse])
async def get_wards(
    province_code: str = Query(..., description="Province code"),
    district_code: Optional[str] = Query(None, description="District code (optional for 2-level)"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Get wards/communes based on selection mode.
    
    **Adaptive Logic:**
    - If `district_code` is provided: Returns wards under that district (3-level)
    - If `district_code` is NULL: Returns wards directly under province (2-level)
    
    This allows the frontend to automatically adapt to user's selection flow.
    """
    repo = AdministrativeRepository(db)
    
    if district_code:
        # 3-level: Wards under specific district
        wards = await repo.get_wards_by_district(province_code, district_code)
    else:
        # 2-level: Wards directly under province
        wards = await repo.get_wards_by_province(province_code)
    
    return [
        WardResponse(
            code=w.code,
            name=w.name,
            province_code=w.province_code,
            district_code=w.district_code
        )
        for w in wards
    ]
