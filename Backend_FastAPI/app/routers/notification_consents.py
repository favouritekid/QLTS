# app/routers/notification_consents.py
"""
Phase B7: Notification Consent API — admin CRUD for consent management.

Endpoints:
  POST /api/notification-consents/upsert   — single consent upsert
  POST /api/notification-consents/bulk-import — CSV bulk import
  GET  /api/notification-consents          — list with filters
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import RequireAdmin
from app.core.rate_limits import limiter, RateLimits
from app.services import notification_consent_service

log = structlog.get_logger(__name__)
router = APIRouter(
    prefix="/notification-consents",
    tags=["Notification Consents (Admin)"],
)


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
    current_admin: models.User = RequireAdmin,
):
    """List consent records with optional filters. Admin-only."""
    skip = (page - 1) * page_size

    records, total = await notification_consent_service.list_consents(
        db,
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
    current_user: models.User = RequireAdmin,
):
    """
    Upsert a single consent record.

    If a consent for (channel, source_type, source_id) already exists,
    it is updated. Otherwise a new record is created.
    """
    result = await notification_consent_service.upsert_consent(
        db,
        data=body.model_dump(),
        actor_id=current_user.id,
    )
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
    current_user: models.User = RequireAdmin,
):
    """
    Bulk import consent records from CSV.

    Required columns: channel, source_type, source_id, consent_status
    Optional columns: normalized_phone, normalized_email, consent_source, notes
    """
    content = await file.read()

    result = await notification_consent_service.bulk_import_consents(
        db,
        file_content=content,
        actor_id=current_user.id,
    )
    await db.commit()

    log.info(
        "Consent bulk import completed",
        processed=result["processed"],
        granted=result["granted"],
        revoked=result["revoked"],
        skipped=result["skipped"],
        error_count=len(result["errors"]),
        actor_id=current_user.id,
    )

    return schemas.NotificationConsentImportResult(
        processed=result["processed"],
        granted=result["granted"],
        revoked=result["revoked"],
        skipped=result["skipped"],
        errors=result["errors"],
    )


# ---------------------------------------------------------------------------
# Phase E1: Consent History endpoints
# ---------------------------------------------------------------------------


@limiter.limit(RateLimits.DATA_READ)
@router.get("/history", response_model=schemas.ConsentHistoryPage)
async def list_entity_consent_history(
    request: Request,
    source_type: str = Query(..., description="Entity type (lead, admission_profile, etc.)"),
    source_id: int = Query(..., description="Entity ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = RequireAdmin,
):
    """List consent history for an entity (source_type + source_id). Admin-only."""
    skip = (page - 1) * page_size

    records, total = await notification_consent_service.list_entity_consent_history(
        db,
        source_type=source_type,
        source_id=source_id,
        skip=skip,
        limit=page_size,
    )

    return schemas.ConsentHistoryPage(
        total_count=total,
        history=[
            schemas.ConsentHistoryResponse.model_validate(r)
            for r in records
        ],
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get("/{consent_id}/history", response_model=schemas.ConsentHistoryPage)
async def list_consent_history(
    request: Request,
    consent_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = RequireAdmin,
):
    """List history for a specific consent record. Admin-only."""
    skip = (page - 1) * page_size

    records, total = await notification_consent_service.list_consent_history(
        db,
        consent_id=consent_id,
        skip=skip,
        limit=page_size,
    )

    return schemas.ConsentHistoryPage(
        total_count=total,
        history=[
            schemas.ConsentHistoryResponse.model_validate(r)
            for r in records
        ],
    )
