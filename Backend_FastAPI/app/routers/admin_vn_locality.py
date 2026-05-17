# app/routers/admin_vn_locality.py
"""Admin CSV import + search endpoints for vn_commune_area_map +
vn_high_school (Q9 #07 PR4).

* POST /api/v2/admin/vn-locality/communes/import — upload BNV CSV
* POST /api/v2/admin/vn-locality/high-schools/import — upload MOET CSV
* POST /api/v2/admin/vn-locality/high-schools/seed-sample — 5 demo rows
  (admin one-shot bootstrap so FE dropdown has data pre-MOET CSV)
* GET  /api/v2/vn-locality/high-schools/search?q=X — searchable dropdown
  source for candidate FE (read; not admin-only)
"""
import structlog
from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.deps import get_current_active_user, require_admin
from app.schemas.vn_locality import (
    CsvImportResponse,
    VnHighSchoolResponse,
)
from app.services.vn_locality_service import VnLocalityService


log = structlog.get_logger(__name__)

admin_router = APIRouter(
    prefix="/api/v2/admin/vn-locality",
    tags=["Admin v2 - VN Locality Import"],
)

public_router = APIRouter(
    prefix="/api/v2/vn-locality",
    tags=["VN Locality - Public Read"],
)


# =============================================================================
# Admin: CSV imports + sample seed
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
    csv_bytes = await file.read()
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


@admin_router.post(
    "/high-schools/import",
    response_model=CsvImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_high_school_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> CsvImportResponse:
    """Upload high school CSV (MOET format).

    Expected columns: ``name,province,district,ward,kv_code``. Idempotent —
    skips (name, province) already active."""
    csv_bytes = await file.read()
    service = VnLocalityService(db)
    result, callback = await service.import_high_school_csv(csv_bytes)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_high_school_csv_imported",
        filename=file.filename,
        inserted=result["inserted"],
        skipped=result["skipped_existing"],
        error_count=len(result["error_rows"]),
        actor=user.id,
    )
    return CsvImportResponse(**result)


@admin_router.post(
    "/high-schools/seed-sample",
    status_code=status.HTTP_201_CREATED,
)
async def seed_sample_high_schools(
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> dict:
    """One-shot bootstrap of 5 demo high school rows so candidate FE
    dropdown works before admin uploads the real MOET CSV. Idempotent —
    skips already-existing rows by name+province."""
    service = VnLocalityService(db)
    result, callback = await service.seed_sample_high_schools()
    await db.commit()
    if callback:
        await callback()
    log.info(
        "vn_high_school_sample_seeded",
        inserted=result["inserted"],
        total_in_seed=result["total_in_seed"],
        actor=user.id,
    )
    return result


# =============================================================================
# Public: searchable dropdown source (used by candidate FE)
# =============================================================================


@public_router.get(
    "/high-schools/search",
    response_model=list[VnHighSchoolResponse],
)
async def search_high_schools(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(get_current_active_user),
) -> list[VnHighSchoolResponse]:
    """Case-insensitive name search for candidate dropdown.
    Returns active rows only (is_active=true)."""
    service = VnLocalityService(db)
    rows = await service.search_high_schools(q, limit=limit)
    return [VnHighSchoolResponse.model_validate(r) for r in rows]
