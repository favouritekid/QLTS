# app/routers/administrative.py
"""
API endpoints for administrative nodes (provinces, districts, wards).

Two explicit modes controlled by `mode` query parameter:
- mode=current  →  34 provinces, 2-level (province → ward), post 01/07/2025
- mode=legacy   →  63 provinces, 3-level (province → district → ward), pre 01/07/2025
"""

from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core import deps
from app.repositories.administrative_repository import AdministrativeRepository
from app.schemas.administrative import (
    ProvinceResponse,
    DistrictResponse,
    ResolveWardResponse,
    WardResponse,
)


class AddressMode(str, Enum):
    current = "current"
    legacy = "legacy"


router = APIRouter(prefix="/administrative", tags=["Administrative"])


@router.get("/provinces", response_model=List[ProvinceResponse])
async def get_provinces(
    mode: AddressMode = Query(AddressMode.current, description="current = 34 tỉnh hiện hành; legacy = 63 tỉnh cũ"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Get provinces for a specific administrative era.

    - **mode=current**: 34 provinces effective from 01/07/2025 (QĐ 19/2025)
    - **mode=legacy**: 63 provinces valid before 01/07/2025
    """
    repo = AdministrativeRepository(db)
    provinces = await repo.get_provinces(current=mode == AddressMode.current)
    return [
        ProvinceResponse(code=p.code, name=p.name)
        for p in provinces
    ]


@router.get("/districts", response_model=List[DistrictResponse])
async def get_districts(
    province_code: str = Query(..., description="Legacy province code"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Get districts under a legacy province (3-level structure).

    Districts only exist in the legacy era. Current (2-level) provinces
    have no districts — frontend should not call this endpoint in current mode.
    """
    repo = AdministrativeRepository(db)
    districts = await repo.get_districts_by_province(province_code)
    return [
        DistrictResponse(
            code=d.code,
            name=d.name,
            province_code=d.province_code,
        )
        for d in districts
    ]


@router.get("/wards", response_model=List[WardResponse])
async def get_wards(
    province_code: str = Query(..., description="Province code"),
    mode: AddressMode = Query(AddressMode.current, description="current = 2-cấp; legacy = 3-cấp"),
    district_code: Optional[str] = Query(None, description="District code (required for legacy mode)"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Get wards/communes for a specific mode.

    - **mode=current**: 2-level wards directly under province (district_code ignored)
    - **mode=legacy**: 3-level wards under a specific district (district_code required)
    """
    repo = AdministrativeRepository(db)

    if mode == AddressMode.current:
        wards = await repo.get_wards_by_province(province_code)
    else:
        if not district_code:
            return []
        wards = await repo.get_wards_by_district(province_code, district_code)

    return [
        WardResponse(
            code=w.code,
            name=w.name,
            province_code=w.province_code,
            district_code=w.district_code,
        )
        for w in wards
    ]


@router.get("/resolve-ward", response_model=ResolveWardResponse)
async def resolve_ward(
    code: str = Query(..., description="Ward code (current or legacy) to canonicalize"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """PR-3: resolve a ward code (current OR legacy 3-tier) to its canonical
    CURRENT-era commune (code + name).

    The FE calls this when an officer picks an address — esp. from an old
    (3-tier) document — so the profile stores the current commune code and the
    UI can show "→ Xã X (hiện hành)". ``resolved=false`` → officer must pick a
    current-mode commune (the submit gate also fail-closes).
    """
    repo = AdministrativeRepository(db)
    current_code = await repo.resolve_current_ward_code(code)
    current_name = (
        await repo.get_current_ward_name(current_code) if current_code else None
    )
    return ResolveWardResponse(
        input_code=code,
        current_code=current_code,
        current_name=current_name,
        resolved=current_code is not None,
    )
