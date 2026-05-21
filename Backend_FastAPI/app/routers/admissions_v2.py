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

from typing import Optional

import structlog
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import (
    CasbinAuth,
    get_admission_for_manager,
    get_admission_for_user,
    get_choice_for_user,
    get_current_active_user,
    require_admin,
)
from app.services import admission_choice_engine_service as choice_engine
from app.services.admission_choice_service import AdmissionChoiceService
from app.utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admissions",
    tags=["Admissions v2 — Multi-NV (Phase 3)"],
)


# =============================================================================
# T6 — Publish result (manager/admin trigger choice-engine cascade)
#
# Simplified flow per user clarification 2026-05-15: bỏ T2 start-review
# (speculative multi-manager design YAGNI). publish_result giờ accept cả
# `submitted` lẫn `reviewing` state; auto-transition submitted→reviewing
# internal trước khi engine cascade. 1 click thay vì 2 step.
# =============================================================================


@router.post(
    "/{profile_id}/publish-result",
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
            # Q9 #07 review-3 fix: eager-load admission_round so the
            # priority bonus engine (CR-P0) can read academic_year for
            # priority_*_config lookup. Without this chain, the engine
            # falls back to __dict__.get(...) → None → skip priority
            # calc → 0đ bonus on every candidate (silent regression).
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.admission_path)
            .selectinload(models.AdmissionPath.admission_round),
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.admission_path)
            .selectinload(models.AdmissionPath.criteria),
            # Q9 #07 Phase E.4 — choice-engine gate 0 (eligibility) needs
            # derive_target_level_and_type(path), which reads:
            #   path.academic_info.offering.program.degree_level_ref.code
            #   path.academic_info.offering.offering_type_config.code
            # Without this chain, gate 0 raises CONFIG_GAP_TARGET_LEVEL and
            # every choice rejects silently. Mirrors the bonus_rule chain.
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.admission_path)
            .selectinload(models.AdmissionPath.academic_info)
            .selectinload(models.OfferingAcademicInfo.offering)
            .selectinload(models.ProgramOffering.program)
            .selectinload(models.MajorProgram.degree_level_ref),
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.admission_path)
            .selectinload(models.AdmissionPath.academic_info)
            .selectinload(models.OfferingAcademicInfo.offering)
            .selectinload(models.ProgramOffering.offering_type_config),
            # SubjectGroup uses subject_mappings (M2M) → SubjectGroupSubject.subject
            # NOT direct `subjects` relation (em earlier drift, fixed).
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.path_subject_group_config)
            .selectinload(models.PathSubjectGroupConfig.subject_group)
            .selectinload(models.SubjectGroup.subject_mappings)
            .selectinload(models.SubjectGroupSubject.subject),
            selectinload(models.AdmissionProfile.choices)
            .selectinload(models.AdmissionProfileChoice.scores)
            .selectinload(models.ProfileChoiceScore.subject),
        )
    )
    result = await db.execute(stmt)
    full_profile = result.scalar_one()

    # Service helper (Sub-3.2) — pre-checks + auto-transition submitted→
    # reviewing nếu cần + evaluate_cascade. Pass actor cho audit trail.
    cascade_result, post_commit_cb = await choice_engine.publish_result(
        db, full_profile, actor=current_user,
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
    "/{profile_id}/waitlist-promote",
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
        profile_status=result["profile_status"],
    )


# =============================================================================
# T11 — Waitlist reject (manager/admin manual finalize waitlist → rejected)
# Wave 5 ship 2026-05-16
# =============================================================================


