# app/routers/notification_consents.py
"""
Phase B7: Notification Consent API — admin CRUD for consent management.

Endpoints:
  POST /api/notification-consents/upsert   — single consent upsert
  POST /api/notification-consents/bulk-import — CSV bulk import
  GET  /api/notification-consents          — list with filters
"""
import csv
import io
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import CasbinAuth, get_current_active_user
from app.core.rate_limits import limiter, RateLimits
from app.repositories.notification_consent_repository import NotificationConsentRepository

log = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/notification-consents",
    tags=["Notification Consents (Admin)"],
)

# Required CSV columns for bulk import
_REQUIRED_CSV_COLS = {"channel", "source_type", "source_id", "consent_status"}


@limiter.limit(RateLimits.DATA_READ)
@router.get("", response_model=schemas.NotificationConsentsPage)
async def list_consents(
    request: Request,
    channel: Optional[str] = Query(None, description="Filter by channel"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    consent_status: Optional[str] = Query(None, description="Filter by consent status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """List consent records with optional filters. Admin-only."""
    repo = NotificationConsentRepository(db)
    skip = (page - 1) * page_size

    records, total = await repo.list_consents(
        channel=channel,
        source_type=source_type,
        consent_status=consent_status,
        skip=skip,
        limit=page_size,
    )

    return schemas.NotificationConsentsPage(
        total_count=total,
        consents=[
            schemas.NotificationConsentResponse.model_validate(r)
            for r in records
        ],
    )


@limiter.limit(RateLimits.DATA_WRITE)
@router.post("/upsert", response_model=schemas.NotificationConsentResponse)
async def upsert_consent(
    request: Request,
    body: schemas.NotificationConsentUpsert,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Upsert a single consent record.

    If a consent for (channel, source_type, source_id) already exists,
    it is updated. Otherwise a new record is created.
    """
    repo = NotificationConsentRepository(db)

    now = datetime.now(timezone.utc)
    data = body.model_dump()
    data["granted_by"] = current_user.id

    if body.consent_status == "granted":
        data["granted_at"] = now
        data["revoked_at"] = None
    elif body.consent_status == "revoked":
        data["revoked_at"] = now

    result = await repo.upsert_latest(data)
    await db.commit()

    log.info(
        "Consent upserted",
        channel=body.channel,
        source_type=body.source_type,
        source_id=body.source_id,
        consent_status=body.consent_status,
        actor_id=current_user.id,
    )

    return schemas.NotificationConsentResponse.model_validate(result)


@limiter.limit(RateLimits.DATA_WRITE)
@router.post("/bulk-import", response_model=schemas.NotificationConsentImportResult)
async def bulk_import_consents(
    request: Request,
    file: UploadFile = File(..., description="CSV file with consent records"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Bulk import consent records from CSV.

    Required columns: channel, source_type, source_id, consent_status
    Optional columns: normalized_phone, normalized_email, consent_source, notes
    """
    # Read and decode CSV
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    # Validate headers
    if not reader.fieldnames:
        return schemas.NotificationConsentImportResult(
            processed=0, granted=0, revoked=0, skipped=0,
            errors=[{"line": 0, "message": "Empty CSV or missing headers"}],
        )

    missing = _REQUIRED_CSV_COLS - set(reader.fieldnames)
    if missing:
        return schemas.NotificationConsentImportResult(
            processed=0, granted=0, revoked=0, skipped=0,
            errors=[{"line": 0, "message": f"Missing required columns: {', '.join(sorted(missing))}"}],
        )

    # Build rows
    now = datetime.now(timezone.utc)
    rows = []
    parse_errors = []

    for i, row in enumerate(reader, start=2):  # line 1 = header
        try:
            source_id = int(row["source_id"])
        except (ValueError, TypeError):
            parse_errors.append({"line": i, "message": f"Invalid source_id: {row.get('source_id')}"})
            continue

        consent_status = row.get("consent_status", "granted").strip().lower()
        if consent_status not in ("granted", "revoked"):
            parse_errors.append({"line": i, "message": f"Invalid consent_status: {consent_status}"})
            continue

        data = {
            "channel": row["channel"].strip(),
            "source_type": row["source_type"].strip(),
            "source_id": source_id,
            "consent_status": consent_status,
            "consent_source": row.get("consent_source", "csv_import").strip() or "csv_import",
            "granted_by": current_user.id,
            "notes": row.get("notes", "").strip() or None,
            "normalized_phone": row.get("normalized_phone", "").strip() or None,
            "normalized_email": row.get("normalized_email", "").strip() or None,
        }

        if consent_status == "granted":
            data["granted_at"] = now
        elif consent_status == "revoked":
            data["revoked_at"] = now

        rows.append(data)

    # Bulk upsert
    repo = NotificationConsentRepository(db)
    summary = await repo.bulk_upsert(rows)
    await db.commit()

    # Merge parse errors into summary
    all_errors = parse_errors + summary.get("errors", [])

    log.info(
        "Consent bulk import completed",
        processed=summary["processed"],
        granted=summary["granted"],
        revoked=summary["revoked"],
        skipped=summary["skipped"] + len(parse_errors),
        error_count=len(all_errors),
        actor_id=current_user.id,
    )

    return schemas.NotificationConsentImportResult(
        processed=summary["processed"],
        granted=summary["granted"],
        revoked=summary["revoked"],
        skipped=summary["skipped"] + len(parse_errors),
        errors=all_errors,
    )
