# app/routers/admin_vn_school.py
"""Admin CRUD endpoints cho vn_school + vn_school_kv_assignment (PR-B).

Prefix ``/api/v2/admin/vn-school`` (bổ trợ public ``/api/v2/vn-school/search``).
Tất cả ``require_admin`` (danh mục quy chế, không per-unit). DELETE school =
deactivate (``is_active=false``), KHÔNG hard-delete (FK
``vn_school_kv_assignment.school_id`` CASCADE).
"""
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.deps import require_admin
from app.models.vn_school import VnSchool
from app.schemas.vn_locality import (
    CsvImportResponse,
    VnSchoolAdminResponse,
    VnSchoolCreate,
    VnSchoolKvAssignmentCreate,
    VnSchoolKvAssignmentResponse,
    VnSchoolKvAssignmentUpdate,
    VnSchoolListResponse,
    VnSchoolProvinceItem,
    VnSchoolUpdate,
)
from app.services.vn_school_service import VnSchoolService

log = structlog.get_logger(__name__)

MAX_CSV_SIZE_BYTES = 10 * 1024 * 1024

admin_router = APIRouter(
    prefix="/api/v2/admin/vn-school",
    tags=["Admin v2 - VN School"],
)


def _school_resp(school: VnSchool, current_kv) -> VnSchoolAdminResponse:
    return VnSchoolAdminResponse(
        id=school.id,
        moet_school_code=school.moet_school_code,
        moet_province_code=school.moet_province_code,
        moet_district_code=school.moet_district_code,
        name=school.name,
        address=school.address,
        province=school.province,
        district=school.district,
        ward=school.ward,
        level=school.level,
        is_dtnt=school.is_dtnt,
        is_active=school.is_active,
        current_kv=current_kv,
    )


# =============================================================================
# Schools
# =============================================================================


@admin_router.get("/schools", response_model=VnSchoolListResponse)
async def list_schools(
    moet_province_code: str | None = None,
    level: str | None = None,
    q: str | None = None,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(require_admin),
) -> VnSchoolListResponse:
    service = VnSchoolService(db)
    rows, total = await service.list_schools(
        moet_province_code=moet_province_code,
        level=level,
        q=q,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )
    return VnSchoolListResponse(
        items=[VnSchoolAdminResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@admin_router.get("/provinces", response_model=list[VnSchoolProvinceItem])
async def list_school_provinces(
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(require_admin),
) -> list[VnSchoolProvinceItem]:
    service = VnSchoolService(db)
    rows = await service.list_school_provinces()
    return [VnSchoolProvinceItem.model_validate(r) for r in rows]


@admin_router.post(
    "/schools",
    response_model=VnSchoolAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_school(
    payload: VnSchoolCreate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnSchoolAdminResponse:
    service = VnSchoolService(db)
    school, callback = await service.create_school(payload.model_dump())
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_school_created",
        id=school.id,
        moet_code=school.moet_school_code,
        actor=user.id,
    )
    return _school_resp(school, await service.current_kv(school.id))


@admin_router.patch(
    "/schools/{school_id}",
    response_model=VnSchoolAdminResponse,
)
async def update_school(
    school_id: int,
    payload: VnSchoolUpdate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnSchoolAdminResponse:
    service = VnSchoolService(db)
    school, callback = await service.update_school(
        school_id, payload.model_dump(exclude_unset=True)
    )
    await db.commit()
    if callback:
        await callback()
    log.info("vn_school_updated", id=school.id, actor=user.id)
    return _school_resp(school, await service.current_kv(school.id))


@admin_router.delete(
    "/schools/{school_id}",
    response_model=VnSchoolAdminResponse,
)
async def deactivate_school(
    school_id: int,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnSchoolAdminResponse:
    """DELETE = deactivate (is_active=false). KHÔNG hard-delete."""
    service = VnSchoolService(db)
    school, callback = await service.deactivate_school(school_id)
    await db.commit()
    if callback:
        await callback()
    log.info("vn_school_deactivated", id=school.id, actor=user.id)
    return _school_resp(school, await service.current_kv(school.id))


@admin_router.post(
    "/schools/import",
    response_model=CsvImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_schools_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> CsvImportResponse:
    """Bulk import trường (CSV UTF-8). Cột: moet_school_code, moet_province_code,
    name, province, level (+ tuỳ chọn). Idempotent. KV assignment qua endpoint
    /kv (KHÔNG qua CSV)."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File phải có đuôi .csv",
        )
    if file.size is not None and file.size > MAX_CSV_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"CSV vượt {MAX_CSV_SIZE_BYTES // (1024 * 1024)}MB",
        )
    csv_bytes = await file.read()
    if len(csv_bytes) > MAX_CSV_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"CSV vượt {MAX_CSV_SIZE_BYTES // (1024 * 1024)}MB",
        )
    service = VnSchoolService(db)
    result, callback = await service.import_schools_csv(csv_bytes)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_school_csv_imported",
        inserted=result["inserted"],
        skipped=result["skipped_existing"],
        error_count=len(result["error_rows"]),
        actor=user.id,
    )
    return CsvImportResponse(**result)


# =============================================================================
# KV assignment (per school)
# =============================================================================


@admin_router.get(
    "/schools/{school_id}/kv",
    response_model=list[VnSchoolKvAssignmentResponse],
)
async def list_kv_assignments(
    school_id: int,
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(require_admin),
) -> list[VnSchoolKvAssignmentResponse]:
    service = VnSchoolService(db)
    rows = await service.list_kv_assignments(school_id)
    return [VnSchoolKvAssignmentResponse.model_validate(r) for r in rows]


@admin_router.post(
    "/schools/{school_id}/kv",
    response_model=VnSchoolKvAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_kv_assignment(
    school_id: int,
    payload: VnSchoolKvAssignmentCreate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnSchoolKvAssignmentResponse:
    service = VnSchoolService(db)
    row, callback = await service.add_kv_assignment(school_id, payload.model_dump())
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_school_kv_added",
        id=row.id,
        school_id=school_id,
        kv=row.kv_code,
        actor=user.id,
    )
    return VnSchoolKvAssignmentResponse.model_validate(row)


@admin_router.patch(
    "/kv/{assignment_id}",
    response_model=VnSchoolKvAssignmentResponse,
)
async def update_kv_assignment(
    assignment_id: int,
    payload: VnSchoolKvAssignmentUpdate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnSchoolKvAssignmentResponse:
    service = VnSchoolService(db)
    row, callback = await service.update_kv_assignment(
        assignment_id, payload.model_dump(exclude_unset=True)
    )
    await db.commit()
    if callback:
        await callback()
    log.info("vn_school_kv_updated", id=row.id, actor=user.id)
    return VnSchoolKvAssignmentResponse.model_validate(row)


@admin_router.delete(
    "/kv/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_kv_assignment(
    assignment_id: int,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> None:
    service = VnSchoolService(db)
    _row, callback = await service.delete_kv_assignment(assignment_id)
    await db.commit()
    if callback:
        await callback()
    log.info("vn_school_kv_deleted", id=assignment_id, actor=user.id)
