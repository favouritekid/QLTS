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
)
from app.services import admission_choice_engine_service as choice_engine


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
