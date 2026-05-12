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

import structlog

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.events import SystemEvents
from .admission_scoring_service import (
    AdmissionScoringService,
    AdmissionScoreResult,
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
) -> Tuple[str, Optional[AdmissionScoreResult], List[str]]:
    """Evaluate ONE choice in isolation — gates first, then scoring.

    Returns:
        (decision, score_result_or_none, reason_codes)
        decision ∈ {'admitted', 'rejected'} — waitlist deferred Q-P3-05

    Side effects: NONE — pure decision computation. Caller writes
    `choice.decision` + `choice.eligibility_check_result` based on returned
    decision + reason codes.
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
    """
    config = getattr(choice, "path_subject_group_config", None)
    if config is None:
        return []
    group = getattr(config, "subject_group", None)
    if group is None:
        return []
    subjects = getattr(group, "subjects", None) or []
    codes: List[str] = []
    for s in subjects:
        code = getattr(s, "code", None)
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

        # Per-choice decision (gates + scoring)
        decision, score_result, reason_codes = _evaluate_single_choice(
            profile, choice,
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
