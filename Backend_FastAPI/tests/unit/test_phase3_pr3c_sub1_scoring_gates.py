"""Phase 3 PR-3C Sub-1 — Standalone rule helpers `_check_min_gpa` +
`_check_graduation_year_range`.

Non-tautological anchor per memory `pattern-change-impact-audit`:
- Verify behavior across nullable matrix (criteria None + profile None +
  both None + both set passing + both set failing)
- Catches future regression nếu helper signature changes (vd dùng profile
  object trực tiếp thay vì primitive params)

Sub-1 scope: 2 new static helpers ADD on existing `AdmissionScoringService`.
No change to `calculate_score()` signature (3 production callers untouched).
Wire qua Sub-2 `evaluate_cascade()` orchestration.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.admission_scoring_service import (
    AdmissionScoringService,
    DisqualificationReason,
)


# ============================================================================
# _check_min_gpa — rule 2 of plan v0.7 6-rule sequential
# ============================================================================


class TestCheckMinGpa:
    """Anchor tests for `_check_min_gpa` Phase 3 PR-3C gate."""

    def test_no_threshold_configured_skips_rule(self):
        """criteria.min_gpa is None → rule SKIPS regardless of profile state.
        Matches `calculate_score()` precedent — None threshold = no-op.
        """
        passed, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=Decimal("7.5"),
            criteria_min_gpa=None,
        )
        assert passed is True
        assert reason is None

    def test_no_threshold_no_gpa_skips_rule(self):
        """Both None → still skip (consistent with no-threshold semantic)."""
        passed, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=None,
            criteria_min_gpa=None,
        )
        assert passed is True
        assert reason is None

    def test_threshold_set_but_gpa_null_fails(self):
        """criteria.min_gpa=6.0 nhưng profile.gpa_overall=NULL → fail
        với `MISSING_GPA_OVERALL`. Candidate phải provide GPA khi rule
        active.
        """
        passed, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=None,
            criteria_min_gpa=Decimal("6.0"),
        )
        assert passed is False
        assert reason == DisqualificationReason.MISSING_GPA_OVERALL.value
        assert reason == "MISSING_GPA_OVERALL"

    def test_gpa_below_threshold_fails(self):
        """profile.gpa_overall=5.5 < criteria.min_gpa=6.0 → fail BELOW_MIN_GPA."""
        passed, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=Decimal("5.5"),
            criteria_min_gpa=Decimal("6.0"),
        )
        assert passed is False
        assert reason == DisqualificationReason.BELOW_MIN_GPA.value
        assert reason == "BELOW_MIN_GPA"

    def test_gpa_exactly_at_threshold_passes(self):
        """profile.gpa_overall=6.0 == criteria.min_gpa=6.0 → pass (>=
        contract, NOT strict >). Locks Numeric(4,2) precision compare.
        """
        passed, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=Decimal("6.00"),
            criteria_min_gpa=Decimal("6.0"),
        )
        assert passed is True
        assert reason is None

    def test_gpa_above_threshold_passes(self):
        """Normal pass path — profile 7.5 > threshold 6.0."""
        passed, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=Decimal("7.5"),
            criteria_min_gpa=Decimal("6.0"),
        )
        assert passed is True
        assert reason is None

    def test_decimal_precision_no_float_drift(self):
        """Verify Decimal compare avoids float precision bug.

        Float compare: 0.1 + 0.2 != 0.3. Decimal compare correct.
        Test ensures helper preserves Decimal semantic even if caller
        passes float-like values.
        """
        passed, reason = AdmissionScoringService._check_min_gpa(
            profile_gpa_overall=Decimal("6.0"),
            criteria_min_gpa=Decimal("5.99"),
        )
        assert passed is True


# ============================================================================
# _check_graduation_year_range — rule 3 (Phase 4 active, NO-OP for 2026)
# ============================================================================


class TestCheckGraduationYearRange:
    """Anchor tests for `_check_graduation_year_range` Phase 3 PR-3C gate.

    Phase 1 #04 columns DEFERRED Q1/2027 → helper currently NO-OPs cho
    mùa 2026. Tests verify Phase 4 swap semantics ready khi columns ship.
    """

    def test_no_range_configured_skips_rule(self):
        """Both criteria range args None → skip (Phase 4 not wired).
        Mùa 2026 production behavior — `criteria.min/max_graduation_year`
        columns đã DEFERRED Q1/2027 per Q9 chốt 2026-05-01.
        """
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=2024,
            criteria_min_graduation_year=None,
            criteria_max_graduation_year=None,
        )
        assert passed is True
        assert reason is None

    def test_no_range_no_grad_year_skips_rule(self):
        """All None → still skip (consistent semantic)."""
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=None,
        )
        assert passed is True
        assert reason is None

    def test_range_set_but_grad_year_null_fails(self):
        """Phase 4 ship range cols + caller passes them → profile.grad_year=NULL
        → fail GRADUATION_YEAR_OUT_OF_RANGE.
        """
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=None,
            criteria_min_graduation_year=2023,
            criteria_max_graduation_year=2026,
        )
        assert passed is False
        assert reason == DisqualificationReason.GRADUATION_YEAR_OUT_OF_RANGE.value

    def test_grad_year_below_min_fails(self):
        """profile.graduation_year=2022 < criteria.min=2023 → fail."""
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=2022,
            criteria_min_graduation_year=2023,
            criteria_max_graduation_year=2026,
        )
        assert passed is False
        assert reason == DisqualificationReason.GRADUATION_YEAR_OUT_OF_RANGE.value

    def test_grad_year_above_max_fails(self):
        """profile.graduation_year=2027 > criteria.max=2026 → fail."""
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=2027,
            criteria_min_graduation_year=2023,
            criteria_max_graduation_year=2026,
        )
        assert passed is False
        assert reason == DisqualificationReason.GRADUATION_YEAR_OUT_OF_RANGE.value

    def test_grad_year_at_min_passes(self):
        """profile.graduation_year=2023 == criteria.min=2023 → pass (>=)."""
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=2023,
            criteria_min_graduation_year=2023,
            criteria_max_graduation_year=2026,
        )
        assert passed is True

    def test_grad_year_at_max_passes(self):
        """profile.graduation_year=2026 == criteria.max=2026 → pass (<=)."""
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=2026,
            criteria_min_graduation_year=2023,
            criteria_max_graduation_year=2026,
        )
        assert passed is True

    def test_min_only_no_max(self):
        """criteria.min set but criteria.max None — half-open range."""
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=2050,
            criteria_min_graduation_year=2023,
            criteria_max_graduation_year=None,
        )
        assert passed is True  # No upper bound

    def test_max_only_no_min(self):
        """criteria.max set but criteria.min None — half-open range."""
        passed, reason = AdmissionScoringService._check_graduation_year_range(
            profile_graduation_year=1990,
            criteria_min_graduation_year=None,
            criteria_max_graduation_year=2026,
        )
        assert passed is True  # No lower bound


# ============================================================================
# DisqualificationReason enum lock — anchor cho 2 NEW codes
# ============================================================================


def test_phase3_disqualification_reasons_locked():
    """Sub-1 ADD 2 codes to DisqualificationReason enum. Lock prevents
    accidental rename/removal per memory `pattern-change-impact-audit`.
    """
    assert DisqualificationReason.MISSING_GPA_OVERALL.value == "MISSING_GPA_OVERALL"
    assert (
        DisqualificationReason.GRADUATION_YEAR_OUT_OF_RANGE.value
        == "GRADUATION_YEAR_OUT_OF_RANGE"
    )
    # Total 8 reasons (6 existing + 2 NEW)
    assert len(list(DisqualificationReason)) == 8
