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
from typing import Any, Dict

from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core import deps
from app.core.events import SystemEvents
from app.services import organization_service
from app.services.notification_dispatcher import dispatch
from app.utils.exceptions import BadRequest

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(tags=["Admin - Organization"])

# Permission dependency
PermissionDep = Depends(deps.check_permission)


# ============================================================================
# NOTIFICATION HELPER (DRY - Reduces router boilerplate)
# ============================================================================

async def _dispatch_org_notification(
    db: AsyncSession,
    event: SystemEvents,
    payload: Dict[str, Any],
) -> None:
    """
    Helper to dispatch organization notifications.
    Wraps dispatch call with error handling to prevent notification failures
    from affecting the main CRUD operation.
    """
    try:
        await dispatch(db=db, event=event, payload=payload, auto_commit=True)
    except Exception as e:
        log.warning(f"Failed to dispatch {event.value} notification: {e}")


# ============================================================================
# ORGANIZATION UNITS CRUD
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_organization_unit(
    request: Request,
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một đơn vị tổ chức mới."""
    unit, post_commit = await organization_service.create_organization_unit(db, unit_in)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.UNIT_CREATED, {
        "unit_id": unit.id,
        "unit_name": unit.name,
        "unit_type": unit.type,
        "parent_id": unit.parent_id,
        "actor_id": current_admin.id,
    })
    
    return unit


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
)
async def get_organization_unit_details(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    unit: models.OrganizationUnit = Depends(
        lambda unit_id, db, current_user: deps.get_organizational_unit_for_user(
            unit_id=unit_id,
            db=db,
            current_user=current_user,
            allow_read_only=True
        )
    ),
):
    """
    (Admin/Manager/Officer) Get organizational unit details.

    **Security:**
    - ✓ Role: Admin, Manager, or Officer (Casbin)
    - ✓ Ownership: Manager limited to managed units, Officer can view own unit
    - ✓ IDOR Protection: Enabled

    Admin: Can view all units
    Manager: Can view managed units
    Officer: Can view their own unit (read-only)
    """
    return unit


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
)
async def update_existing_organization_unit(
    request: Request,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    unit: models.OrganizationUnit = deps.OrgUnitAccessDep,
):
    """
    (Admin/Manager) Update an organizational unit.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to managed units
    - ✓ IDOR Protection: Enabled

    Admin: Can update all units
    Manager: Can update only managed units
    """
    updated_unit, post_commit = await organization_service.update_organization_unit(db, unit.id, unit_in)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.UNIT_UPDATED, {
        "unit_id": updated_unit.id,
        "unit_name": updated_unit.name,
        "unit_type": updated_unit.type,
        "parent_id": updated_unit.parent_id,
        "actor_id": current_admin.id,
    })
    
    return updated_unit


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Deleted successfully (soft delete)"},
        403: {"description": "Forbidden - IDOR or insufficient permission"},
        404: {"description": "Not found"},
        400: {"description": "Cannot delete - unit has dependencies"}
    }
)
async def delete_existing_organization_unit(
    request: Request,  # Required for rate limiter
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    unit: models.OrganizationUnit = deps.OrgUnitAccessDep,
):
    """
    (Admin/Manager) Delete an organizational unit (soft delete).

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to managed units
    - ✓ IDOR Protection: Enabled

    **Business Rules:**
    - Soft delete only (sets is_active=False)
    - Cannot delete unit with active users or leads

    Admin: Can delete all units
    Manager: Can delete only managed units
    """
    _, post_commit = await organization_service.delete_organization_unit(db, unit.id)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.UNIT_DELETED, {
        "unit_id": unit.id,
        "unit_name": unit.name,
        "unit_type": unit.type,
        "parent_id": unit.parent_id,
        "actor_id": current_admin.id,
    })
    
    return None


# ============================================================================
# MAJOR PROGRAMS CRUD (Level 1 - Chương trình đào tạo)
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/programs",
    response_model=schemas.MajorProgram,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_program(
    request: Request,
    program_in: schemas.MajorProgramCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo chương trình đào tạo mới (Level 1)."""
    program, post_commit = await organization_service.create_major_program(db, program_in)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.PROGRAM_CREATED, {
        "program_id": program.id,
        "program_name": program.name,
        "program_code": program.code,
        "actor_id": current_admin.id,
    })
    
    return program


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/programs/{program_id}",
    response_model=schemas.MajorProgram,
)
async def get_program_details(
    request: Request,
    program_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết chương trình đào tạo."""
    return await organization_service.get_major_program_by_id(db, program_id)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/programs/{program_id}",
    response_model=schemas.MajorProgram,
)
async def update_existing_program(
    request: Request,
    program_id: int,
    program_in: schemas.MajorProgramUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật chương trình đào tạo."""
    program, post_commit = await organization_service.update_major_program(db, program_id, program_in)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.PROGRAM_UPDATED, {
        "program_id": program.id,
        "program_name": program.name,
        "program_code": program.code,
        "actor_id": current_admin.id,
    })
    
    return program


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/programs/{program_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_program(
    request: Request,
    program_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa chương trình đào tạo (soft delete)."""
    program = await organization_service.get_major_program_by_id(db, program_id)  # Get info before delete
    _, post_commit = await organization_service.delete_major_program(db, program_id)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.PROGRAM_DELETED, {
        "program_id": program_id,
        "program_name": program.name,
        "program_code": program.code,
        "actor_id": current_admin.id,
    })
    
    return None


# ============================================================================
# PROGRAM OFFERINGS CRUD (Level 2 - Loại hình đào tạo)
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/programs/{program_id}/offerings",
    response_model=schemas.ProgramOffering,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_offering(
    request: Request,
    program_id: int,
    offering_in: schemas.ProgramOfferingCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo loại hình đào tạo mới cho chương trình (Level 2)."""
    # Ensure program_id in path matches program_id in body
    if offering_in.program_id != program_id:
        raise BadRequest(detail="program_id in path must match program_id in request body")

    offering, post_commit = await organization_service.create_program_offering(db, offering_in)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.OFFERING_CREATED, {
        "offering_id": offering.id,
        "offering_name": offering.name,
        "program_id": offering.program_id,
        "actor_id": current_admin.id,
    })
    
    return offering


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/offerings/{offering_id}",
    response_model=schemas.ProgramOffering,
)
async def get_offering_details(
    request: Request,
    offering_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết loại hình đào tạo."""
    return await organization_service.get_program_offering_by_id(db, offering_id)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/offerings/{offering_id}",
    response_model=schemas.ProgramOffering,
)
async def update_existing_offering(
    request: Request,
    offering_id: int,
    offering_in: schemas.ProgramOfferingUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật loại hình đào tạo."""
    # Service returns (offering, callback) tuple
    offering, post_commit = await organization_service.update_program_offering(
        db, offering_id, offering_in
    )

    # Commit transaction
    await db.commit()

    # Execute post-commit callback
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.OFFERING_UPDATED, {
        "offering_id": offering.id,
        "offering_name": offering.name,
        "program_id": offering.program_id,
        "actor_id": current_admin.id,
    })

    return offering


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/offerings/{offering_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_offering(
    request: Request,
    offering_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa loại hình đào tạo (soft delete)."""
    # Get offering info before delete
    offering = await organization_service.get_program_offering_by_id(db, offering_id)
    _, post_commit = await organization_service.delete_program_offering(db, offering_id)
    await db.commit()
    await post_commit()
    
    # ✅ Dispatch notification (fire-and-forget)
    await _dispatch_org_notification(db, SystemEvents.OFFERING_DELETED, {
        "offering_id": offering_id,
        "offering_name": offering.name,
        "program_id": offering.program_id,
        "actor_id": current_admin.id,
    })
    
    return None


# ============================================================================
# OFFERING ACADEMIC INFO CRUD (Level 3 - Thông tin tuyển sinh)
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/offerings/{offering_id}/academic-info",
    response_model=schemas.OfferingAcademicInfo,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_academic_info(
    request: Request,
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

    academic_info, post_commit = await organization_service.create_academic_info(
        db,
        academic_info_in=academic_info_in,
        created_by_user_id=current_admin.id
    )
    await db.commit()
    await post_commit()
    return academic_info


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.patch(
    "/academic-info/{academic_info_id}",
    response_model=schemas.OfferingAcademicInfo,
)
async def update_existing_academic_info(
    request: Request,
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
    academic_info, post_commit = await organization_service.update_academic_info(
        db,
        academic_info_id=academic_info_id,
        academic_info_in=academic_info_in,
        updated_by_user_id=current_admin.id
    )
    await db.commit()
    await post_commit()
    return academic_info


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/academic-info/{academic_info_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_academic_info(
    request: Request,
    academic_info_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Soft delete thông tin tuyển sinh.

    Note: Đây là soft delete (đánh dấu is_deleted=True).
    Có thể khôi phục bằng endpoint POST /academic-info/{id}/restore.
    Returns 404 nếu academic info không tồn tại.
    """
    _, post_commit = await organization_service.delete_academic_info(db, academic_info_id=academic_info_id)
    await db.commit()
    await post_commit()
    return None


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/academic-info/{academic_info_id}/restore",
    response_model=schemas.OfferingAcademicInfo,
)
async def restore_deleted_academic_info(
    request: Request,
    academic_info_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Khôi phục thông tin tuyển sinh đã bị soft delete.

    Đặt is_deleted = False, cho phép bản ghi hiển thị và chỉnh sửa lại.
    Hữu ích khi người dùng lỡ tay xóa.
    Returns 400 nếu bản ghi chưa bị xóa.
    Returns 404 nếu academic info không tồn tại.
    """
    academic_info, post_commit = await organization_service.restore_academic_info(db, academic_info_id=academic_info_id)
    await db.commit()
    await post_commit()
    return academic_info