@router.post(
    "/{profile_id}/waitlist-reject",
    response_model=schemas.AdmissionWaitlistRejectResponse,
    summary="T11 — Reject waitlisted choice (manager/admin manual)",
)
async def waitlist_reject_choice(
    profile_id: int,
    payload: schemas.AdmissionWaitlistRejectRequest,
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_manager),
    current_user: models.User = CasbinAuth,
):
    """T11 manual waitlist reject — manager/admin chọn 1 NV trên
    waitlist chuyển sang rejected khi đợt closes + slot không mở.

    Mirror waitlist_promote pattern. Difference:
    - `reason` REQUIRED (negative decision needs audit)
    - Fires ADMISSION_WAITLIST_REJECTED (NOT generic DECISION_REJECTED)

    **Pre-checks** (raises 400 BusinessRuleViolation):
    - choice.decision must be "waitlisted"
    - profile.status must be "waitlisted"

    **Security**:
    - IDOR: `get_admission_for_manager` (profile-scoped 3-tier)
    - Casbin: manager/admin allow per template; accountant deny
      (separation-of-duties — waitlist reject is admission decision,
      not finance op)
    - Ownership: router verifies choice.admission_profile_id == profile.id

    **Dispatches** (via state_service.transition() + PAIR map Wave 5):
    - ADMISSION_WAITLIST_REJECTED (T11 source-aware, distinct từ T9
      cascade DECISION_REJECTED)
    """
    # Fetch choice + verify ownership (router thin lookup, mirror promote)
    choice = await db.get(models.AdmissionProfileChoice, payload.choice_id)
    if choice is None or choice.admission_profile_id != profile.id:
        # 404 anti-enumeration per IDOR pattern
        raise ResourceNotFoundError(
            f"Choice {payload.choice_id} không thuộc hồ sơ {profile_id}"
        )

    # Service helper (Wave 5 ship)
    result, post_commit_cb = await choice_engine.reject_waitlisted_choice(
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
        "admissions_v2.waitlist_reject",
        profile_id=profile_id,
        choice_id=payload.choice_id,
        actor_id=current_user.id,
        reason_len=len(payload.reason),
    )

    return schemas.AdmissionWaitlistRejectResponse(
        choice_id=result["choice_id"],
        profile_id=result["profile_id"],
        profile_status=result["profile_status"],
    )


# =============================================================================
# T17 — Admin rollback (admin force profile back to draft, audit-logged)
# =============================================================================


@router.post(
    "/{profile_id}/admin-rollback",
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
        already_at_target=result.get("already_at_target", False),
    )


# =============================================================================
# PR-3D-B BE-1 — Choice CRUD (POST/DELETE/PATCH)
# =============================================================================
# Retroactive multi-NV editing per Plan v0.7 Q-P3-12 Wave B FULL polish.
# Service helpers in admission_choice_service.py enforce 4 prechecks
# (uses_choice_engine + status whitelist + allow_multi_nv + max_choices).
# IDOR gates: get_admission_for_user (POST) + get_choice_for_user (DELETE/PATCH).
# Casbin: officer/manager/admin allow per PR-3D-B Casbin extend; accountant DENY.
#
# Route pattern: `/{profile_id}/choices[/{choice_id}[/scores]]` — plain int
# path params (FastAPI's path-type validation enforces digit-only; Starlette
# does NOT honor inline regex syntax per memory
# `fastapi-route-regex-vs-casbin-keymatch-distinction`).
# =============================================================================


