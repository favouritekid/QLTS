# app/routers/admin_v2_admission_round.py
"""Admin v2 — admission_round CRUD endpoints (#184 Phase 2 PR-2A).

Mirrors the ``admin_v2_system_config`` pattern: ``/api/v2/admin``
prefix, ``Depends(require_admin)`` for write, ``ADMIN_WRITE`` rate
limit, structlog audit.

Endpoints
---------
* ``POST   /api/v2/admin/academic-info/{id}/rounds`` — create
* ``GET    /api/v2/admin/academic-info/{id}/rounds`` — list per academic_info
* ``GET    /api/v2/admin/rounds/{id}`` — single
* ``PATCH  /api/v2/admin/rounds/{id}`` — edit (v2.12 P1 fix #4 quota override)
* ``DELETE /api/v2/admin/rounds/{id}`` — soft-archive
* ``POST   /api/v2/admin/rounds/{id}/extend`` — admin extend end_date (SPEC §2.1.a Rule 2)
"""

import structlog
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import get_current_active_user, require_admin
from app.core.rate_limits import RateLimits, limiter
from app.schemas.admission_round import (
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
# Nested under academic-info
# =============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post(
    "/academic-info/{academic_info_id}/rounds",
    response_model=AdmissionRoundResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_round(
    request: Request,
    academic_info_id: int,
    payload: AdmissionRoundCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Create new round under academic_info.

    Service guards: academic_info exists + not soft-deleted, round_code
    UNIQUE per academic_info, sum(round_quota) ≤ annual_admission_quota
    (PLAN §5 tier 1).
    """
    service = AdmissionRoundService(db)
    round_obj = await service.create(academic_info_id, payload, current_admin)

    await activity_service.log_activity(
        db=db,
        action="admission_round_create",
        resource_type="offering_admission_round",
        resource_id=round_obj.id,
        actor_id=current_admin.id,
        description=(
            f"Round {payload.round_code!r} created for academic_info "
            f"{academic_info_id}"
        ),
        changes={
            "round_code": payload.round_code,
            "round_name": payload.round_name,
            "round_quota": payload.round_quota,
            "admit_quota": payload.admit_quota,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    await db.refresh(round_obj)
    return AdmissionRoundResponse.model_validate(round_obj)


@router.get(
    "/academic-info/{academic_info_id}/rounds",
    response_model=AdmissionRoundListResponse,
)
async def list_rounds_by_academic_info(
    academic_info_id: int,
    db: AsyncSession = Depends(database.get_db),
    _user: models.User = Depends(get_current_active_user),
):
    """List rounds under academic_info, ordered by round_code."""
    service = AdmissionRoundService(db)
    rows = await service.list_by_academic_info(academic_info_id)
    return AdmissionRoundListResponse(
        total=len(rows),
        items=[AdmissionRoundResponse.model_validate(r) for r in rows],
    )


# =============================================================================
# Direct round operations
# =============================================================================


@router.get("/rounds/{round_id}", response_model=AdmissionRoundResponse)
async def get_round(
    round_id: int,
    db: AsyncSession = Depends(database.get_db),
    _user: models.User = Depends(get_current_active_user),
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
    """Update round fields. v2.12 P1 fix #4: round_quota decrease below
    submission_count requires explicit ``override=true`` flag.
    """
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
    """Soft-archive round (Concern γ v6).

    Phase 2 behavior: allow regardless of submission_count (admin
    discretion). ``is_active=false`` hides round khỏi storefront +
    path config dropdown nhưng giữ data integrity (existing profiles
    vẫn link round_id qua applied_rules).
    """
    service = AdmissionRoundService(db)
    round_obj = await service.soft_archive(round_id, current_admin)

    await activity_service.log_activity(
        db=db,
        action="admission_round_soft_archive",
        resource_type="offering_admission_round",
        resource_id=round_id,
        actor_id=current_admin.id,
        description=(
            f"Round {round_id} soft-archived "
            f"(submission_count={round_obj.submission_count})"
        ),
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
    """Admin extend ``end_date`` per SPEC §2.1.a Rule 2.

    Audit fields ``extended_at`` + ``extended_by_user_id`` +
    ``extension_reason`` written atomically. Reason ≥10 chars enforced
    at schema layer.
    """
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
