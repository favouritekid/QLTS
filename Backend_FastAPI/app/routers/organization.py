# app/routers/organization.py
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, schemas
from ..core import deps
from ..services import organization_service

router = APIRouter(tags=["Organization"])


@router.get("/organization-unit-types", response_model=List[str])
async def get_organization_unit_types():
    """Lấy danh sách các loại đơn vị tổ chức cho phép."""
    return schemas.OrganizationUnitType.values()


@router.get("/organization-units", response_model=List[schemas.OrganizationUnit])
async def get_all_organization_units(
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """Lấy danh sách tất cả các đơn vị."""
    return await organization_service.get_all_organization_units(db)


@router.get("/majors", response_model=List[schemas.Major])
async def get_filtered_majors(
    unitId: int,
    search: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """Lấy danh sách ngành học, lọc theo unitId và tìm kiếm."""
    return await organization_service.get_majors_by_unit_tree(
        db, unit_id=unitId, search_term=search
    )
