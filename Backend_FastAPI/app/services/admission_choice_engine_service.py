# app/services/admission_choice_engine_service.py
"""
Phase 3 PR-3C Sub-2 — Choice-engine cascade orchestration (T6 publish).

Orchestrates the multi-NV admit cascade: loops `profile.choices` by
`display_order`, applies gates (min_gpa, graduation_year), scores per
choice via `AdmissionScoringService.calculate_score()`, and writes the
admit/reject decision PLUS the `bonus_rule_snapshot` (Q-P3-11 — snapshot
tại T6, NOT T1 submit).

ARCHITECTURE
============
This module is **NEW** (PR-3C Sub-2) — split from
`admission_scoring_service.py` because that file is constrained to pure
stateless rules (no DB writes, no side effects). Cascade orchestration
needs to:
  * write to `AdmissionProfileChoice` rows (decision + scores +
    bonus_rule_snapshot + eligibility_check_result)
  * transition `AdmissionProfile.status` via
    `admission_state_service.transition()`
  * dispatch ADMISSION_* events with `strict=True` per memory
    ``dispatch-bundle-strict-required``

Returns the V3.0 architecture tuple `(result, post_commit_callback)`
— caller commits DB then awaits callback for outbox flush.

CASCADE RULES (plan v0.7 Phần 3.1)
==================================
For each `choice` in `profile.choices.order_by(display_order)`:
  1. Resolve `effective_bonus_rule` = path.bonus_rule_override
                                       ?? method.default_bonus_rule
  2. Snapshot to `choice.bonus_rule_snapshot` (Q-P3-11)
  3. Apply gates (Sub-1 helpers):
     - `_check_min_gpa(profile.gpa_overall, criteria.min_gpa)`
     - `_check_graduation_year_range(...)` (NO-OP cho mùa 2026)
  4. If any gate fails → `choice.decision = 'rejected'` + capture reason
     into `eligibility_check_result`. Continue to next choice.
  5. Call `calculate_score(criteria, scores, allowed_subjects, weights)`
  6. Decision logic:
     - `score.passed=True`        → `choice.decision='admitted'`,
                                     mark remaining choices `'skip'`,
                                     BREAK loop
     - `score.passed=False`       → `choice.decision='rejected'`,
                                     continue next
     - `score.status=INVALID`     → `choice.decision='rejected'`
  7. After cascade: transition `profile.status`:
     - At least 1 admitted → `result_published` then `admitted`
     - All rejected         → `result_published` then `rejected`
     - Auto-waitlist DEFERRED Q-P3-05 (mùa đầu manual only)

ATOMICITY
=========
Caller wraps `evaluate_cascade()` trong `async with db.begin_nested()`
per memory ``dispatch-bundle-strict-required`` — partial fail per
profile rollback without nuking the batch. `strict=True` on dispatch
propagates persistence errors so the savepoint catches them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.events import SystemEvents
from ..utils.exceptions import BusinessRuleViolation
from .admission_scoring_service import (
    AdmissionScoringService,
    AdmissionScoreResult,
    DisqualificationReason,
    ProfileStatus,
)

if TYPE_CHECKING:
    from ..models import (
        AdmissionProfile,
        AdmissionProfileChoice,
        AdmissionPath,
    )

log = structlog.get_logger(__name__)


# ============================================================================
# Result dataclass
# ============================================================================


@dataclass
class CascadeResult:
    """Outcome of `evaluate_cascade()` per profile.

    Records per-choice decisions + final profile status transition so
    caller (router) can build response payload + audit log.
    """
    profile_id: int
    final_status: str  # 'admitted' | 'rejected' | 'waitlisted'
    admitted_choice_id: Optional[int] = None
    admitted_display_order: Optional[int] = None
    per_choice_decisions: List[Dict[str, Any]] = field(default_factory=list)
    # Per-choice entry: {choice_id, display_order, decision, reasons, score}


# ============================================================================
# Bonus rule resolution (Q-P3-11 snapshot source)
# ============================================================================


def resolve_effective_bonus_rule(path: "AdmissionPath") -> Optional[Dict[str, Any]]:
    """Resolve BonusRule per chain: path.bonus_rule_override
    ?? method.default_bonus_rule. Returns dict (JSONB-shaped) or None.

    Caller MUST eager-load path.admission_method to avoid lazy-load
    in async context.

    Q-P3-11 contract: snapshot value captured tại T6 publish time
    (NOT T1 submit). Subsequent changes to method/path bonus rule
    config do NOT mutate the snapshot — historical audit preserved.
    """
    override = getattr(path, "bonus_rule_override", None)
    if override is not None:
        return dict(override) if isinstance(override, dict) else override
    method = getattr(path, "admission_method", None)
    if method is None:
        return None
    default = getattr(method, "default_bonus_rule", None)
    if default is None:
        return None
    return dict(default) if isinstance(default, dict) else default


# ============================================================================
# Per-choice evaluation (gates + score + decision)
# ============================================================================


def _evaluate_single_choice(
    profile: "AdmissionProfile",
    choice: "AdmissionProfileChoice",
    priority_bonus: Decimal = Decimal("0"),
) -> Tuple[str, Optional[AdmissionScoreResult], List[str]]:
    """Evaluate ONE choice in isolation — gates first, then scoring.

    Q9 #07 CR-P0 fix: ``priority_bonus`` is added to ``final_score``
    after the raw score is calculated, and the ``passed`` flag is
    re-checked against ``min_score``. Without this addition the snapshot
    columns are decorative — quy chế Bộ GDĐT bị vi phạm vì candidate
    ưu tiên KHÔNG được hưởng quyền lợi cộng điểm.

    Returns:
        (decision, score_result_or_none, reason_codes)
        decision ∈ {'admitted', 'rejected'} — waitlist deferred Q-P3-05

    Side effects: mutates ``score_result.final_score`` / ``score_result.passed`` /
    ``score_result.failure_reasons`` / ``score_result.disqualification_codes``
    when priority bonus flips the pass/fail outcome.
    """
    reason_codes: List[str] = []
    path = choice.admission_path

    # Gate 1: min GPA threshold (Sub-1 helper)
    # AdmissionPath has FK to AdmissionCriteria via criteria_id. Eager-loaded.
    criteria = getattr(path, "criteria", None)
    if criteria is not None:
        passed_gpa, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=getattr(profile, "gpa_overall", None),
            criteria_min_gpa=getattr(criteria, "min_gpa", None),
        )
        if not passed_gpa:
            reason_codes.append(reason)
            return "rejected", None, reason_codes

        # Gate 2: graduation year range (Sub-1 helper; NO-OP cho mùa 2026)
        # Phase 4 will activate by passing criteria.min/max_graduation_year
        passed_year, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=getattr(profile, "graduation_year", None),
            # Phase 1 #04 deferred → pass None until Phase 4
            criteria_min_graduation_year=None,
            criteria_max_graduation_year=None,
        )
        if not passed_year:
            reason_codes.append(reason)
            return "rejected", None, reason_codes

    # Gate 3..6 + scoring via existing calculate_score (Phase 2 rules)
    # Caller MUST have provided subject_scores on profile (eager loaded)
    subject_scores = _collect_subject_scores(choice)
    allowed_subjects = _resolve_allowed_subjects(choice)

    score_result: Optional[AdmissionScoreResult] = None
    if criteria is not None and subject_scores and allowed_subjects:
        score_result = AdmissionScoringService.calculate_score(
            criteria=criteria,
            subject_scores=subject_scores,
            allowed_subjects=allowed_subjects,
            subject_weights=None,  # Phase 4: read from path snapshot
        )

        # Q9 #07 CR-P0: apply priority bonus to final_score + re-check
        # passed flag against min_score threshold. This is the load-
        # bearing line — without it the snapshot columns get written
        # but the decision is computed from raw score only, silently
        # rejecting candidates who qualify for the bonus.
        if (
            score_result.status == ProfileStatus.VALID
            and score_result.final_score is not None
            and priority_bonus > Decimal("0")
        ):
            boosted = score_result.final_score + priority_bonus
            min_threshold = score_result.min_score_threshold
            score_result.final_score = boosted
            if min_threshold is None or boosted >= min_threshold:
                # Bonus flipped fail → pass. Clean up the "below min"
                # disqualification artifacts so audit shows what really
                # happened (raw fail + bonus rescue).
                was_failing_on_min = (
                    DisqualificationReason.BELOW_MIN_SCORE.value
                    in score_result.disqualification_codes
                )
                if was_failing_on_min:
                    score_result.disqualification_codes = [
                        c for c in score_result.disqualification_codes
                        if c != DisqualificationReason.BELOW_MIN_SCORE.value
                    ]
                    score_result.failure_reasons = [
                        r for r in score_result.failure_reasons
                        if "điểm chuẩn" not in r.lower()
                    ]
                score_result.passed = True

        reason_codes.extend(score_result.disqualification_codes)
        if score_result.status == ProfileStatus.INVALID:
            return "rejected", score_result, reason_codes
        if not score_result.passed:
            return "rejected", score_result, reason_codes
        return "admitted", score_result, reason_codes

    # Missing data → reject with explicit code
    if not subject_scores:
        reason_codes.append("NO_VALID_SCORES")
    return "rejected", score_result, reason_codes


def _collect_subject_scores(choice: "AdmissionProfileChoice") -> Dict[str, Any]:
    """Build subject_scores dict from choice.scores eager-loaded rows.

    Returns {subject_code: Decimal score}.
    """
    out: Dict[str, Any] = {}
    scores = getattr(choice, "scores", None) or []
    for score_row in scores:
        subject = getattr(score_row, "subject", None)
        code = getattr(subject, "code", None) if subject else None
        if code:
            out[code] = getattr(score_row, "score", None)
    return out


def _resolve_allowed_subjects(choice: "AdmissionProfileChoice") -> List[str]:
    """Extract allowed subjects from choice.path_subject_group_config.

    Returns list of subject codes in deterministic order.

    Schema: SubjectGroup has `subject_mappings` (M2M to SubjectGroupSubject)
    NOT direct `subjects` relation. Navigate via mapping → subject chain.
    """
    config = getattr(choice, "path_subject_group_config", None)
    if config is None:
        return []
    group = getattr(config, "subject_group", None)
    if group is None:
        return []
    # SubjectGroup.subject_mappings → SubjectGroupSubject.subject → Subject
    mappings = getattr(group, "subject_mappings", None) or []
    codes: List[str] = []
    for sgs in mappings:
        subj = getattr(sgs, "subject", None)
        code = getattr(subj, "code", None) if subj else None
        if code:
            codes.append(code)
    return codes


# ============================================================================
# Main orchestration — evaluate_cascade
# ============================================================================


async def evaluate_cascade(
    db: AsyncSession,
    profile: "AdmissionProfile",
) -> Tuple[CascadeResult, Optional[Callable[[], Awaitable[None]]]]:
    """T6 publish: sequential admit cascade per profile.choices.

    PRE-CONDITIONS:
        * `profile.uses_choice_engine == True` (caller verifies)
        * `profile.status == 'reviewing'` (caller verifies)
        * `profile.choices` eager-loaded with path + criteria +
          path_subject_group_config + subject_group + scores chain
        * Caller wrapped trong `async with db.begin_nested()` for atomic
          per-profile rollback semantic

    SIDE EFFECTS:
        * Writes `choice.decision` + `choice.bonus_rule_snapshot` +
          `choice.eligibility_check_result` per choice
        * Marks remaining choices `'skip'` after first admit
        * Transitions `profile.status` via state_service.transition()
        * Dispatches ADMISSION_RESULT_PUBLISHED + per-choice decision event

    Returns:
        `(CascadeResult, post_commit_callback)` — V3.0 contract.
        Caller commits db then awaits callback for notification outbox flush.

    Raises:
        BusinessRuleViolation: if state machine rejects transition edge
        (propagated from state_service.transition())
    """
    from . import admission_state_service as state_service
    from .notification_dispatcher import dispatch_event

    # Sort choices by display_order (eager-loaded relation already ordered
    # per AdmissionProfile.choices relationship but defensive sort here).
    sorted_choices = sorted(
        profile.choices,
        key=lambda c: c.display_order,
    )

    result = CascadeResult(
        profile_id=profile.id,
        final_status="rejected",  # Default — overridden if any admit
    )

    admitted_found = False
    for choice in sorted_choices:
        if admitted_found:
            # First admit found → mark remaining choices as 'skip'
            choice.decision = "skip"
            result.per_choice_decisions.append({
                "choice_id": choice.id,
                "display_order": choice.display_order,
                "decision": "skip",
                "reasons": [],
                "score": None,
            })
            continue

        # Q-P3-11: snapshot bonus_rule at T6 publish time
        path = choice.admission_path
        choice.bonus_rule_snapshot = resolve_effective_bonus_rule(path)

        # Q9 #07 PR2b: snapshot priority bonus (KV + UT) at T6 publish
        # time alongside bonus_rule_snapshot. Same freeze semantic — later
        # admin edits to priority_*_config tables do NOT mutate the
        # snapshot. Engine treats NULL rule + missing rates as 0đ
        # (graceful for legacy 315 profiles without backfill).
        # Lazy import: priority_service imports app.models which would
        # create a circular dep at module load time of this engine file.
        from app.services.priority_service import calculate_priority_bonus

        round_obj = getattr(path, "admission_round", None)
        academic_year = (
            getattr(round_obj, "academic_year", None) if round_obj else None
        )
        if academic_year is not None:
            (
                choice.priority_area_bonus_snapshot,
                choice.priority_object_bonus_snapshot,
                choice.priority_config_snapshot,
            ) = await calculate_priority_bonus(
                db=db,
                profile=profile,
                rule=choice.bonus_rule_snapshot,
                academic_year=academic_year,
            )

        # Q9 #07 CR-P0: feed the priority bonus total into the decision
        # so the snapshot columns actually affect admit/reject. Without
        # this, ưu tiên candidates get the snapshot written but still
        # bounced for raw-score < min_score (quy chế Bộ vi phạm).
        priority_bonus_total = (
            (choice.priority_area_bonus_snapshot or Decimal("0"))
            + (choice.priority_object_bonus_snapshot or Decimal("0"))
        )

        # Per-choice decision (gates + scoring + priority bonus)
        decision, score_result, reason_codes = _evaluate_single_choice(
            profile, choice, priority_bonus=priority_bonus_total,
        )
        choice.decision = decision

        # Record eligibility check result for audit trail
        choice.eligibility_check_result = {
            "decision": decision,
            "reason_codes": reason_codes,
            "score": (
                {
                    "final_score": (
                        float(score_result.final_score)
                        if score_result and score_result.final_score is not None
                        else None
                    ),
                    "passed": score_result.passed if score_result else False,
                    "selected_subjects": (
                        score_result.selected_subjects if score_result else []
                    ),
                }
                if score_result
                else None
            ),
        }

        result.per_choice_decisions.append({
            "choice_id": choice.id,
            "display_order": choice.display_order,
            "decision": decision,
            "reasons": reason_codes,
            "score": (
                float(score_result.final_score)
                if score_result and score_result.final_score is not None
                else None
            ),
        })

        if decision == "admitted":
            admitted_found = True
            result.admitted_choice_id = choice.id
            result.admitted_display_order = choice.display_order

    # Final profile status — admitted if any choice admitted, else rejected
    final_status = "admitted" if admitted_found else "rejected"
    result.final_status = final_status

    await db.flush()

    # Transition profile status: reviewing → result_published → final
    # (state machine forbids reviewing → admitted directly per PR-3B map)
    _, cb1 = await state_service.transition(
        db, profile, "result_published",
        source="choice_engine",
        event_metadata={"cascade_run": True, "admitted_count": 1 if admitted_found else 0},
    )
    _, cb2 = await state_service.transition(
        db, profile, final_status,
        source="choice_engine",
        event_metadata={
            "cascade_run": True,
            "admitted_choice_id": result.admitted_choice_id,
        },
    )

    log.info(
        "admission_choice_engine.evaluate_cascade",
        profile_id=profile.id,
        final_status=final_status,
        admitted_choice_id=result.admitted_choice_id,
        per_choice_count=len(result.per_choice_decisions),
    )

    # Chain callbacks: caller commits + awaits both dispatches
    async def chained_callback() -> None:
        if cb1 is not None:
            await cb1()
        if cb2 is not None:
            await cb2()

    return result, chained_callback


# ============================================================================
# Sub-3.2 — Router-facing service helper
# ============================================================================


async def publish_result(
    db: AsyncSession,
    profile: "AdmissionProfile",
    *,
    actor: Optional[Any] = None,
) -> Tuple[CascadeResult, Optional[Callable[[], Awaitable[None]]]]:
    """T6 publish-result service entry point (router-facing).

    Thin wrapper trên `evaluate_cascade()` adding pre-condition guards.
    Used by `POST /api/v2/admissions/{id}/publish-result` router (Sub-3.3).

    SIMPLIFIED FLOW 2026-05-15: bỏ T2 start-review explicit step (YAGNI
    cho solo-manager system). Endpoint giờ accept cả `submitted` lẫn
    `reviewing` state; nếu `submitted` → internal transition
    submitted→reviewing trước khi engine evaluate (atomic). State machine
    giữ nguyên — `reviewing` vẫn là intermediate state cho engine cascade
    audit trail (state_history ghi cả 2 transitions).

    PRE-CHECKS (raises BusinessRuleViolation):
        1. `profile.uses_choice_engine == True` — only multi-NV profiles
           publish via choice engine; legacy single-NV profiles flow qua
           existing `admission_service.review_*` paths.
        2. `profile.status` IN ("submitted", "reviewing") — manager click
           "Công bố kết quả" trực tiếp từ submitted (1-click) HOẶC từ
           reviewing (legacy 2-step still supported nếu admin set state
           manual qua state machine).

    NO `begin_nested()` wrap here — single-profile publish ships within
    the router's outer transaction. Batch-publish (future Phase 4 ship)
    would wrap per-profile in begin_nested with `dispatch_event(strict=True)`
    propagation per memory `dispatch-bundle-strict-required`. For single-
    profile case, FastAPI dependency rollback on exception suffices.

    Args:
        db: Caller async session.
        profile: AdmissionProfile to publish.
        actor: User triggering publish (manager/admin) — passed to
               state_service.transition() cho audit trail. Optional cho
               backward-compat (Phase 3 caller chưa pass).

    Returns:
        `(CascadeResult, post_commit_callback)` per V3.0 contract.
        Caller (router) commits db then awaits callback for
        notification outbox flush.

    Raises:
        BusinessRuleViolation: pre-check failure (engine flag / wrong state)
                                or downstream state machine edge rejection.
    """
    from . import admission_state_service as state_service

    if not getattr(profile, "uses_choice_engine", False):
        raise BusinessRuleViolation(
            "Hồ sơ không bật multi-NV choice engine — không thể publish qua engine"
        )
    if profile.status not in ("submitted", "reviewing"):
        raise BusinessRuleViolation(
            f"Hồ sơ phải ở trạng thái 'submitted' hoặc 'reviewing' để publish; "
            f"trạng thái hiện tại: '{profile.status}'"
        )

    # Auto-transition submitted → reviewing trước engine cascade. Engine
    # vẫn cần reviewing state làm intermediate (per state_machine T6 edge:
    # reviewing → result_published only). transition() handle audit log
    # + dispatch event ADMISSION_REVIEW_STARTED nếu rule cấu hình.
    if profile.status == "submitted":
        await state_service.transition(
            db,
            profile,
            "reviewing",
            actor=actor,
            reason="Auto-transition trước engine cascade (publish_result)",
            source="api",
        )

    return await evaluate_cascade(db, profile)


# ============================================================================
# Sub-3.2 — Waitlist promote helper (T10)
# ============================================================================


async def promote_waitlisted_choice(
    db: AsyncSession,
    choice: "AdmissionProfileChoice",
    profile: "AdmissionProfile",
    actor: Any,
    reason: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[Callable[[], Awaitable[None]]]]:
    """T10 manual promote: waitlisted → admitted (admin action).

    Used by `POST /api/v2/admissions/{profile_id}/waitlist-promote`
    (Sub-3.4 router, profile-scoped per Casbin policy LIVE prod — see
    DRIFT-01 sync from Plan v0.7 line 437 stale choice-scoped path).
    Uses PR-3B Sub-2 `TRANSITION_PAIR_TO_EVENT` source-aware mapping:
    `(waitlisted, admitted)` fires `ADMISSION_WAITLIST_PROMOTED` (NOT
    generic `ADMISSION_DECISION_ADMITTED` from target alone).

    PRE-CHECKS:
        1. `choice.decision == "waitlisted"` — only waitlisted choices
           can be promoted
        2. `profile.status == "waitlisted"` — must match (engine sets
           both together per cascade)

    Returns:
        `(result_dict, post_commit_callback)` per V3.0 contract.
    """
    from . import admission_state_service as state_service

    if choice.decision != "waitlisted":
        raise BusinessRuleViolation(
            f"Nguyện vọng phải ở quyết định 'waitlisted'; current: '{choice.decision}'"
        )
    if profile.status != "waitlisted":
        raise BusinessRuleViolation(
            f"Hồ sơ phải ở trạng thái 'waitlisted'; current: '{profile.status}'"
        )

    # Update choice decision FIRST so audit trail captures the source
    choice.decision = "admitted"
    await db.flush()

    # State transition fires ADMISSION_WAITLIST_PROMOTED via PAIR map
    _, callback = await state_service.transition(
        db, profile, "admitted",
        actor=actor,
        reason=reason,  # Optional audit context (Sub-3.4 router passes payload.reason)
        source="waitlist_promote",
        event_metadata={
            "promoted_from_waitlist": True,
            "choice_id": choice.id,
            "display_order": choice.display_order,
        },
    )

    return (
        {
            "choice_id": choice.id,
            "decision": "admitted",
            "profile_id": profile.id,
            "profile_status": "admitted",
        },
        callback,
    )


# ============================================================================
# Wave 5 — Waitlist reject helper (T11) — ship 2026-05-16
# ============================================================================


async def reject_waitlisted_choice(
    db: AsyncSession,
    choice: "AdmissionProfileChoice",
    profile: "AdmissionProfile",
    actor: Any,
    reason: str,
) -> Tuple[Dict[str, Any], Optional[Callable[[], Awaitable[None]]]]:
    """T11 manual reject: waitlisted → rejected (admin/manager action).

    Used by `POST /api/v2/admissions/{profile_id}/waitlist-reject`
    (Wave 5 ship 2026-05-16). Mirror semantic của
    `promote_waitlisted_choice` (T10) — manager/admin manually finalize
    candidate dự bị → trượt khi đợt closes + slot không mở.

    Uses PR-3B Sub-2 `TRANSITION_PAIR_TO_EVENT` source-aware mapping:
    `(waitlisted, rejected)` fires `ADMISSION_WAITLIST_REJECTED` (NOT
    generic `ADMISSION_DECISION_REJECTED` từ T9 engine cascade).
    Notification consumers cần distinguish first-pass reject (T9) vs
    second-pass admin finalize (T11) cho audit + candidate UX.

    PRE-CHECKS:
        1. `choice.decision == "waitlisted"` — only waitlisted choices
           can be rejected via T11 path (T9 cascade reject covers other)
        2. `profile.status == "waitlisted"` — must match (engine sets
           both together per cascade)

    Difference vs promote:
        - `reason` REQUIRED min 10 chars (admin justify negative
          decision per memory phase3-pr-3d-b-backlog "DELETE audit +
          reason"). Promote reason optional vì positive outcome.

    Returns:
        `(result_dict, post_commit_callback)` per V3.0 contract.
    """
    from . import admission_state_service as state_service

    if choice.decision != "waitlisted":
        raise BusinessRuleViolation(
            f"Nguyện vọng phải ở quyết định 'waitlisted'; current: '{choice.decision}'"
        )
    if profile.status != "waitlisted":
        raise BusinessRuleViolation(
            f"Hồ sơ phải ở trạng thái 'waitlisted'; current: '{profile.status}'"
        )

    # Update choice decision FIRST so audit trail captures the source
    choice.decision = "rejected"
    await db.flush()

    # State transition fires ADMISSION_WAITLIST_REJECTED via PAIR map
    _, callback = await state_service.transition(
        db, profile, "rejected",
        actor=actor,
        reason=reason,  # Required audit context
        source="waitlist_reject",
        event_metadata={
            "rejected_from_waitlist": True,
            "choice_id": choice.id,
            "display_order": choice.display_order,
            "reason": reason,
        },
    )

    return (
        {
            "choice_id": choice.id,
            "decision": "rejected",
            "profile_id": profile.id,
            "profile_status": "rejected",
        },
        callback,
    )


# ============================================================================
# Sub-3.2 — Admin rollback helper (T17)
# ============================================================================


async def admin_rollback_profile(
    db: AsyncSession,
    profile: "AdmissionProfile",
    reason: str,
    actor: Any,
) -> Tuple[Dict[str, Any], Optional[Callable[[], Awaitable[None]]]]:
    """T17 admin-rollback: any non-final state → draft (admin-only).

    Used by `POST /api/v2/admissions/{id}/admin-rollback`. Uses PR-3C
    Sub-3.5 `TRANSITION_PAIR_TO_EVENT` extension (11 pair entries) —
    `(<any_source>, "draft")` fires `ADMISSION_ROLLED_BACK` source-aware.

    PRE-CHECKS:
        1. `profile.status NOT IN ("enrolled", "withdrawn")` — terminal
           states cannot be rolled back per state machine (no `→ DRAFT`
           edges from those sources).
        2. `reason` mandatory, min 10 chars (caller already validated via
           schema; defensive re-check here).

    Returns:
        `(result_dict, post_commit_callback)` with `rolled_back_from`
        capture for audit response.
    """
    from . import admission_state_service as state_service

    rolled_back_from = profile.status

    if rolled_back_from in ("enrolled", "withdrawn"):
        raise BusinessRuleViolation(
            f"Hồ sơ ở trạng thái cuối ('{rolled_back_from}') không thể rollback"
        )
    if not reason or len(reason.strip()) < 10:
        raise BusinessRuleViolation(
            "Lý do rollback bắt buộc, tối thiểu 10 ký tự"
        )

    # W9-J.7.idem fix 2026-05-16: idempotent no-op khi đã ở 'draft'.
    # Trước: state machine raise "Invalid transition: draft → draft"
    # → 400 confusing UX ("not allowed"). Sau: 200 với
    # `already_at_target=true` cho FE phân biệt no-op vs actual rollback.
    if rolled_back_from == "draft":
        return (
            {
                "profile_id": profile.id,
                "status": "draft",
                "rolled_back_from": "draft",
                "already_at_target": True,
            },
            None,
        )

    _, callback = await state_service.transition(
        db, profile, "draft",
        actor=actor,
        reason=reason,
        source="admin_rollback",
        event_metadata={
            "rolled_back_from": rolled_back_from,
            "actor_id": getattr(actor, "id", None),
        },
    )

    return (
        {
            "profile_id": profile.id,
            "status": "draft",
            "rolled_back_from": rolled_back_from,
        },
        callback,
    )
