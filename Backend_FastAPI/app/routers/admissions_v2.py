# app/routers/admissions_v2.py
"""Admissions v2 — Phase 3 multi-NV choice-engine endpoints.

Routes under `/api/v2/admissions` prefix mirror Casbin policy paths
(`/api/v2/admissions/*/<verb>`) configured trong PR-3B Sub-3:
  * MANAGER ALLOW: publish-result (T6), waitlist-promote (T10), waitlist-reject (T11)
  * OFFICER ALLOW: GET /choices (read), GET /publish-result (read)
  * ADMIN: wildcard /* .* + require_admin dependency cho T17
  * ACCOUNTANT DENY: 6 routes (Phase 1 B1 + Sub-3 5 routes)

BONUS-35 keyMatch4 route convention: all dynamic `{id}` segments use
`{id:[0-9]+}` regex constraint per memory `lead-keymatch4-collision-followup`.

Endpoints (Sub-3.3-3.5b incremental ship):
  * POST /api/v2/admissions/{profile_id:[0-9]+}/publish-result    — T6 (Sub-3.3 SHIP)
  * POST /api/v2/admin/admission-profile-choice/{choice_id:[0-9]+}/promote — T10 (Sub-3.4)
  * POST /api/v2/admissions/{profile_id:[0-9]+}/admin-rollback   — T17 (Sub-3.5b)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import (
    CasbinAuth,
    get_admission_for_manager,
    require_admin,
)
from app.services import admission_choice_engine_service as choice_engine
from app.utils.exceptions import ResourceNotFoundError


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admissions",
    tags=["Admissions v2 — Multi-NV (Phase 3)"],
)


# =============================================================================
# T6 — Publish result (admin batch trigger choice-engine cascade)
# =============================================================================


@router.post(
    "/{profile_id:[0-9]+}/publish-result",
    response_model=schemas.AdmissionPublishResultResponse,
    summary="T6 — Publish admission result (trigger multi-NV choice engine)",
)
async def publish_admission_result(
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),
    current_user: models.User = CasbinAuth,
):
    """T6 publish-result — trigger choice-engine cascade per profile.

    Manager/Admin runs this khi profile sẵn sàng để publish result. Engine
    evaluates each `AdmissionProfileChoice` in `display_order`, applies
    gates + scoring, marks decision per choice (admitted/rejected/skip),
    transitions profile.status reviewing → result_published → admitted/rejected.

    **Pre-checks** (raises 400 BusinessRuleViolation):
    - profile.uses_choice_engine must be True (legacy single-NV use other path)
    - profile.status must be "reviewing"

    **Security**:
    - IDOR: `get_admission_for_manager` (3-tier scope: admin all + manager unit)
    - Casbin: manager/admin allow per PR-3B Sub-3 policy

    **Dispatches** (via state_service.transition() cascade):
    - ADMISSION_RESULT_PUBLISHED (T6, on first transition)
    - ADMISSION_DECISION_ADMITTED / WAITLISTED / REJECTED (T7/T8/T9, on final transition)
    - Per-choice events captured trong CascadeResult.per_choice_decisions

    Returns CascadeResult với per-choice decisions trace cho audit.
    """
    # Re-query profile WITH choices eager-loaded (the IDOR gate returns
    # a thin profile row; cascade needs full relations chain).
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.admission_path)
            .selectinload(models.AdmissionPath.admission_method),
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.admission_path)
            .selectinload(models.AdmissionPath.criteria),
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.path_subject_group_config)
            .selectinload(models.PathSubjectGroupConfig.subject_group)
            .selectinload(models.SubjectGroup.subjects),
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.scores)
            .selectinload(models.ProfileChoiceScore.subject),
        )
    )
    result = await db.execute(stmt)
    full_profile = result.scalar_one()

    # Service helper (Sub-3.2) — pre-checks + evaluate_cascade
    cascade_result, post_commit_cb = await choice_engine.publish_result(
        db, full_profile,
    )

    # V3.0 contract: caller commits, then awaits callback for notif outbox
    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    log.info(
        "admissions_v2.publish_result",
        profile_id=profile_id,
        final_status=cascade_result.final_status,
        admitted_choice_id=cascade_result.admitted_choice_id,
        actor_id=current_user.id,
    )

    return schemas.AdmissionPublishResultResponse(
        profile_id=cascade_result.profile_id,
        final_status=cascade_result.final_status,
        admitted_choice_id=cascade_result.admitted_choice_id,
        admitted_display_order=cascade_result.admitted_display_order,
        per_choice_decisions=cascade_result.per_choice_decisions,
    )


# =============================================================================
# T10 — Waitlist promote (admin manual promote choice waitlisted → admitted)
# =============================================================================


@router.post(
    "/{profile_id:[0-9]+}/waitlist-promote",
    response_model=schemas.AdmissionWaitlistPromoteResponse,
    summary="T10 — Promote waitlisted choice to admitted (admin manual)",
)
async def waitlist_promote_choice(
    profile_id: int,
    payload: schemas.AdmissionWaitlistPromoteRequest,
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),
    current_user: models.User = CasbinAuth,
):
    """T10 manual waitlist promote — admin chọn 1 NV trên waitlist
    chuyển sang admitted.

    DRIFT-01 sync: route profile-scoped per Casbin policy LIVE prod
    (`/api/v2/admissions/*/waitlist-promote`), NOT choice-scoped admin
    namespace per stale Plan v0.7 line 437. `choice_id` moves từ URL
    param vào request body — router verifies ownership.

    **Pre-checks** (raises 400 BusinessRuleViolation):
    - choice.decision must be "waitlisted"
    - profile.status must be "waitlisted"

    **Security**:
    - IDOR: `get_admission_for_manager` (profile-scoped 3-tier)
    - Casbin: manager/admin allow per PR-3B Sub-3 policy
    - Ownership: router verifies choice.admission_profile_id == profile.id
      (defense-in-depth — service helper also checks)

    **Dispatches** (via state_service.transition() + PAIR map):
    - ADMISSION_WAITLIST_PROMOTED (T10 source-aware, NOT generic ADMITTED)
    """
    # Fetch choice + verify ownership (router thin lookup)
    choice = await db.get(models.AdmissionProfileChoice, payload.choice_id)
    if choice is None or choice.admission_profile_id != profile.id:
        # 404 anti-enumeration per IDOR pattern (memory deps.py precedent)
        raise ResourceNotFoundError(
            f"Choice {payload.choice_id} không thuộc hồ sơ {profile_id}"
        )

    # Service helper (Sub-3.2)
    result, post_commit_cb = await choice_engine.promote_waitlisted_choice(
        db,
        choice=choice,
        profile=profile,
        actor=current_user,
        reason=payload.reason,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    log.info(
        "admissions_v2.waitlist_promote",
        profile_id=profile_id,
        choice_id=payload.choice_id,
        actor_id=current_user.id,
        has_reason=bool(payload.reason),
    )

    return schemas.AdmissionWaitlistPromoteResponse(
        choice_id=result["choice_id"],
        profile_id=result["profile_id"],
    )


# =============================================================================
# T17 — Admin rollback (admin force profile back to draft, audit-logged)
# =============================================================================


@router.post(
    "/{profile_id:[0-9]+}/admin-rollback",
    response_model=schemas.AdmissionAdminRollbackResponse,
    summary="T17 — Admin rollback profile to draft (audit-logged)",
)
async def admin_rollback_admission(
    profile_id: int,
    payload: schemas.AdmissionAdminRollbackRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """T17 admin rollback — force any non-final profile state → draft.

    Audit-gated với:
    - **Admin-only**: `require_admin` dependency (NOT CasbinAuth). Manager
      và officer denied via Casbin DENY trên `/api/v2/admissions/*/admin-rollback`
      (Phase 1 B1 accountant deny line 324 + diamond inheritance reach).
    - **Reason mandatory**: payload.reason min 10 chars, max 500 chars
      (`AdmissionAdminRollbackRequest` schema enforces; service defensive
      double-check).

    **Pre-checks** (raises 400 BusinessRuleViolation in service helper):
    - profile.status NOT IN ("enrolled", "withdrawn") — terminal states
      cannot rollback per state machine ALLOWED_TRANSITIONS (Sub-3.5 extension)

    **Security**:
    - No IDOR gate — admin has global scope (require_admin dep enforces)
    - `db.get(profile_id)` direct → 404 if not found (anti-enumeration)

    **Dispatches** (via state_service.transition() + PAIR map):
    - ADMISSION_ROLLED_BACK (T17 source-aware via TRANSITION_PAIR_TO_EVENT
      11 pair entries shipped trong Sub-3.5 atomic). PAIR map fires
      ROLLED_BACK regardless of source state.

    Returns AdmissionAdminRollbackResponse với `rolled_back_from` capture
    cho audit response.
    """
    # Admin global scope — direct db.get (no IDOR gate needed)
    profile = await db.get(models.AdmissionProfile, profile_id)
    if profile is None:
        raise ResourceNotFoundError(f"Hồ sơ {profile_id} không tồn tại")

    # Service helper (Sub-3.2) — pre-checks (terminal state, reason min 10)
    # + state machine transition (source-aware PAIR → ROLLED_BACK)
    result, post_commit_cb = await choice_engine.admin_rollback_profile(
        db,
        profile=profile,
        reason=payload.reason,
        actor=current_admin,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    log.info(
        "admissions_v2.admin_rollback",
        profile_id=profile_id,
        rolled_back_from=result["rolled_back_from"],
        actor_id=current_admin.id,
        reason_length=len(payload.reason),
    )

    return schemas.AdmissionAdminRollbackResponse(
        profile_id=result["profile_id"],
        rolled_back_from=result["rolled_back_from"],
    )
