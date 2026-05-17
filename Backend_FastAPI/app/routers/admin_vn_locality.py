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
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.deps import get_current_active_user, require_admin
from app.core.rate_limits import RateLimits, limiter
from app.schemas.vn_locality import (
    CsvImportResponse,
    VnHighSchoolResponse,
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


@limiter.limit(RateLimits.DATA_READ)
@public_router.get(
    "/high-schools/search",
    response_model=list[VnHighSchoolResponse],
)
async def search_high_schools(
    request: Request,
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(get_current_active_user),
) -> list[VnHighSchoolResponse]:
    """Case-insensitive prefix search for candidate dropdown.
    Returns active rows only (is_active=true).

    m-CR-4 fix: rate-limited via slowapi to prevent typing-fast spam.
    CR-M3 fix: prefix match (not substring) — index-friendly + cleaner UX."""
    service = VnLocalityService(db)
    rows = await service.search_high_schools(q, limit=limit)
    return [VnHighSchoolResponse.model_validate(r) for r in rows]
