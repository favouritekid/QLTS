# app/routers/admin_v2_admission_round.py
"""Admin v2 — admission_round CRUD endpoints (Phase 2 v8.2 PR-2A v2).

Year-level routes (Q1 v8.2). Mirrors ``admin_v2_system_config`` pattern:
``/api/v2/admin`` prefix, ``Depends(require_admin)`` for read+write
(Q P2-3 v8.1 — admin URL space implies admin-only), structlog audit.

Endpoints
---------
* ``POST   /api/v2/admin/years/{academic_year}/rounds`` — create single
* ``POST   /api/v2/admin/years/{academic_year}/rounds/bulk-create`` — atomic 4 đợt
* ``GET    /api/v2/admin/years/{academic_year}/rounds`` — list per year
* ``GET    /api/v2/admin/rounds/{round_id}`` — single
* ``PATCH  /api/v2/admin/rounds/{round_id}`` — edit time-window/lifecycle
* ``DELETE /api/v2/admin/rounds/{round_id}`` — soft-archive
* ``POST   /api/v2/admin/rounds/{round_id}/extend`` — admin extend end_date
"""

import structlog
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin
from app.core.rate_limits import RateLimits, limiter
from app.schemas.admission_round import (
    AdmissionRoundBulkCreate,
    AdmissionRoundBulkCreateResponse,
    AdmissionRoundCreate,
    AdmissionRoundExtend,
    AdmissionRoundListResponse,
    AdmissionRoundResponse,
    AdmissionRoundUpdate,
)
from app.services import activity_service
from app.services.admission_round_service import AdmissionRoundService


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admin",
    tags=["Admin v2 - Admission Round"],
)


# =============================================================================
# Year-level scoped endpoints
# =============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post(
    "/years/{academic_year}/rounds",
    response_model=AdmissionRoundResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_round(
    request: Request,
    academic_year: int,
    payload: AdmissionRoundCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Create new round under academic_year (Q1 v8.2 — year-level)."""
    service = AdmissionRoundService(db)
    round_obj = await service.create(academic_year, payload, current_admin)

    await activity_service.log_activity(
        db=db,
        action="admission_round_create",
        resource_type="offering_admission_round",
        resource_id=round_obj.id,
        actor_id=current_admin.id,
        description=(
            f"Round {payload.round_code!r} created cho năm {academic_year}"
        ),
        changes={
            "academic_year": academic_year,
            "round_code": payload.round_code,
            "round_name": payload.round_name,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    await db.refresh(round_obj)
    return AdmissionRoundResponse.model_validate(round_obj)


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post(
    "/years/{academic_year}/rounds/bulk-create",
    response_model=AdmissionRoundBulkCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_create_rounds(
    request: Request,
    academic_year: int,
    payload: AdmissionRoundBulkCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Bulk-create rounds (e.g., 4 đợt năm 2026 atomic).

    Per Q1 v8.2 + PR-2A v2 plan: top-down workflow — admin tạo nhiều
    rounds cùng lúc thay vì per-major bottom-up.
    """
    service = AdmissionRoundService(db)
    created, skipped = await service.bulk_create(academic_year, payload, current_admin)

    await activity_service.log_activity(
        db=db,
        action="admission_round_bulk_create",
        resource_type="offering_admission_round",
        actor_id=current_admin.id,
        description=(
            f"Bulk-created {len(created)} rounds cho năm {academic_year} "
            f"({skipped} duplicates skipped)"
        ),
        changes={
            "academic_year": academic_year,
            "requested": len(payload.rounds),
            "created": len(created),
            "skipped": skipped,
            "round_codes": [r.round_code for r in created],
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    for r in created:
        await db.refresh(r)

    return AdmissionRoundBulkCreateResponse(
        requested=len(payload.rounds),
        created=len(created),
        skipped_duplicates=skipped,
        items=[AdmissionRoundResponse.model_validate(r) for r in created],
    )


@router.get(
    "/years/{academic_year}/rounds",
    response_model=AdmissionRoundListResponse,
)
async def list_rounds_by_year(
    academic_year: int,
    db: AsyncSession = Depends(database.get_db),
    _admin: models.User = Depends(require_admin),
):
    """List rounds under academic_year, ordered by round_code."""
    service = AdmissionRoundService(db)
    rows = await service.list_by_year(academic_year)
    return AdmissionRoundListResponse(
        total=len(rows),
        items=[AdmissionRoundResponse.model_validate(r) for r in rows],
    )


# =============================================================================
# Direct round operations (by round_id)
# =============================================================================


@router.get("/rounds/{round_id}", response_model=AdmissionRoundResponse)
async def get_round(
    round_id: int,
    db: AsyncSession = Depends(database.get_db),
    _admin: models.User = Depends(require_admin),
):
    """Fetch single round detail."""
    service = AdmissionRoundService(db)
    round_obj = await service.get_by_id(round_id)
    return AdmissionRoundResponse.model_validate(round_obj)


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.patch("/rounds/{round_id}", response_model=AdmissionRoundResponse)
async def update_round(
    request: Request,
    round_id: int,
    payload: AdmissionRoundUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Update round time-window/lifecycle (Phase 2 scope per Q3 v8.2)."""
    service = AdmissionRoundService(db)
    round_obj = await service.update(round_id, payload, current_admin)

    await activity_service.log_activity(
        db=db,
        action="admission_round_update",
        resource_type="offering_admission_round",
        resource_id=round_id,
        actor_id=current_admin.id,
        description=f"Round {round_id} updated",
        changes=payload.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    await db.refresh(round_obj)
    return AdmissionRoundResponse.model_validate(round_obj)


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.delete("/rounds/{round_id}", response_model=AdmissionRoundResponse)
async def soft_archive_round(
    request: Request,
    round_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Soft-archive round (Concern γ v6 carry forward).

    Phase 2: allow regardless of submission_count (admin discretion).
    """
    service = AdmissionRoundService(db)
    round_obj = await service.soft_archive(round_id, current_admin)

    await activity_service.log_activity(
        db=db,
        action="admission_round_soft_archive",
        resource_type="offering_admission_round",
        resource_id=round_id,
        actor_id=current_admin.id,
        description=f"Round {round_id} soft-archived",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    await db.refresh(round_obj)
    return AdmissionRoundResponse.model_validate(round_obj)


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post("/rounds/{round_id}/extend", response_model=AdmissionRoundResponse)
async def extend_round(
    request: Request,
    round_id: int,
    payload: AdmissionRoundExtend,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Admin extend ``end_date`` per SPEC §2.1.a Rule 2."""
    service = AdmissionRoundService(db)
    round_obj = await service.extend(round_id, payload, current_admin)

    await activity_service.log_activity(
        db=db,
        action="admission_round_extend",
        resource_type="offering_admission_round",
        resource_id=round_id,
        actor_id=current_admin.id,
        description=(
            f"Round {round_id} end_date extended to {payload.end_date.isoformat()}"
        ),
        changes={
            "new_end_date": payload.end_date.isoformat(),
            "extension_reason": payload.extension_reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    await db.refresh(round_obj)
    return AdmissionRoundResponse.model_validate(round_obj)
