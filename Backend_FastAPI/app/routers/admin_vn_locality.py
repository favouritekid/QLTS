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
from app.schemas.vn_locality import CsvImportResponse
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
