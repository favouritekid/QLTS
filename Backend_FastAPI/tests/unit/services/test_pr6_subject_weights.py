"""PR6 Step 1 — backend contract tests for per-subject weights.

Scope of this file:
    - _serialize_subject_groups() — emits weights parallel field with the
      right shape; default 1.0 for untouched rows; float serialization.
    - AdmissionScoringService.generate_snapshot() — freezes subject_weights
      into the snapshot body AND into the rule hash (so a weight edit
      counts as a rule change, not a silent drift).

Scope this file does NOT cover:
    - The scoring formula itself (Step 2 — extend _calculate_final_score
      to use weights). Contract tests land here; math tests land next PR.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.admission_service import _serialize_subject_groups
from app.services.admission_scoring_service import AdmissionScoringService


# ---------------------------------------------------------------------------
# Fixture helpers — lightweight mock graph, no DB
# ---------------------------------------------------------------------------


def _mk_subject(code: str) -> SimpleNamespace:
    return SimpleNamespace(code=code)


def _mk_mapping(code: str, weight: Decimal) -> SimpleNamespace:
    return SimpleNamespace(subject=_mk_subject(code), weight=weight)


def _mk_group(code: str, name: str, subjects_and_weights: list[tuple[str, Decimal]]):
    group = SimpleNamespace(
        code=code,
        name=name,
        subject_mappings=[
            _mk_mapping(code, weight) for code, weight in subjects_and_weights
        ],
    )
    return group


def _mk_admission_path(groups: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        criteria=SimpleNamespace(
            subject_group_mappings=[
                SimpleNamespace(subject_group=g) for g in groups
            ]
        ),
    )


# ---------------------------------------------------------------------------
# _serialize_subject_groups
# ---------------------------------------------------------------------------


class TestSerializeSubjectGroups:
    def test_emits_weights_parallel_field_with_defaults(self):
        """Every row backfilled to 1.0 by the migration → emit plain sum
        shape (weights present and all 1.0, behavior unchanged)."""
        path = _mk_admission_path([
            _mk_group("A00", "Toán - Lý - Hóa", [
                ("math", Decimal("1.0")),
                ("physics", Decimal("1.0")),
                ("chemistry", Decimal("1.0")),
            ]),
        ])

        [group] = _serialize_subject_groups(path)

        assert group["code"] == "A00"
        assert group["name"] == "Toán - Lý - Hóa"
        # Backward-compat: flat list still present for existing clients.
        assert group["subjects"] == ["math", "physics", "chemistry"]
        # NEW: parallel weights dict.
        assert group["weights"] == {
            "math": 1.0,
            "physics": 1.0,
            "chemistry": 1.0,
        }

    def test_emits_raw_coefficients_when_configured(self):
        """Weighted config: Toán x2, Lý x1, Hóa x1 → raw numbers, no
        normalization (per PR6 spec decision)."""
        path = _mk_admission_path([
            _mk_group("A00", "Toán - Lý - Hóa", [
                ("math", Decimal("2.0")),
                ("physics", Decimal("1.0")),
                ("chemistry", Decimal("1.0")),
            ]),
        ])

        [group] = _serialize_subject_groups(path)

        assert group["weights"] == {
            "math": 2.0,
            "physics": 1.0,
            "chemistry": 1.0,
        }

    def test_weights_are_floats_not_decimals(self):
        """JSONB snapshot must be plain JSON — Decimal would not be
        serializable. Guard the conversion."""
        path = _mk_admission_path([
            _mk_group("D01", "Toán - Văn - Anh", [
                ("math", Decimal("1.5")),
                ("literature", Decimal("1.0")),
                ("english", Decimal("2.0")),
            ]),
        ])

        [group] = _serialize_subject_groups(path)

        for value in group["weights"].values():
            assert isinstance(value, float), f"expected float, got {type(value)}"

    def test_empty_criteria_returns_empty_list(self):
        """No regression: the pre-existing None-guard still works."""
        path = SimpleNamespace(id=1, criteria=None)
        assert _serialize_subject_groups(path) == []


# ---------------------------------------------------------------------------
# AdmissionScoringService.generate_snapshot()
# ---------------------------------------------------------------------------


def _mk_criteria(**overrides) -> SimpleNamespace:
    defaults = dict(
        code="C1",
        name="Test Criteria",
        method=SimpleNamespace(code="hoc_ba"),
        required_subject_count=3,
        subject_selection_mode="fixed",
        scoring_method="sum",
        min_score=Decimal("18.0"),
        min_gpa=Decimal("6.5"),
        min_subject_score=Decimal("1.0"),
        max_possible_score=Decimal("30.0"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestGenerateSnapshotWeights:
    def test_snapshot_freezes_subject_weights(self):
        """Snapshot body carries subject_weights taken from the group at
        application time. That's how the no-retroactive-backfill
        guarantee is enforced: later edits to SubjectGroupSubject.weight
        don't mutate this profile's already-committed snapshot."""
        group = _mk_group("A00", "Toán - Lý - Hóa", [
            ("math", Decimal("2.0")),
            ("physics", Decimal("1.0")),
            ("chemistry", Decimal("1.0")),
        ])
        criteria = _mk_criteria()

        snapshot = AdmissionScoringService.generate_snapshot(
            criteria=criteria,
            subject_group=group,
            allowed_subjects=["math", "physics", "chemistry"],
            input_scores={
                "math": Decimal("8.0"),
                "physics": Decimal("7.0"),
                "chemistry": Decimal("9.0"),
            },
        )

        assert snapshot["subject_weights"] == {
            "math": 2.0,
            "physics": 1.0,
            "chemistry": 1.0,
        }

    def test_snapshot_without_group_gets_empty_weights(self):
        """Paths with no resolved subject_group fall through to empty
        weights. Scoring logic (Step 2) treats missing keys as 1.0."""
        snapshot = AdmissionScoringService.generate_snapshot(
            criteria=_mk_criteria(),
            subject_group=None,
            allowed_subjects=[],
            input_scores={},
        )
        assert snapshot["subject_weights"] == {}

    def test_rule_hash_changes_when_weights_change(self):
        """A weight edit must be treated as a rule change so audit /
        change-detection downstream can react. Uses the same criteria +
        input for both runs — only the group weights differ."""
        criteria = _mk_criteria()
        common = dict(
            criteria=criteria,
            allowed_subjects=["math", "physics", "chemistry"],
            input_scores={
                "math": Decimal("8.0"),
                "physics": Decimal("7.0"),
                "chemistry": Decimal("9.0"),
            },
        )

        plain = AdmissionScoringService.generate_snapshot(
            subject_group=_mk_group("A00", "n", [
                ("math", Decimal("1.0")),
                ("physics", Decimal("1.0")),
                ("chemistry", Decimal("1.0")),
            ]),
            **common,
        )
        weighted = AdmissionScoringService.generate_snapshot(
            subject_group=_mk_group("A00", "n", [
                ("math", Decimal("2.0")),
                ("physics", Decimal("1.0")),
                ("chemistry", Decimal("1.0")),
            ]),
            **common,
        )

        assert plain["__rule_hash__"] != weighted["__rule_hash__"], (
            "Changing subject weights must bump the rule hash — otherwise "
            "audit tooling will silently miss the change."
        )
