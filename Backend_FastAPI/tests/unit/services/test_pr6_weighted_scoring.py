"""PR6 Step 2 — weighted scoring formula tests.

Guards the business decisions chốt 2026-04-19:
    - per-subject, raw coefficients
    - default 1.0 → no-op
    - missing key → treated as 1.0 (backward-compat)
    - sum / average methods IGNORE weights (snapshot immutability)
    - no-retroactive: snapshot without weights keeps plain sum
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.admission_scoring_service import (
    AdmissionScoringService,
    ScoringMethod,
)


def _mk_criteria(scoring_method: str = "weighted", **overrides) -> SimpleNamespace:
    defaults = dict(
        code="C1",
        subject_selection_mode="fixed",
        scoring_method=scoring_method,
        required_subject_count=3,
        min_score=None,
        min_subject_score=None,
        min_gpa=None,
        max_possible_score=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestCalculateFinalScoreWeighted:
    """Unit-level: pure math on _calculate_final_score."""

    def test_weighted_sum_honours_coefficients(self):
        """Toán x2, Lý x1, Hóa x1 on (8, 7, 9): canonical example from
        the PR6 spec session — result must be 32."""
        total = AdmissionScoringService._calculate_final_score(
            scores=[Decimal("8"), Decimal("7"), Decimal("9")],
            method=ScoringMethod.WEIGHTED.value,
            selected_codes=["math", "physics", "chemistry"],
            subject_weights={"math": 2.0, "physics": 1.0, "chemistry": 1.0},
        )
        assert total == Decimal("32")  # 16 + 7 + 9

    def test_weighted_all_one_matches_plain_sum(self):
        """Default 1.0 everywhere → weighted ≡ sum (no-op guarantee)."""
        scores = [Decimal("8"), Decimal("7"), Decimal("9")]
        weighted = AdmissionScoringService._calculate_final_score(
            scores=scores,
            method=ScoringMethod.WEIGHTED.value,
            selected_codes=["math", "physics", "chemistry"],
            subject_weights={"math": 1.0, "physics": 1.0, "chemistry": 1.0},
        )
        plain = AdmissionScoringService._calculate_final_score(
            scores=scores,
            method=ScoringMethod.SUM.value,
        )
        assert weighted == plain == Decimal("24")

    def test_missing_key_falls_back_to_one(self):
        """A subject not present in the weights map uses 1.0. Matches
        the DB default and protects pre-migration snapshots that missed
        a code."""
        total = AdmissionScoringService._calculate_final_score(
            scores=[Decimal("8"), Decimal("7"), Decimal("9")],
            method=ScoringMethod.WEIGHTED.value,
            selected_codes=["math", "physics", "chemistry"],
            subject_weights={"math": 2.0},  # physics / chemistry missing
        )
        # 8*2 + 7*1 + 9*1 = 32
        assert total == Decimal("32")

    def test_weighted_without_weights_falls_back_to_sum(self):
        """No-retroactive guarantee: snapshot may carry scoring_method
        'weighted' but no weights → must stay plain sum, not crash or
        silently weight scores to zero."""
        total = AdmissionScoringService._calculate_final_score(
            scores=[Decimal("8"), Decimal("7"), Decimal("9")],
            method=ScoringMethod.WEIGHTED.value,
            selected_codes=["math", "physics", "chemistry"],
            subject_weights=None,
        )
        assert total == Decimal("24")

    def test_sum_method_ignores_weights(self):
        """Switching scoring_method back to 'sum' must not secretly apply
        weights hiding in the snapshot. Snapshot-level immutability."""
        total = AdmissionScoringService._calculate_final_score(
            scores=[Decimal("8"), Decimal("7"), Decimal("9")],
            method=ScoringMethod.SUM.value,
            selected_codes=["math", "physics", "chemistry"],
            subject_weights={"math": 2.0, "physics": 1.0, "chemistry": 1.0},
        )
        assert total == Decimal("24")  # plain sum, not 32

    def test_average_method_ignores_weights(self):
        total = AdmissionScoringService._calculate_final_score(
            scores=[Decimal("8"), Decimal("7"), Decimal("9")],
            method=ScoringMethod.AVERAGE.value,
            selected_codes=["math", "physics", "chemistry"],
            subject_weights={"math": 2.0, "physics": 1.0, "chemistry": 1.0},
        )
        assert total == Decimal("24") / Decimal("3")

    def test_empty_scores_stays_zero(self):
        total = AdmissionScoringService._calculate_final_score(
            scores=[],
            method=ScoringMethod.WEIGHTED.value,
            selected_codes=[],
            subject_weights={"math": 2.0},
        )
        assert total == Decimal("0")


class TestCalculateScoreWithWeights:
    """Integration-shape: calculate_score() end-to-end with weights."""

    def test_calculate_score_weighted_happy_path(self):
        criteria = _mk_criteria(scoring_method="weighted")
        subject_scores = {
            "math": Decimal("8"),
            "physics": Decimal("7"),
            "chemistry": Decimal("9"),
        }
        result = AdmissionScoringService.calculate_score(
            criteria=criteria,
            subject_scores=subject_scores,
            allowed_subjects=["math", "physics", "chemistry"],
            subject_weights={"math": 2.0, "physics": 1.0, "chemistry": 1.0},
        )
        assert result.final_score == Decimal("32")
        assert result.scoring_method == "weighted"

    def test_calculate_score_weighted_backward_compat(self):
        """No subject_weights passed → weighted method falls back to
        plain sum. Same behavior as pre-PR6 code for old snapshots."""
        criteria = _mk_criteria(scoring_method="weighted")
        result = AdmissionScoringService.calculate_score(
            criteria=criteria,
            subject_scores={
                "math": Decimal("8"),
                "physics": Decimal("7"),
                "chemistry": Decimal("9"),
            },
            allowed_subjects=["math", "physics", "chemistry"],
        )
        assert result.final_score == Decimal("24")

    def test_calculate_score_sum_ignores_passed_weights(self):
        """Defense in depth: even if caller erroneously passes weights
        to a sum-method profile, the sum method must ignore them."""
        criteria = _mk_criteria(scoring_method="sum")
        result = AdmissionScoringService.calculate_score(
            criteria=criteria,
            subject_scores={
                "math": Decimal("8"),
                "physics": Decimal("7"),
                "chemistry": Decimal("9"),
            },
            allowed_subjects=["math", "physics", "chemistry"],
            subject_weights={"math": 2.0},
        )
        assert result.final_score == Decimal("24")
