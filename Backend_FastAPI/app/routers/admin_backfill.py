# app/routers/admin_backfill.py
"""Admin backfill exception queue — Phase 3 PR-3D-B BE-2.

Q-P3-09 endpoints serve `/admin/admission-backfill-queue` FE screen.
4 routes:
  * GET  /api/v2/admin/admission-backfill-exceptions             — paginated list
  * PATCH /api/v2/admin/admission-backfill-exceptions/{id}/resolve — single resolve
  * POST /api/v2/admin/admission-backfill-exceptions/bulk-resolve — batch resolve
  * GET  /api/v2/admin/admission-backfill-exceptions/export.csv   — CSV download

**Security model**:
- All 4 endpoints gated by ``require_admin`` (admin-only — Phase 4 diamond
  inheritance fix unaffected since these routes never hit Casbin).
- ``get_backfill_exception_for_admin`` IDOR gate on `/{id}/resolve` returns
  404 if row missing (anti-enum parity).

Service helpers in ``app.services.admission_backfill_service``; this router
is a thin HTTP translator per V3.0 architecture.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import get_backfill_exception_for_admin, require_admin
from app.services import admission_backfill_service as backfill_service


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admin/admission-backfill-exceptions",
    tags=["Admin — Backfill Exceptions (Phase 3 Q-P3-09)"],
)


def _to_response(
    row: models.AdmissionBackfillException,
) -> schemas.AdmissionBackfillExceptionResponse:
    """Materialize response with denormalized resolved_by username."""
    resolved_by_username = (
        row.resolved_by.username if row.resolved_by is not None else None
    )
    return schemas.AdmissionBackfillExceptionResponse(
        id=row.id,
        profile_id=row.profile_id,
        exception_type=row.exception_type,
        details=row.details,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resolved_by_user_id=row.resolved_by_user_id,
        resolved_by_username=resolved_by_username,
        resolution_notes=row.resolution_notes,
    )


# =============================================================================
# GET / — paginated list with admin filters
# =============================================================================


@router.get(
    "",
    response_model=schemas.BackfillExceptionListResponse,
    summary="List backfill exceptions (admin filter + pagination)",
)
async def list_exceptions(
    exception_type: Optional[str] = Query(
        None, description="Exact match filter on exception_type column"
    ),
    is_resolved: Optional[bool] = Query(
        None, description="True = resolved only; False = open only; null = all"
    ),
    profile_id: Optional[int] = Query(
        None, description="Filter to a single profile"
    ),
    created_from: Optional[datetime] = Query(
        None, description="Inclusive lower bound on created_at"
    ),
    created_to: Optional[datetime] = Query(
        None, description="Exclusive upper bound on created_at"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Admin-only paginated list.

    Filters compose AND. Sorted newest-first. Default 50/page (max 200 for
    bulk-resolve workflows where admin needs to see large batches).
    """
    rows, total = await backfill_service.list_backfill_exceptions(
        db,
        exception_type=exception_type,
        is_resolved=is_resolved,
        profile_id=profile_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )

    log.info(
        "admin_backfill.list",
        actor_id=current_admin.id,
        total=total,
        returned=len(rows),
        filters={
            "exception_type": exception_type,
            "is_resolved": is_resolved,
            "profile_id": profile_id,
        },
    )

    return schemas.BackfillExceptionListResponse(
        items=[_to_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# =============================================================================
# PATCH /{id}/resolve — single resolve
# =============================================================================


@router.patch(
    "/{exception_id}/resolve",
    response_model=schemas.AdmissionBackfillExceptionResponse,
    summary="Resolve a single backfill exception",
)
async def resolve_exception(
    payload: schemas.BackfillExceptionResolveRequest,
    db: AsyncSession = Depends(database.get_db),
    exception: models.AdmissionBackfillException = Depends(
        get_backfill_exception_for_admin
    ),
    current_admin: models.User = Depends(require_admin),
):
    """Mark a single exception resolved with audit notes.

    Service rejects if already resolved (idempotent — admin gets clear 400
    rather than silent re-touch of resolved_by_user_id).
    """
    resolved, post_commit_cb = await backfill_service.resolve_exception(
        db,
        exception=exception,
        resolution_notes=payload.resolution_notes,
        actor_id=current_admin.id,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    # Re-fetch with relation eager-load so denormalized username populates
    await db.refresh(resolved, attribute_names=["resolved_by"])

    log.info(
        "admin_backfill.resolve",
        actor_id=current_admin.id,
        exception_id=resolved.id,
        profile_id=resolved.profile_id,
    )
    return _to_response(resolved)


# =============================================================================
# POST /bulk-resolve — batch resolve
# =============================================================================


@router.post(
    "/bulk-resolve",
    response_model=schemas.BackfillBulkResolveResponse,
    summary="Bulk resolve N backfill exceptions with shared notes",
)
async def bulk_resolve_exceptions(
    payload: schemas.BackfillExceptionBulkResolveRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Resolve up to 500 exceptions atomically with shared resolution notes.

    Counters returned for admin UI feedback:
    - requested: input list size
    - resolved: rows actually updated
    - skipped_already_resolved: rows that were already resolved (no-op)
    - missing: input IDs that didn't exist
    - missing_ids: list of missing IDs for client follow-up
    """
    counters, post_commit_cb = await backfill_service.bulk_resolve_exceptions(
        db,
        exception_ids=payload.exception_ids,
        resolution_notes=payload.resolution_notes,
        actor_id=current_admin.id,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    log.info(
        "admin_backfill.bulk_resolve",
        actor_id=current_admin.id,
        **counters,
    )
    return schemas.BackfillBulkResolveResponse(**counters)


# =============================================================================
# GET /export.csv — CSV streaming download
# =============================================================================


@router.get(
    "/export.csv",
    response_class=StreamingResponse,
    summary="Export filtered exceptions as CSV",
)
async def export_csv(
    exception_type: Optional[str] = Query(None),
    is_resolved: Optional[bool] = Query(None),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Stream a CSV of all matching exceptions (no pagination — admin export).

    Columns: id, profile_id, exception_type, details (JSON-serialized),
    created_at, resolved_at, resolved_by_user_id, resolved_by_username,
    resolution_notes.

    ``details`` JSONB is dumped as raw JSON string into a single column —
    admin tooling parses downstream. Filename uses UTC timestamp for unique
    download names.
    """
    import json

    rows = []
    async for row in backfill_service.iter_csv_rows(
        db,
        exception_type=exception_type,
        is_resolved=is_resolved,
    ):
        # JSON-encode the dict column for CSV cell safety
        row["details"] = json.dumps(row["details"], ensure_ascii=False)
        rows.append(row)

    buf = io.StringIO()
    fieldnames = [
        "id",
        "profile_id",
        "exception_type",
        "details",
        "created_at",
        "resolved_at",
        "resolved_by_user_id",
        "resolved_by_username",
        "resolution_notes",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    buf.seek(0)

    from datetime import timezone as _tz
    ts = datetime.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"backfill_exceptions_{ts}.csv"

    log.info(
        "admin_backfill.export_csv",
        actor_id=current_admin.id,
        row_count=len(rows),
        exception_type=exception_type,
        is_resolved=is_resolved,
    )

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
