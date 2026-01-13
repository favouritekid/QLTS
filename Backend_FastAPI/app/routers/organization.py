# app/routers/organization.py
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, schemas
from ..core.deps import CasbinAuth  # ✅ Phase 2.2: Use standard alias
from ..services import organization_service
from app.core.rate_limits import limiter, RateLimits

router = APIRouter(tags=["Organization"])


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/organization-unit-types", response_model=List[str])
async def get_organization_unit_types(request: Request):
    """Lấy danh sách các loại đơn vị tổ chức cho phép."""
    return schemas.OrganizationUnitType.values()


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/organization-units", response_model=List[schemas.OrganizationUnit])
async def get_all_organization_units(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth,  # ✅ SECURITY FIX: Casbin RBAC enforcement
):
    """Lấy danh sách tất cả các đơn vị với cấu trúc 3-tier."""
    return await organization_service.get_all_organization_units(db)


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/organization-units/tree-with-aggregation", response_model=List[schemas.OrganizationTreeNodeWithAggregation])
async def get_organization_tree_with_aggregation(
    request: Request,
    academic_year: Optional[int] = None,
    include_inactive: bool = False,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Lấy cây tổ chức với thông tin chương trình đào tạo và dữ liệu tổng hợp (3-tier).

    - **academic_year**: Năm học cần lấy thông tin (mặc định là năm hiện tại)
    - **include_inactive**: Có bao gồm các đơn vị không hoạt động không (mặc định là False)

    Response bao gồm (3-tier architecture):
    - Danh sách chương trình (MajorProgram) trực thuộc mỗi đơn vị
    - Mỗi chương trình có nhiều loại hình đào tạo (ProgramOffering)
    - Mỗi loại hình đào tạo có thông tin học thuật theo năm (OfferingAcademicInfo)
    - Thống kê tổng hợp được tổng hợp từ các đơn vị con lên đơn vị cha
    """
    return await organization_service.get_organization_tree_with_aggregation(
        db, academic_year=academic_year, include_inactive=include_inactive
    )


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/programs", response_model=List[schemas.MajorProgram])
async def get_filtered_programs(
    request: Request,
    unitId: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Lấy danh sách chương trình đào tạo (MajorProgram - Level 1), lọc theo unitId và tìm kiếm.
    
    Nếu không có unitId, trả về tất cả chương trình.
    Đây là endpoint mới thay thế cho /majors trong kiến trúc 3-tier.
    """
    return await organization_service.get_programs_by_unit_tree(
        db, unit_id=unitId, search_term=search
    )


# =============================================================================
# ✅ NEW 3-TIER API ENDPOINTS
# =============================================================================

# -----------------------------------------------------------------------------
# PROGRAM OFFERING (Level 2) ENDPOINTS
# -----------------------------------------------------------------------------

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/programs/{program_id}/offerings", response_model=List[schemas.ProgramOffering])
async def get_program_offerings(
    request: Request,
    program_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Lấy danh sách các loại hình đào tạo (offerings) của một chương trình.

    Ví dụ: Chương trình "Công nghệ Thông tin" có thể có:
    - Chính quy
    - Liên thông
    - Từ xa
    """
    return await organization_service.get_offerings_by_program(db, program_id=program_id)


# -----------------------------------------------------------------------------
# OFFERING ACADEMIC INFO (Level 3) ENDPOINTS - Year-Versioned Data
# -----------------------------------------------------------------------------

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/offerings/{offering_id}/academic-info", response_model=List[schemas.OfferingAcademicInfo])
async def get_offering_academic_history(
    request: Request,
    offering_id: int,
    published_only: bool = False,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Lấy lịch sử thông tin học thuật (academic info) của một loại hình đào tạo theo từng năm.

    Query params:
    - published_only: Nếu true, chỉ trả về thông tin đã xuất bản (default: false)

    Returns: Danh sách academic info theo năm (mới nhất trước).
    """
    return await organization_service.get_academic_info_history(
        db, offering_id=offering_id, published_only=published_only
    )


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/offerings/{offering_id}/academic-info/{year}", response_model=schemas.OfferingAcademicInfo)
async def get_offering_academic_info_by_year(
    request: Request,
    offering_id: int,
    year: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Lấy thông tin học thuật của một loại hình đào tạo cho năm học cụ thể.

    Returns 404 nếu không có thông tin cho năm đó.
    """
    info = await organization_service.get_academic_info_by_offering_and_year(
        db, offering_id=offering_id, academic_year=year
    )
    if not info:
        from ..utils.exceptions import ResourceNotFoundError
        raise ResourceNotFoundError(
            detail=f"Academic info for offering {offering_id} and year {year} not found."
        )
    return info


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/offerings/{offering_id}/academic-info/current", response_model=schemas.OfferingAcademicInfo)
async def get_offering_current_academic_info(
    request: Request,
    offering_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Lấy thông tin học thuật hiện tại (năm hiện hành, đã xuất bản) của một loại hình đào tạo.

    Đây là endpoint tiện lợi để lấy thông tin tuyển sinh hiện tại mà không cần chỉ định năm.
    Returns 404 nếu không có thông tin xuất bản cho năm hiện tại.
    """
    info = await organization_service.get_current_academic_info(db, offering_id=offering_id)
    if not info:
        from ..utils.exceptions import ResourceNotFoundError
        raise ResourceNotFoundError(
            detail=f"No published academic info found for offering {offering_id} in current year."
        )
    return info


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("/offerings/{offering_id}/academic-info", response_model=schemas.OfferingAcademicInfo)
async def create_offering_academic_info(
    request: Request,
    offering_id: int,
    academic_info_in: schemas.OfferingAcademicInfoCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Tạo thông tin học thuật mới cho một loại hình đào tạo và năm học.

    Requires admin role. Tự động gán created_by_user_id.
    Returns 400 nếu thông tin đã tồn tại cho offering/year này.
    """
    # Ensure offering_id in path matches offering_id in body
    if academic_info_in.offering_id != offering_id:
        from ..utils.exceptions import BadRequest
        raise BadRequest(detail="offering_id in path must match offering_id in request body")

    return await organization_service.create_academic_info(
        db,
        academic_info_in=academic_info_in,
        created_by_user_id=current_user.id
    )

@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/program-offerings", response_model=List[schemas.ProgramOffering])
async def get_all_program_offerings(
    request: Request,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 1000, # Default limit lớn cho dropdown
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth,
):
    """
    Lấy danh sách tất cả loại hình đào tạo (Flat list).
    Dùng cho các Dropdown chọn Offering.
    """
    return await organization_service.get_all_program_offerings(
        db, is_active=is_active, skip=skip, limit=limit
    )

@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.patch("/academic-info/{academic_info_id}", response_model=schemas.OfferingAcademicInfo)
async def update_offering_academic_info(
    request: Request,
    academic_info_id: int,
    academic_info_in: schemas.OfferingAcademicInfoUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Cập nhật thông tin học thuật hiện có.

    Requires admin role. Hỗ trợ partial updates.
    Returns 404 nếu academic info không tồn tại.
    """
    return await organization_service.update_academic_info(
        db,
        academic_info_id=academic_info_id,
        academic_info_in=academic_info_in,
        updated_by_user_id=current_user.id
    )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/academic-info/{academic_info_id}", status_code=204)
async def delete_offering_academic_info(
    request: Request,
    academic_info_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: schemas.User = CasbinAuth  # ✅ SECURITY FIX: Casbin RBAC enforcement,
):
    """
    Xóa thông tin học thuật (hard delete).

    Requires admin role.
    Note: Đây là hard delete. Nên cân nhắc đánh dấu unpublished thay vì xóa.
    Returns 404 nếu academic info không tồn tại.
    """
    await organization_service.delete_academic_info(db, academic_info_id=academic_info_id)
    return None  # 204 No Content