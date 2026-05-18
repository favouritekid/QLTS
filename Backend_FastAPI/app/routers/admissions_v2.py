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
from fastapi import APIRouter, Body, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import (
    CasbinAuth,
    get_admission_for_manager,
    get_admission_for_user,
    get_choice_for_user,
    require_admin,
)
from app.services import admission_choice_engine_service as choice_engine
from app.services.admission_choice_service import AdmissionChoiceService
from app.utils.exceptions import ResourceNotFoundError


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
    from app.services.priority_service import resolve_kv_for_profile

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

    kv, meta = await resolve_kv_for_profile(preview_profile, db)

    log.info(
        "admissions_v2.preview_priority_kv",
        profile_id=profile_id,
        kv_resolved=kv,
        pathway=meta.get("pathway"),
    )

    return schemas.PreviewPriorityKvResponse(
        kv_resolved=kv,
        pathway=meta.get("pathway"),
        rule_applied=meta.get("rule_applied"),
        requires_manual_override=meta.get("requires_manual_override", False),
        reason=meta.get("reason"),
        breakdown=meta.get("breakdown"),
    )
