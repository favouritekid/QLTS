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


@router.get("/organization-units/tree-with-aggregation", response_model=List[schemas.OrganizationTreeNodeWithAggregation])
async def get_organization_tree_with_aggregation(
    academic_year: Optional[int] = None,
    include_inactive: bool = False,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """
    Lấy cây tổ chức với thông tin ngành học và dữ liệu tổng hợp.

    - **academic_year**: Năm học cần lấy thông tin (mặc định là năm hiện tại)
    - **include_inactive**: Có bao gồm các đơn vị không hoạt động không (mặc định là False)

    Response bao gồm:
    - Danh sách ngành học trực thuộc mỗi đơn vị
    - Thống kê tổng hợp (số ngành học, chỉ tiêu tuyển sinh, học phí trung bình/min/max)
    - Dữ liệu được tổng hợp từ các đơn vị con lên đơn vị cha
    """
    return await organization_service.get_organization_tree_with_aggregation(
        db, academic_year=academic_year, include_inactive=include_inactive
    )


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


# =============================================================================
# ✅ PHASE 3: MAJOR ACADEMIC INFO API ENDPOINTS (Year-Versioned Data)
# =============================================================================

@router.get("/majors/{major_id}/academic-info", response_model=List[schemas.MajorAcademicInfo])
async def get_major_academic_history(
    major_id: int,
    published_only: bool = False,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """
    Get all academic info history for a major, ordered by year descending.

    Query params:
    - published_only: If true, only return published info (default: false)

    Returns list of academic info sorted by year (newest first).
    """
    return await organization_service.get_academic_info_history(
        db, major_id=major_id, published_only=published_only
    )


@router.get("/majors/{major_id}/academic-info/{year}", response_model=schemas.MajorAcademicInfo)
async def get_major_academic_info_by_year(
    major_id: int,
    year: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """
    Get academic info for a specific major and academic year.

    Returns 404 if no info exists for that year.
    """
    info = await organization_service.get_academic_info_by_major_and_year(
        db, major_id=major_id, academic_year=year
    )
    if not info:
        from ..utils.exceptions import ResourceNotFoundError
        raise ResourceNotFoundError(
            detail=f"Academic info for major {major_id} and year {year} not found."
        )
    return info


@router.post("/majors/{major_id}/academic-info", response_model=schemas.MajorAcademicInfo)
async def create_major_academic_info(
    major_id: int,
    academic_info_in: schemas.MajorAcademicInfoCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """
    Create new academic info for a major and year.

    Requires admin role. Automatically sets created_by_user_id.
    Returns 400 if info already exists for that major/year.
    """
    # Ensure major_id in path matches major_id in body
    if academic_info_in.major_id != major_id:
        from ..utils.exceptions import BadRequest
        raise BadRequest(detail="major_id in path must match major_id in request body")

    return await organization_service.create_academic_info(
        db,
        academic_info_in=academic_info_in,
        created_by_user_id=current_user.id
    )


@router.patch("/academic-info/{academic_info_id}", response_model=schemas.MajorAcademicInfo)
async def update_major_academic_info(
    academic_info_id: int,
    academic_info_in: schemas.MajorAcademicInfoUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """
    Update existing academic info.

    Requires admin role. Supports partial updates.
    Returns 404 if academic info doesn't exist.
    """
    return await organization_service.update_academic_info(
        db,
        academic_info_id=academic_info_id,
        academic_info_in=academic_info_in
    )


@router.delete("/academic-info/{academic_info_id}", status_code=204)
async def delete_major_academic_info(
    academic_info_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = deps.CurrentUser,
):
    """
    Delete academic info (hard delete).

    Requires admin role.
    Note: This is a hard delete. Consider marking as unpublished instead.
    Returns 404 if academic info doesn't exist.
    """
    await organization_service.delete_academic_info(db, academic_info_id=academic_info_id)
    return None  # 204 No Content
