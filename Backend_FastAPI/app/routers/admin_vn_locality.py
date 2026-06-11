# app/routers/admin_vn_locality.py
"""Admin CSV import endpoints for vn_commune_area_map (Q9 #07 PR4).

Phase1_09 redesign (2026-05-18) removed VnHighSchool endpoints — see
``Documents/Q9_07_PR5_REDESIGN.md`` v1.3. VnSchool family endpoints
(THCS + THPT + TRUNG_HOC_NGHE) will live under /admin/vn-school/* in
Phase B.1 import script + Phase D candidate FE.

Current endpoints:
* POST /api/v2/admin/vn-locality/communes/import — upload BNV CSV
"""
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.deps import require_admin
from app.schemas.vn_locality import (
    CsvImportResponse,
    VnCommuneAreaMapCreate,
    VnCommuneAreaMapListResponse,
    VnCommuneAreaMapReplaceArea,
    VnCommuneAreaMapResponse,
    VnCommuneAreaMapUpdate,
)
from app.services.vn_locality_service import VnLocalityService


# CR-M1: cap CSV upload at 10MB to prevent OOM via accidental/malicious
# huge file. Matches the QLTS lead-import precedent (lead-import-size-pr7
# memory). Real BNV/MOET CSVs are well under 1MB (~11k rows max).
MAX_CSV_SIZE_BYTES = 10 * 1024 * 1024


def _require_csv_filename(filename: str | None) -> None:
    """F.6 fix: reject non-CSV uploads at the router boundary so admin
    sees an immediate 400 instead of "201 inserted=0" after the service
    successfully decodes the file (a binary PDF/txt can decode as UTF-8
    by accident, then DictReader reads junk header → 0 valid rows)."""
    if not filename or not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File phải có đuôi .csv",
        )


log = structlog.get_logger(__name__)

admin_router = APIRouter(
    prefix="/api/v2/admin/vn-locality",
    tags=["Admin v2 - VN Locality Import"],
)

# public_router DROPPED phase1_09 — was only used for /high-schools/search
# (also DROPPED). Will be re-introduced trong Phase D candidate FE with
# new prefix /api/v2/vn-school/* (VnSchool family).


# =============================================================================
# Admin: CSV imports (commune only post-phase1_09)
# =============================================================================


@admin_router.post(
    "/communes/import",
    response_model=CsvImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_commune_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> CsvImportResponse:
    """Upload commune CSV (BNV TT 06/2026 format).

    Expected columns: ``commune_code,province,district,ward,area_code``.
    Idempotent — skips rows where (commune_code, active) already exists.
    Malformed rows collected into ``error_rows`` for admin to fix."""
    # CR-M1: pre-read size check (Content-Length header). Post-read check
    # below catches the case where client lied about size.
    _require_csv_filename(file.filename)
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
    service = VnLocalityService(db)
    result, callback = await service.import_commune_csv(csv_bytes)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_commune_csv_imported",
        filename=file.filename,
        inserted=result["inserted"],
        skipped=result["skipped_existing"],
        error_count=len(result["error_rows"]),
        actor=user.id,
    )
    return CsvImportResponse(**result)


# =============================================================================
# Admin: commune KV CRUD (PR-A — UI quản lý danh mục KV theo xã)
#
# Tất cả ``require_admin`` (quy chế tuyển sinh, không per-unit). Đổi KV đi qua
# ``/replace-area`` (temporal: retire cũ + insert mới), KHÔNG update tại chỗ.
# =============================================================================


@admin_router.get("/communes", response_model=VnCommuneAreaMapListResponse)
async def list_communes(
    province: str | None = None,
    q: str | None = None,
    active_only: bool = True,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(require_admin),
) -> VnCommuneAreaMapListResponse:
    """Bảng paginated + lọc tỉnh (``province`` = tên tỉnh) + search
    (``q`` khớp ward/commune_code)."""
    service = VnLocalityService(db)
    rows, total = await service.list_communes(
        province=province,
        q=q,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )
    return VnCommuneAreaMapListResponse(
        items=[VnCommuneAreaMapResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@admin_router.post(
    "/communes",
    response_model=VnCommuneAreaMapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_commune(
    payload: VnCommuneAreaMapCreate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnCommuneAreaMapResponse:
    service = VnLocalityService(db)
    row, callback = await service.create_commune(payload.model_dump())
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_commune_created",
        id=row.id,
        commune_code=row.commune_code,
        area_code=row.area_code,
        actor=user.id,
    )
    return VnCommuneAreaMapResponse.model_validate(row)


@admin_router.patch(
    "/communes/{commune_id}",
    response_model=VnCommuneAreaMapResponse,
)
async def update_commune(
    commune_id: int,
    payload: VnCommuneAreaMapUpdate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnCommuneAreaMapResponse:
    """PATCH metadata (province/district/ward/effective_to). area_code KHÔNG
    sửa được ở đây (đổi KV → /replace-area)."""
    service = VnLocalityService(db)
    row, callback = await service.update_commune(
        commune_id, payload.model_dump(exclude_unset=True)
    )
    await db.commit()
    if callback:
        await callback()
    log.info("vn_commune_updated", id=row.id, actor=user.id)
    return VnCommuneAreaMapResponse.model_validate(row)


@admin_router.post(
    "/communes/{commune_id}/replace-area",
    response_model=VnCommuneAreaMapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def replace_commune_area(
    commune_id: int,
    payload: VnCommuneAreaMapReplaceArea,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnCommuneAreaMapResponse:
    """Đổi KV temporal: retire dòng cũ + trả dòng active MỚI (201)."""
    service = VnLocalityService(db)
    row, callback = await service.replace_commune_area(
        commune_id, payload.area_code, payload.effective_from
    )
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_commune_area_replaced",
        old_id=commune_id,
        new_id=row.id,
        area_code=row.area_code,
        actor=user.id,
    )
    return VnCommuneAreaMapResponse.model_validate(row)


@admin_router.delete(
    "/communes/{commune_id}",
    response_model=VnCommuneAreaMapResponse,
)
async def retire_commune(
    commune_id: int,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> VnCommuneAreaMapResponse:
    """Retire (soft-close ``effective_to`` = hôm nay). KHÔNG hard-delete."""
    service = VnLocalityService(db)
    row, callback = await service.retire_commune(commune_id)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_commune_retired",
        id=row.id,
        effective_to=str(row.effective_to),
        actor=user.id,
    )
    return VnCommuneAreaMapResponse.model_validate(row)


# =============================================================================
# REMOVED phase1_09 (Q9 #07 PR5 redesign 2026-05-18)
# =============================================================================
# 3 endpoints below REMOVED — VnHighSchool table dropped, replaced by
# VnSchool family (level='THPT'). New endpoints will be exposed under
# /admin/vn-school/* trong Phase B.1 import script + Phase D candidate FE.
#
# Dropped endpoints:
#   POST /admin/vn-locality/high-schools/import
#   POST /admin/vn-locality/high-schools/seed-sample
#   GET  /vn-locality/high-schools/search
#
# FE/clients should switch to /admin/vn-school/* (when ready). Pre-PR5
# any cached call to these endpoints will now 404 (correct behavior —
# better than 500 from NotImplementedError stub).
