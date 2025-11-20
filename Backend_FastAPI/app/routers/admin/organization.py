# app/routers/admin/organization.py
"""
Organization & Major Program Management Admin Router

Handles all organization structure and academic program operations including:
- Organization Units CRUD
- Major Programs CRUD (Level 1 - Chương trình đào tạo)
- Program Offerings CRUD (Level 2 - Loại hình đào tạo)

PHASE 2B: Extracted from monolithic admin.py
Dependencies: organization_service (from PHASE 1)

Complexity: MEDIUM (hierarchical CRUD, 3-tier architecture)
"""

import structlog
from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core import deps
from app.services import organization_service
from app.utils.exceptions import BadRequest

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(tags=["Admin - Organization"])

# Permission dependency
PermissionDep = Depends(deps.check_permission)


# ============================================================================
# ORGANIZATION UNITS CRUD
# ============================================================================


@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một đơn vị tổ chức mới."""
    return await organization_service.create_organization_unit(db, unit_in)


@router.get(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
)
async def get_organization_unit_details(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một đơn vị tổ chức."""
    return await organization_service.get_organization_unit_by_id(db, unit_id)


@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
)
async def update_existing_organization_unit(
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một đơn vị tổ chức."""
    return await organization_service.update_organization_unit(db, unit_id, unit_in)


@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_organization_unit(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một đơn vị tổ chức."""
    await organization_service.delete_organization_unit(db, unit_id)
    return None


# ============================================================================
# MAJOR PROGRAMS CRUD (Level 1 - Chương trình đào tạo)
# ============================================================================


@router.post(
    "/programs",
    response_model=schemas.MajorProgram,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_program(
    program_in: schemas.MajorProgramCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo chương trình đào tạo mới (Level 1)."""
    return await organization_service.create_major_program(db, program_in)


@router.get(
    "/programs/{program_id}",
    response_model=schemas.MajorProgram,
)
async def get_program_details(
    program_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết chương trình đào tạo."""
    return await organization_service.get_major_program_by_id(db, program_id)


@router.put(
    "/programs/{program_id}",
    response_model=schemas.MajorProgram,
)
async def update_existing_program(
    program_id: int,
    program_in: schemas.MajorProgramUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật chương trình đào tạo."""
    return await organization_service.update_major_program(db, program_id, program_in)


@router.delete(
    "/programs/{program_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_program(
    program_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa chương trình đào tạo (soft delete)."""
    await organization_service.delete_major_program(db, program_id)
    return None


# ============================================================================
# PROGRAM OFFERINGS CRUD (Level 2 - Loại hình đào tạo)
# ============================================================================


@router.post(
    "/programs/{program_id}/offerings",
    response_model=schemas.ProgramOffering,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_offering(
    program_id: int,
    offering_in: schemas.ProgramOfferingCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo loại hình đào tạo mới cho chương trình (Level 2)."""
    # Ensure program_id in path matches program_id in body
    if offering_in.program_id != program_id:
        raise BadRequest(detail="program_id in path must match program_id in request body")

    return await organization_service.create_program_offering(db, offering_in)


@router.get(
    "/offerings/{offering_id}",
    response_model=schemas.ProgramOffering,
)
async def get_offering_details(
    offering_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết loại hình đào tạo."""
    return await organization_service.get_program_offering_by_id(db, offering_id)


@router.put(
    "/offerings/{offering_id}",
    response_model=schemas.ProgramOffering,
)
async def update_existing_offering(
    offering_id: int,
    offering_in: schemas.ProgramOfferingUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật loại hình đào tạo."""
    return await organization_service.update_program_offering(db, offering_id, offering_in)


@router.delete(
    "/offerings/{offering_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_offering(
    offering_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa loại hình đào tạo (soft delete)."""
    await organization_service.delete_program_offering(db, offering_id)
    return None


# ============================================================================
# OFFERING ACADEMIC INFO CRUD (Level 3 - Thông tin tuyển sinh)
# ============================================================================


@router.post(
    "/offerings/{offering_id}/academic-info",
    response_model=schemas.OfferingAcademicInfo,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_academic_info(
    offering_id: int,
    academic_info_in: schemas.OfferingAcademicInfoCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Tạo thông tin tuyển sinh mới cho loại hình đào tạo (Level 3).

    Mỗi loại hình có thể có nhiều năm học khác nhau.
    Returns 400 nếu thông tin đã tồn tại cho offering/year này.
    """
    # Ensure offering_id in path matches offering_id in body
    if academic_info_in.offering_id != offering_id:
        raise BadRequest(detail="offering_id in path must match offering_id in request body")

    return await organization_service.create_academic_info(
        db,
        academic_info_in=academic_info_in,
        created_by_user_id=current_admin.id
    )


@router.patch(
    "/academic-info/{academic_info_id}",
    response_model=schemas.OfferingAcademicInfo,
)
async def update_existing_academic_info(
    academic_info_id: int,
    academic_info_in: schemas.OfferingAcademicInfoUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Cập nhật thông tin tuyển sinh.

    Supports partial updates.
    Returns 404 nếu academic info không tồn tại.
    """
    return await organization_service.update_academic_info(
        db,
        academic_info_id=academic_info_id,
        academic_info_in=academic_info_in,
        updated_by_user_id=current_admin.id
    )


@router.delete(
    "/academic-info/{academic_info_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_academic_info(
    academic_info_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Xóa thông tin tuyển sinh.

    Note: Đây là hard delete. Nên cân nhắc đánh dấu unpublished thay vì xóa.
    Returns 404 nếu academic info không tồn tại.
    """
    await organization_service.delete_academic_info(db, academic_info_id=academic_info_id)
    return None