@router.post(
    "/{profile_id}/choices",
    response_model=schemas.AdmissionProfileChoiceResponse,
    status_code=201,
    summary="Create a new choice (retroactive add-NV)",
)
async def create_choice(
    profile_id: int,
    payload: schemas.AdmissionProfileChoiceCreate,
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    current_user: models.User = CasbinAuth,
):
    """POST /api/v2/admissions/{profile_id}/choices.

    Create a new ``AdmissionProfileChoice`` row + N ``ProfileChoiceScore``
    rows in a single atomic transaction. Snapshot pattern: Subject.max_score
    + SubjectGroupSubject.weight frozen at write time.

    **Prechecks** (BusinessRuleViolation → 400):
    - profile.uses_choice_engine == True
    - profile.status IN (draft, revision_requested)
    - round.allow_multi_nv == True OR count < 1 (first choice always OK)
    - existing_count < system_config.max_choices_per_profile
    - path_subject_group_config.admission_path_id == admission_path_id
    - each score.subject_id ∈ SubjectGroupSubject for the chosen group

    **Security**:
    - IDOR: ``get_admission_for_user`` (3-tier scope)
    - Casbin: officer/manager/admin allow; accountant DENY
    """
    service = AdmissionChoiceService(db)
    choice, post_commit_cb = await service.create_choice_with_scores(
        profile=profile,
        admission_path_id=payload.admission_path_id,
        path_subject_group_config_id=payload.path_subject_group_config_id,
        display_order=payload.display_order,
        scores=payload.scores,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    # Re-fetch with eager-load for Contract-06 computed display fields
    full_choice = await service.get_choice(choice.id, eager=True)

    log.info(
        "admissions_v2.create_choice",
        profile_id=profile_id,
        choice_id=choice.id,
        actor_id=current_user.id,
        display_order=payload.display_order,
        score_count=len(payload.scores),
    )

    return schemas.AdmissionProfileChoiceResponse.model_validate(full_choice)


@router.delete(
    "/{profile_id}/choices/{choice_id}",
    response_model=schemas.ChoiceDeleteResponse,
    summary="Delete a choice (retroactive remove)",
)
async def delete_choice(
    profile_id: int,
    db: AsyncSession = Depends(database.get_db),
    choice: models.AdmissionProfileChoice = Depends(get_choice_for_user),
    current_user: models.User = CasbinAuth,
    body: Optional[schemas.ChoiceDeleteRequest] = Body(default=None),
):
    """DELETE /api/v2/admissions/{profile_id}/choices/{choice_id}.

    Cascade-deletes child ``ProfileChoiceScore`` rows via FK ON DELETE CASCADE.

    **Pre-checks** (raises 400 BusinessRuleViolation):
    - profile.uses_choice_engine == True
    - profile.status IN (draft, revision_requested)

    **Ownership**: router verifies ``choice.admission_profile_id == profile_id``
    (defense-in-depth — IDOR already narrows scope, this catches mismatched
    URL paths).

    **Audit (PR-CO-3, FU #114)**: optional body ``{ "reason": "..." }`` is
    captured to ``user_activity_log`` with the choice snapshot + scores
    so DELETEs leave a forensic trace. Body is optional — a payload-less
    DELETE still writes the audit row with a null reason.

    **Security**:
    - IDOR: ``get_choice_for_user`` (3-tier scope)
    - Casbin: officer/manager/admin allow; accountant DENY
    """
    if choice.admission_profile_id != profile_id:
        raise ResourceNotFoundError(
            f"Choice {choice.id} không thuộc hồ sơ {profile_id}"
        )

    service = AdmissionChoiceService(db)
    result, post_commit_cb = await service.delete_choice(
        profile=choice.profile,
        choice=choice,
        actor_id=current_user.id,
        reason=body.reason if body else None,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    log.info(
        "admissions_v2.delete_choice",
        profile_id=profile_id,
        choice_id=result["choice_id"],
        actor_id=current_user.id,
        has_reason=bool(body and body.reason),
    )

    return schemas.ChoiceDeleteResponse(
        choice_id=result["choice_id"],
        profile_id=result["profile_id"],
    )


@router.patch(
    "/{profile_id}/choices/{choice_id}",
    response_model=schemas.AdmissionProfileChoiceResponse,
    summary="Update choice display_order (reorder NV)",
)
async def update_choice_display_order(
    profile_id: int,
    payload: schemas.ChoiceUpdateDisplayOrderRequest,
    db: AsyncSession = Depends(database.get_db),
    choice: models.AdmissionProfileChoice = Depends(get_choice_for_user),
    current_user: models.User = CasbinAuth,
):
    """PATCH /api/v2/admissions/{profile_id}/choices/{choice_id}.

    Manual reorder. DB UNIQUE(profile_id, display_order) catches conflicting
    swaps — FE typically defers updates client-side and sends one PATCH per
    row in deterministic order.

    **Pre-checks** (raises 400 BusinessRuleViolation):
    - profile.uses_choice_engine == True
    - profile.status IN (draft, revision_requested)
    - new_display_order ≤ system_config.max_choices_per_profile

    **Security**:
    - IDOR: ``get_choice_for_user`` (3-tier scope)
    - Casbin: officer/manager/admin allow; accountant DENY
    """
    if choice.admission_profile_id != profile_id:
        raise ResourceNotFoundError(
            f"Choice {choice.id} không thuộc hồ sơ {profile_id}"
        )

    service = AdmissionChoiceService(db)
    updated, post_commit_cb = await service.update_choice_display_order(
        profile=choice.profile,
        choice=choice,
        new_display_order=payload.display_order,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    full_choice = await service.get_choice(updated.id, eager=True)

    log.info(
        "admissions_v2.update_choice_display_order",
        profile_id=profile_id,
        choice_id=updated.id,
        actor_id=current_user.id,
        new_display_order=payload.display_order,
    )

    return schemas.AdmissionProfileChoiceResponse.model_validate(full_choice)


@router.patch(
    "/{profile_id}/choices/{choice_id}/scores",
    response_model=schemas.AdmissionProfileChoiceResponse,
    summary="Replace all scores on a choice",
)
async def replace_choice_scores(
    profile_id: int,
    payload: schemas.ChoiceScoresReplaceRequest,
    db: AsyncSession = Depends(database.get_db),
    choice: models.AdmissionProfileChoice = Depends(get_choice_for_user),
    current_user: models.User = CasbinAuth,
):
    """PATCH /api/v2/admissions/{profile_id}/choices/{choice_id}/scores.

    Idempotent replace — existing rows cleared then re-inserted with fresh
    snapshots from Subject + SubjectGroupSubject. Empty list valid as "clear
    all scores" intent.

    **Pre-checks** (raises 400 BusinessRuleViolation):
    - profile.uses_choice_engine == True
    - profile.status IN (draft, revision_requested)
    - each subject_id ∈ SubjectGroupSubject for choice's subject_group

    **Security**:
    - IDOR: ``get_choice_for_user`` (3-tier scope)
    - Casbin: officer/manager/admin allow; accountant DENY
    """
    if choice.admission_profile_id != profile_id:
        raise ResourceNotFoundError(
            f"Choice {choice.id} không thuộc hồ sơ {profile_id}"
        )

    service = AdmissionChoiceService(db)
    updated, post_commit_cb = await service.replace_choice_scores(
        profile=choice.profile,
        choice=choice,
        scores=payload.scores,
    )

    await db.commit()
    if post_commit_cb:
        await post_commit_cb()

    full_choice = await service.get_choice(updated.id, eager=True)

    log.info(
        "admissions_v2.replace_choice_scores",
        profile_id=profile_id,
        choice_id=updated.id,
        actor_id=current_user.id,
        score_count=len(payload.scores),
    )

    return schemas.AdmissionProfileChoiceResponse.model_validate(full_choice)



# =============================================================================
# Q9 #07 Phase D — Live KV preview (draft state, no snapshot save)
# =============================================================================


@router.post(
    "/{profile_id}/preview-priority-kv",
    response_model=schemas.PreviewPriorityKvResponse,
    summary="Live KV preview — resolve khu vực ưu tiên without saving snapshot",
)
async def preview_priority_kv(
    profile_id: int,
    payload: schemas.PreviewPriorityKvRequest = Body(default_factory=lambda: schemas.PreviewPriorityKvRequest()),
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    current_user: models.User = CasbinAuth,
):
    """Real-time KV resolution cho FE draft state (Q9 #07 Phase D.4).

    Gọi sau debounce khi candidate/officer edit form. Engine resolve_kv_for_profile()
    chạy với profile state hiện tại + payload overrides → trả về kv_resolved
    + breakdown WITHOUT lưu snapshot.

    Snapshot chính thức vẫn frozen ở T1 submit + T6 publish per Phase C wiring.

    Payload override behavior (all fields optional):
    - NULL field → fall back profile DB value
    - Non-NULL field → temporary override cho preview (không persist)

    Security:
    - IDOR: get_admission_for_user (3-tier scope: admin all + manager unit + officer assigned)
    - Casbin: standard read scope (any authenticated user with profile access)
    """
    from copy import copy
    from app.services.priority_service import (
        derive_profile_target_context,
        resolve_kv_for_profile,
    )

    # Build transient profile-like object: profile DB state + form overrides.
    # Shallow copy + override avoids SQLAlchemy session mutation persisting.
    preview_profile = copy(profile)
    if payload.cultural_education_level is not None:
        preview_profile.cultural_education_level = payload.cultural_education_level
    if payload.vocational_qualification is not None:
        preview_profile.vocational_qualification = payload.vocational_qualification
    if payload.area_resolution_basis is not None:
        preview_profile.area_resolution_basis = (
            None if payload.area_resolution_basis == "" else payload.area_resolution_basis
        )
    if payload.permanent_commune_code is not None:
        preview_profile.permanent_commune_code = (
            None if payload.permanent_commune_code == "" else payload.permanent_commune_code
        )
    if payload.academic_history is not None:
        preview_profile.academic_history = [
            r.model_dump(exclude_none=False) for r in payload.academic_history
        ]

    # Apply UT codes override for preview (Phase E wireframe — UT live preview)
    if payload.priority_object_codes is not None:
        preview_profile.priority_object_codes = payload.priority_object_codes

    # Phase E.4 commit 5 fix: preview phải pass target_level + admission_type
    # vào resolve_kv_for_profile. Trước fix: preview rơi vào legacy matrix
    # (target_level=None) → CĐ chính quy + completed_thpt được map sang
    # THUONG_TRU thay vì LICH_SU_THPT → basis hiển thị FE sai trước submit.
    # Sau fix: dùng derive_profile_target_context() trên profile DB state
    # (NOT preview_profile, vì context derive từ path chain DB-side, KHÔNG
    # phụ thuộc form overrides).
    target_ctx = await derive_profile_target_context(profile, db)
    kv, meta = await resolve_kv_for_profile(
        preview_profile,
        db,
        target_level=target_ctx.get("target_level"),
        admission_type=target_ctx.get("admission_type"),
    )

    # Look up bonus rates — KV area_bonus + UT object_bonus (potential + verified)
    # academic_year derived từ profile.admission_path.admission_round nếu có
    # (canonical pattern from evaluate_cascade); fallback current year.
    from decimal import Decimal
    from sqlalchemy import select as _sel
    from app.models.priority_config import PriorityAreaConfig, PriorityObjectConfig

    # Best-effort academic_year — preview doesn't always have round loaded.
    # Source order: admission_round (eager-loaded chain) → profile.academic_year
    # snapshot column → DEFAULT_ADMISSION_YEAR (last resort, log warning).
    # See `profile.academic_year` (models/admission.py:148) — always populated
    # at profile creation per ADM-017.
    academic_year = None
    try:
        path = getattr(profile, "admission_path", None)
        round_obj = path.__dict__.get("admission_round") if path else None
        academic_year = round_obj.__dict__.get("academic_year") if round_obj else None
    except Exception:
        academic_year = None
    if academic_year is None:
        academic_year = profile.academic_year
    if academic_year is None:
        log.warning(
            "preview_priority_kv.no_academic_year",
            profile_id=profile_id,
            fallback=2026,
        )
        academic_year = 2026

    area_bonus = None
    if kv:
        from datetime import date as _date
        today = _date.today()
        rate_stmt = (
            _sel(PriorityAreaConfig.bonus_points)
            .where(
                PriorityAreaConfig.academic_year == academic_year,
                PriorityAreaConfig.area_code == kv,
                PriorityAreaConfig.effective_from <= today,
            )
            .where(
                (PriorityAreaConfig.effective_to.is_(None))
                | (PriorityAreaConfig.effective_to > today)
            )
            .limit(1)
        )
        rate_res = await db.execute(rate_stmt)
        area_bonus = rate_res.scalar_one_or_none()

    # UT preview — MAX rate logic per TT 05/2021 "chỉ hưởng một diện cao nhất".
    # Compute 2 buckets:
    #   potential = MAX across ALL submitted codes (assume all verified)
    #   verified  = MAX across codes status='verified' (engine T6 actual)
    object_bonus_potential = None
    object_bonus_verified = None
    ut_breakdown_data = {
        "codes_submitted": preview_profile.priority_object_codes or [],
        "applied_code_potential": None,
        "applied_rate_potential": None,
        "verified_codes": [],
        "applied_code_verified": None,
        "applied_rate_verified": None,
    }

    submitted_codes = list(preview_profile.priority_object_codes or [])
    if submitted_codes:
        from datetime import date as _date
        today = _date.today()
        ut_stmt = (
            _sel(
                PriorityObjectConfig.sub_code,
                PriorityObjectConfig.bonus_points,
            )
            .where(
                PriorityObjectConfig.academic_year == academic_year,
                PriorityObjectConfig.sub_code.in_(submitted_codes),
                PriorityObjectConfig.effective_from <= today,
            )
            .where(
                (PriorityObjectConfig.effective_to.is_(None))
                | (PriorityObjectConfig.effective_to > today)
            )
        )
        ut_rows = (await db.execute(ut_stmt)).all()
        if ut_rows:
            # Potential MAX (assume all verified)
            top_pot = max(ut_rows, key=lambda r: r[1])
            object_bonus_potential = top_pot[1]
            ut_breakdown_data["applied_code_potential"] = top_pot[0]
            ut_breakdown_data["applied_rate_potential"] = str(top_pot[1])

        # Verified MAX (engine T6 actual)
        evidence = profile.priority_object_evidence or {}
        verified_codes = [
            c for c in submitted_codes
            if isinstance(evidence.get(c), dict)
            and evidence[c].get("status") == "verified"
        ]
        ut_breakdown_data["verified_codes"] = verified_codes
        if verified_codes and ut_rows:
            verified_rows = [r for r in ut_rows if r[0] in verified_codes]
            if verified_rows:
                top_ver = max(verified_rows, key=lambda r: r[1])
                object_bonus_verified = top_ver[1]
                ut_breakdown_data["applied_code_verified"] = top_ver[0]
                ut_breakdown_data["applied_rate_verified"] = str(top_ver[1])

    total_bonus_potential = None
    if area_bonus is not None or object_bonus_potential is not None:
        total_bonus_potential = (area_bonus or Decimal("0")) + (object_bonus_potential or Decimal("0"))

    log.info(
        "admissions_v2.preview_priority_kv",
        profile_id=profile_id,
        kv_resolved=kv,
        pathway=meta.get("pathway"),
        ut_codes_submitted=len(submitted_codes),
        ut_codes_verified=len(ut_breakdown_data["verified_codes"]),
    )

    # Phase E.4 — resolve citation pháp lý cho FE EngineResultCard hiển thị
    # "Căn cứ: <citation>". None nếu rule_applied=ambiguous_requires_manual.
    from app.services.priority_service import resolve_law_citation
    rule_law_citation = resolve_law_citation(meta.get("rule_applied"))

    return schemas.PreviewPriorityKvResponse(
        kv_resolved=kv,
        pathway=meta.get("pathway"),
        rule_applied=meta.get("rule_applied"),
        requires_manual_override=meta.get("requires_manual_override", False),
        reason=meta.get("reason"),
        breakdown=meta.get("breakdown"),
        area_bonus=area_bonus,
        object_bonus_potential=object_bonus_potential,
        object_bonus_verified=object_bonus_verified,
        ut_breakdown=ut_breakdown_data,
        total_bonus_potential=total_bonus_potential,
        rule_law_citation=rule_law_citation,
    )


# =============================================================================
# Q9 #07 Phase E wireframe — UT catalog for candidate picker
# =============================================================================


@router.get(
    "/priority-objects/catalog",
    response_model=list[schemas.PriorityObjectCatalogItem],
    summary="Get UT (đối tượng ưu tiên) catalog for candidate picker",
)
async def get_priority_object_catalog(
    academic_year: int = 2026,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Return list of UT codes admin có configure cho year nhất định.

    Used by candidate FE PriorityTab (Phase E wireframe) for the
    UT multi-select picker. Returns active rows only (effective window
    includes today).

    Auth: any authenticated user (candidate/officer/admin/manager).
    Catalog is org-wide public info, not IDOR-scoped.

    Defaults `academic_year=2026` per current mùa tuyển sinh.
    """
    from datetime import date as _date
    from sqlalchemy import select as _sel
    from app.models.priority_config import PriorityObjectConfig

    today = _date.today()
    stmt = (
        _sel(PriorityObjectConfig)
        .where(
            PriorityObjectConfig.academic_year == academic_year,
            PriorityObjectConfig.effective_from <= today,
        )
        .where(
            (PriorityObjectConfig.effective_to.is_(None))
            | (PriorityObjectConfig.effective_to > today)
        )
        .order_by(
            PriorityObjectConfig.bonus_points.desc(),
            PriorityObjectConfig.sub_code,
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [schemas.PriorityObjectCatalogItem.model_validate(r) for r in rows]


# =============================================================================
# Q9 #07 Phase E.2 — Manual KV override (officer/admin write-path)
# =============================================================================


@router.post(
    "/{profile_id}/override-priority-kv",
    response_model=schemas.AdmissionProfileResponse,
    summary="Override KV thủ công (officer/admin write-path — Phase E.2)",
)
async def override_priority_kv(
    profile_id: int,
    payload: schemas.OverridePriorityKvRequest = Body(...),
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    current_user: models.User = CasbinAuth,
):
    """Officer/admin manually override profile's KV (Phase E.2 write-path).

    Service-layer ``priority_override_service.override_kv()`` enforces:
    * Version guard FIRST (memory `version-guard-before-state-machine`)
    * Status whitelist (officer: submitted/reviewing/revision_requested;
      admin bypass với ``acknowledge_post_publish=true`` for post-publish)
    * Reason 20-500 char validation
    * Snapshot mutation + audit log INSERT + version bump

    Snapshot keys overwritten on each override (Decision D1):
    * ``manual_override_by/at/reason`` + ``evidence_file_id``
    * ``frozen_at_status='manual_override'`` + ``resolved_by`` (officer/admin)

    Audit log preserves full chain — query via composite index
    ``(profile_id, action_type, created_at DESC)``.

    Security:
    * IDOR: ``get_admission_for_user`` (3-tier scope admin/manager/officer)
    * Casbin: ``q9_07_e0c`` migration seeds policy
      (officer/manager/admin ALLOW, accountant DENY).
    * Service ``PermissionError`` (officer post-publish) → 403.

    Dispatches ``PRIORITY_KV_OVERRIDDEN`` event post-commit (catalog seed
    Wave 1; payload: application_id, lead_id, actor_id, actor_name,
    kv_resolved, override_reason).
    """
    from app.services.priority_override_service import override_kv as _override_kv
    from fastapi import HTTPException

    try:
        updated_profile, post_commit_cb = await _override_kv(
            db,
            profile,
            kv_resolved=payload.kv_resolved,
            reason=payload.reason,
            evidence_file_id=payload.evidence_file_id,
            actor=current_user,
            expected_version=payload.version,
            acknowledge_post_publish=payload.acknowledge_post_publish,
        )
    except PermissionError as exc:
        # Officer attempted post-publish override; map to 403 per memory
        # `version-guard-before-state-machine` adjacent pattern.
        raise HTTPException(status_code=403, detail=str(exc))

    await db.commit()
    await post_commit_cb()

    log.info(
        "admissions_v2.override_priority_kv",
        profile_id=profile_id,
        actor_id=current_user.id,
        kv_resolved=payload.kv_resolved,
    )

    # Reload với eager-loaded relations for response (assigned_officer
    # name + reviewer name + computed permissions).
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
    )
    reloaded = (await db.execute(stmt)).scalar_one()
    # Populate computed fields cho mutation response per Backend CLAUDE.md
    # "Mutation response contract" — _populate_response_fields() must run
    # post-mutation to set permissions/available_actions/etc.
    from app.services import admission_service

    await admission_service._populate_response_fields(
        db, reloaded, current_user=current_user
    )
    return reloaded


# =============================================================================
# Q9 #07 Phase E.3 — UT evidence verify/reject (officer write-path)
# =============================================================================


async def _evidence_response(
    db: AsyncSession,
    profile_id: int,
    current_user: models.User,
) -> models.AdmissionProfile:
    """Shared reload + _populate_response_fields cho verify/reject responses."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.services import admission_service

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
    )
    reloaded = (await db.execute(stmt)).scalar_one()
    await admission_service._populate_response_fields(
        db, reloaded, current_user=current_user
    )
    return reloaded


@router.patch(
    "/{profile_id}/priority-objects/{sub_code}/verify",
    response_model=schemas.AdmissionProfileResponse,
    summary="Duyệt UT evidence (officer write-path — Phase E.3)",
)
async def verify_priority_object_evidence(
    profile_id: int,
    sub_code: str,
    payload: schemas.VerifyObjectEvidenceRequest = Body(...),
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    current_user: models.User = CasbinAuth,
):
    """Officer marks ``priority_object_evidence[sub_code]`` as verified.

    Bumps version + INSERTs audit log + recomputes
    ``priority_resolution_snapshot.ut_verified_bucket`` (engine T6 actual
    rate freeze). Dispatches PRIORITY_OBJECT_VERIFIED via outbox.

    Security:
    * IDOR: ``get_admission_for_user`` (3-tier scope)
    * Casbin: ``q9_07_e0c`` seed (officer/manager/admin ALLOW, accountant DENY)

    Per Decision D3 (plan v3): candidate uploads minh chứng qua existing
    DocumentsTab (step 6); officer picks ``document_id`` từ
    ``profile.documents`` tại verify time.
    """
    from app.services.priority_override_service import verify_object_evidence
    from fastapi import HTTPException

    try:
        _, post_commit_cb = await verify_object_evidence(
            db,
            profile,
            sub_code=sub_code,
            document_id=payload.document_id,
            actor=current_user,
            expected_version=payload.version,
            acknowledge_post_publish=payload.acknowledge_post_publish,
        )
    except PermissionError as exc:
        # Officer/manager attempted post-publish verify; map to 403
        # (parity với override_priority_kv handler above).
        raise HTTPException(status_code=403, detail=str(exc))

    await db.commit()
    await post_commit_cb()

    log.info(
        "admissions_v2.verify_priority_object_evidence",
        profile_id=profile_id,
        sub_code=sub_code,
        actor_id=current_user.id,
    )
    return await _evidence_response(db, profile_id, current_user)


@router.patch(
    "/{profile_id}/priority-objects/{sub_code}/reject",
    response_model=schemas.AdmissionProfileResponse,
    summary="Từ chối UT evidence (officer write-path — Phase E.3)",
)
async def reject_priority_object_evidence(
    profile_id: int,
    sub_code: str,
    payload: schemas.RejectObjectEvidenceRequest = Body(...),
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    current_user: models.User = CasbinAuth,
):
    """Officer marks ``priority_object_evidence[sub_code]`` as rejected.

    Reject reason 10-500 char mandatory. Recomputes ``ut_verified_bucket``
    — if rejected code was the applied verified code, bucket falls back
    to next-highest verified (or null if none remain).

    Dispatches PRIORITY_OBJECT_REJECTED via outbox với reject_reason
    trong payload.
    """
    from app.services.priority_override_service import reject_object_evidence
    from fastapi import HTTPException

    try:
        _, post_commit_cb = await reject_object_evidence(
            db,
            profile,
            sub_code=sub_code,
            reject_reason=payload.reject_reason,
            actor=current_user,
            expected_version=payload.version,
            acknowledge_post_publish=payload.acknowledge_post_publish,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    await db.commit()
    await post_commit_cb()

    log.info(
        "admissions_v2.reject_priority_object_evidence",
        profile_id=profile_id,
        sub_code=sub_code,
        actor_id=current_user.id,
    )
    return await _evidence_response(db, profile_id, current_user)


# =============================================================================
# Q9 #07 Phase E.4 — Priority evidence upload + untick (PR-2)
# =============================================================================


@router.post(
    "/{profile_id}/priority-evidence/{sub_code}/upload",
    response_model=schemas.AdmissionProfileResponse,
    summary="Upload UT evidence document (Phase E.4 PR-2)",
    status_code=status.HTTP_200_OK,
)
async def upload_priority_evidence(
    profile_id: int,
    sub_code: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Upload minh chứng UT cho 1 sub_code.

    File constraints: PDF/JPG/PNG ≤10MB + magic-byte sniff. Profile MUST
    be trong APPLICANT_DOC_MUTATION_STATES + sub_code MUST be in
    ``profile.priority_object_codes`` + catalog year MUST có sub_code.

    ADM-007 staging/finalize: file staged trước commit, promote post-commit.
    Re-upload thay file cũ; doc_row status reset to 'uploaded' (officer
    phải verify lại sau re-upload).

    Security:
    * IDOR: ``upload_priority_evidence_document`` calls ``get_profile``.
    * Casbin: q9_07_e4 seed (officer/manager/admin ALLOW, accountant DENY).
    """
    from app.services import admission_service

    try:
        profile, finalize = await admission_service.upload_priority_evidence_document(
            db=db,
            profile_id=profile_id,
            sub_code=sub_code,
            file=file,
            current_user=current_user,
        )
        try:
            await db.commit()
        except Exception:
            await finalize(False)
            raise
        await finalize(True)
        await db.refresh(profile)

        log.info(
            "admissions_v2.upload_priority_evidence",
            profile_id=profile_id,
            sub_code=sub_code,
            actor_id=current_user.id,
        )
        return await _evidence_response(db, profile_id, current_user)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        # IDOR: 404 to prevent enumeration
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
        )
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/{profile_id}/priority-evidence/{sub_code}",
    response_model=schemas.AdmissionProfileResponse,
    summary="Untick UT code + cascade delete evidence (Phase E.4 G1)",
)
async def untick_priority_object_evidence(
    profile_id: int,
    sub_code: str,
    payload: schemas.UntickPriorityEvidenceRequest = Body(...),
    db: AsyncSession = Depends(database.get_db),
    profile: models.AdmissionProfile = Depends(get_admission_for_user),
    current_user: models.User = CasbinAuth,
):
    """Officer unticks UT code → cascade hard delete file + JSONB cleanup.

    Atomic 4-mutation contract (G1):
    1. Remove sub_code từ priority_object_codes JSONB.
    2. Remove sub_code entry từ priority_object_evidence JSONB.
    3. DELETE profile_document row (category='priority_evidence',
       priority_sub_code=sub_code).
    4. INSERT priority_audit_log (action='ut_evidence_untick').
    Plus recompute ut_verified_bucket if unticked code was applied verified.

    File unlink via ADM-007 finalize callback (post-commit best-effort).

    Decision #4 UI safety: FE shows confirm dialog BEFORE call. Service
    assumes caller confirmed (no double-prompt). Soft delete defer Phase E.5.

    Security:
    * IDOR: ``get_admission_for_user`` (3-tier scope).
    * Casbin: q9_07_e4 seed (officer/manager/admin ALLOW, accountant DENY).
    """
    from app.services.priority_override_service import untick_priority_evidence

    try:
        _, finalize_cb = await untick_priority_evidence(
            db,
            profile,
            sub_code=sub_code,
            actor=current_user,
            expected_version=payload.version,
        )
        try:
            await db.commit()
        except Exception:
            await finalize_cb(False)
            raise
        await finalize_cb(True)

        log.info(
            "admissions_v2.untick_priority_object_evidence",
            profile_id=profile_id,
            sub_code=sub_code,
            actor_id=current_user.id,
        )
        return await _evidence_response(db, profile_id, current_user)

    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
        )
