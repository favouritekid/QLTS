"""CR-P0 anchor test: priority bonus must affect admission decision,
not just decorate the snapshot columns.

Without this test, future refactors could silently revert to "snapshot
only" mode (compute the bonus, write the columns, but never feed it
into _evaluate_single_choice) — which is exactly the bug Q9 #07 CR-P0
identified in code review.

The test uses a fake calculate_score result so it can construct the
exact "raw fail / bonus rescue" scenario without needing a full DB
fixture: raw final_score = 6.5, min_score = 7.0 → fails. Add
priority_bonus = 2.75 → final_score = 9.25 → passes.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.admission_choice_engine_service import _evaluate_single_choice
from app.services.admission_scoring_service import (
    AdmissionScoreResult,
    DisqualificationReason,
    ProfileStatus,
)


pytestmark = pytest.mark.unit


def _make_choice_with_scoring(
    final_score: Decimal, min_score: Decimal, passed: bool
):
    """Build a stub choice + profile + monkeypatched calculate_score
    that returns a deterministic AdmissionScoreResult so the test can
    isolate the bonus-apply logic in _evaluate_single_choice."""
    criteria = SimpleNamespace(
        code="TEST",
        min_gpa=None,
        method="sum",
        min_score=min_score,
        min_subject_score=None,
        selection_mode="fixed",
        required_count=3,
    )

    # Q9 #07 Phase E.4 — _evaluate_single_choice gate 0 calls
    # derive_target_level_and_type(path) → reads path.academic_info.offering
    # .program.degree_level_ref.code + offering.offering_type_config.code.
    # Without this eager-loaded chain stub, gate 0 raises CONFIG_GAP_TARGET_LEVEL
    # và choice reject với code đó (silently regressed the bonus-flip behavior).
    program_stub = SimpleNamespace()
    program_stub.__dict__["degree_level_ref"] = SimpleNamespace(code="cao_dang")
    offering_stub = SimpleNamespace()
    offering_stub.__dict__["program"] = program_stub
    offering_stub.__dict__["offering_type_config"] = SimpleNamespace(code="chinh_quy")
    academic_info_stub = SimpleNamespace()
    academic_info_stub.__dict__["offering"] = offering_stub

    path = SimpleNamespace(criteria=criteria)
    path.__dict__["academic_info"] = academic_info_stub
    # Build scores so _collect_subject_scores returns something truthy;
    # the actual values don't matter because calculate_score is patched.
    score_row = SimpleNamespace(
        subject=SimpleNamespace(code="MATH"),
        score=Decimal("6.5"),
    )
    config = SimpleNamespace(
        subject_group=SimpleNamespace(
            subject_mappings=[
                SimpleNamespace(subject=SimpleNamespace(code="MATH")),
                SimpleNamespace(subject=SimpleNamespace(code="PHYS")),
                SimpleNamespace(subject=SimpleNamespace(code="CHEM")),
            ]
        ),
    )
    choice = SimpleNamespace(
        admission_path=path,
        scores=[score_row, score_row, score_row],
        path_subject_group_config=config,
    )
    # Q9 #07 Phase E.4 — profile needs cultural_education_level đủ pass
    # eligibility gate 0. CĐ chính quy yêu cầu THPT knowledge (TN_THPT hoặc
    # HOAN_THANH_THPT). Use graduated_thpt để không vướng vào gate 0.
    profile = SimpleNamespace(
        gpa_overall=Decimal("8.0"),
        graduation_year=None,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
    )

    score_result = AdmissionScoreResult(
        status=ProfileStatus.VALID,
        passed=passed,
        final_score=final_score,
        selected_subjects=["MATH", "PHYS", "CHEM"],
        subject_scores={"MATH": Decimal("6.5")},
        min_score_threshold=min_score,
        criteria_code="TEST",
        failure_reasons=(
            [f"Điểm {final_score} < điểm chuẩn {min_score}"]
            if not passed else []
        ),
        disqualification_codes=(
            [DisqualificationReason.BELOW_MIN_SCORE.value]
            if not passed else []
        ),
    )
    return profile, choice, score_result


# ---------------------------------------------------------------------------
# CR-P0 contract: priority bonus is added to final_score + flips passed
# ---------------------------------------------------------------------------


def test_priority_bonus_flips_decision_from_rejected_to_admitted(
    monkeypatch,
) -> None:
    """Raw 6.5 + min_score 7.0 → would reject. With bonus 2.75 →
    boosted 9.25 ≥ 7.0 → admit. This is THE test that protects against
    the bug found in code review (snapshot decorative, decision unchanged)."""
    profile, choice, fake_result = _make_choice_with_scoring(
        final_score=Decimal("6.5"),
        min_score=Decimal("7.0"),
        passed=False,
    )
    monkeypatch.setattr(
        "app.services.admission_choice_engine_service."
        "AdmissionScoringService.calculate_score",
        lambda **kwargs: fake_result,
    )

    decision, result, _ = _evaluate_single_choice(
        profile, choice, priority_bonus=Decimal("2.75"),
    )

    assert decision == "admitted", (
        "Priority bonus should flip the decision — without this fix the "
        "Q9 #07 feature is decorative (snapshot writes, decision unchanged)."
    )
    assert result.final_score == Decimal("9.25")
    assert result.passed is True


def test_priority_bonus_zero_keeps_raw_decision(monkeypatch) -> None:
    """When bonus is zero (legacy 315 profiles without backfill), engine
    falls back to raw-score decision — no spurious admits."""
    profile, choice, fake_result = _make_choice_with_scoring(
        final_score=Decimal("6.5"),
        min_score=Decimal("7.0"),
        passed=False,
    )
    monkeypatch.setattr(
        "app.services.admission_choice_engine_service."
        "AdmissionScoringService.calculate_score",
        lambda **kwargs: fake_result,
    )

    decision, result, _ = _evaluate_single_choice(
        profile, choice, priority_bonus=Decimal("0"),
    )

    assert decision == "rejected"
    assert result.final_score == Decimal("6.5")
    assert result.passed is False


def test_priority_bonus_still_below_min_keeps_rejected(monkeypatch) -> None:
    """Raw 4.0 + min 7.0 + bonus 1.0 → boosted 5.0 still < 7.0.
    Decision stays rejected; final_score updated to boosted value for
    audit transparency."""
    profile, choice, fake_result = _make_choice_with_scoring(
        final_score=Decimal("4.0"),
        min_score=Decimal("7.0"),
        passed=False,
    )
    monkeypatch.setattr(
        "app.services.admission_choice_engine_service."
        "AdmissionScoringService.calculate_score",
        lambda **kwargs: fake_result,
    )

    decision, result, _ = _evaluate_single_choice(
        profile, choice, priority_bonus=Decimal("1.0"),
    )

    assert decision == "rejected"
    assert result.final_score == Decimal("5.0")
    assert result.passed is False
    # BELOW_MIN_SCORE stays since boosted still fails
    assert DisqualificationReason.BELOW_MIN_SCORE.value in result.disqualification_codes


def test_priority_bonus_above_min_clears_disqualification_codes(
    monkeypatch,
) -> None:
    """When bonus rescues a fail, the BELOW_MIN_SCORE disqualification
    code + matching failure_reason are removed so the audit trail
    accurately shows 'raw fail + bonus rescue', not 'fail then admit'."""
    profile, choice, fake_result = _make_choice_with_scoring(
        final_score=Decimal("6.5"),
        min_score=Decimal("7.0"),
        passed=False,
    )
    monkeypatch.setattr(
        "app.services.admission_choice_engine_service."
        "AdmissionScoringService.calculate_score",
        lambda **kwargs: fake_result,
    )

    _, result, reason_codes = _evaluate_single_choice(
        profile, choice, priority_bonus=Decimal("1.0"),
    )

    assert (
        DisqualificationReason.BELOW_MIN_SCORE.value
        not in result.disqualification_codes
    )
    assert not any("điểm chuẩn" in r.lower() for r in result.failure_reasons)


def test_already_passing_with_bonus_increases_final_score(monkeypatch) -> None:
    """Candidate passes WITHOUT bonus but still has priority codes —
    bonus still gets added to final_score (audit transparency + ranking
    fairness in waitlist scenarios)."""
    profile, choice, fake_result = _make_choice_with_scoring(
        final_score=Decimal("8.0"),
        min_score=Decimal("7.0"),
        passed=True,
    )
    monkeypatch.setattr(
        "app.services.admission_choice_engine_service."
        "AdmissionScoringService.calculate_score",
        lambda **kwargs: fake_result,
    )

    decision, result, _ = _evaluate_single_choice(
        profile, choice, priority_bonus=Decimal("0.75"),
    )

    assert decision == "admitted"
    assert result.final_score == Decimal("8.75")
    assert result.passed is True


def test_invalid_status_bonus_not_applied(monkeypatch) -> None:
    """If raw scoring returned INVALID (missing data, gate fail),
    bonus is NOT applied — INVALID is a structural reject, not a
    score threshold issue."""
    profile, choice, _ = _make_choice_with_scoring(
        final_score=Decimal("6.5"),
        min_score=Decimal("7.0"),
        passed=False,
    )
    invalid_result = AdmissionScoreResult(
        status=ProfileStatus.INVALID,
        passed=False,
        final_score=None,  # INVALID never has a score
        selected_subjects=[],
        subject_scores={},
        min_score_threshold=None,
        criteria_code="TEST",
    )
    monkeypatch.setattr(
        "app.services.admission_choice_engine_service."
        "AdmissionScoringService.calculate_score",
        lambda **kwargs: invalid_result,
    )

    decision, result, _ = _evaluate_single_choice(
        profile, choice, priority_bonus=Decimal("2.75"),
    )

    assert decision == "rejected"
    assert result.final_score is None
    assert result.passed is False
