"""Phase 3 PR-3C Sub-2 — Choice-engine cascade tests.

Anchor tests for `evaluate_cascade()` + `resolve_effective_bonus_rule()`.
Non-tautological per memory `pattern-change-impact-audit`:
- T10 source-aware-style anchor: verify cascade-stop semantic (first admit
  → mark remaining as 'skip', NOT 'rejected' or 'pending')
- Q-P3-11 anchor: bonus_rule_snapshot written from effective resolution
  chain (override wins over default)

Follows test_phase3_pr3b_state_machine.py pattern — SimpleNamespace +
MagicMock + AsyncMock for state_service/dispatch.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.admission_choice_engine_service import (
    CascadeResult,
    evaluate_cascade,
    resolve_effective_bonus_rule,
    _evaluate_single_choice,
)


# ============================================================================
# Fixture helpers
# ============================================================================


def _make_path(
    *,
    bonus_rule_override=None,
    method_default_bonus_rule=None,
    min_gpa=None,
    allowed_subject_codes=("MATH", "PHYS", "CHEM"),
    criteria_code="STD",
):
    """Build AdmissionPath stand-in với criteria + method + subject_group."""
    method = SimpleNamespace(
        id=1,
        code="THPTQG",
        default_bonus_rule=method_default_bonus_rule,
    )
    criteria = SimpleNamespace(
        id=1,
        code=criteria_code,
        min_gpa=Decimal(str(min_gpa)) if min_gpa is not None else None,
        min_score=None,
        min_subject_score=None,
        subject_selection_mode="fixed",
        scoring_method="sum",
        required_subject_count=3,
    )
    # Fixture mirror of SubjectGroup → SubjectGroupSubject (mapping) →
    # Subject chain. Hotfix #267 ("SubjectGroup.subjects relation drift")
    # switched the engine from ``group.subjects`` to ``group.subject_mappings``
    # but this fixture file kept the old shape, so 5 tests in this file
    # silently returned ``rejected`` (engine read an empty allowed_subjects
    # list and fell through the scoring gate). 2026-05-14 fix: build the
    # mapping shape that ``_resolve_allowed_subjects`` actually walks.
    subject_mappings = [
        SimpleNamespace(subject=SimpleNamespace(code=c, name_vi=c))
        for c in allowed_subject_codes
    ]
    subject_group = SimpleNamespace(
        id=1, name="A00", subject_mappings=subject_mappings,
    )
    config = SimpleNamespace(
        id=1,
        admission_path_id=1,
        subject_group=subject_group,
    )
    path = SimpleNamespace(
        id=1,
        admission_method=method,
        criteria=criteria,
        bonus_rule_override=bonus_rule_override,
        path_subject_group_config=config,
    )
    return path, config


def _make_choice(
    *,
    choice_id: int,
    display_order: int,
    path,
    config,
    scores_dict=None,
):
    """Build AdmissionProfileChoice stand-in với eager-loaded relations + scores."""
    scores_dict = scores_dict or {}
    score_rows = []
    for code, value in scores_dict.items():
        subject = SimpleNamespace(code=code, name_vi=code)
        score_rows.append(SimpleNamespace(
            subject=subject,
            score=Decimal(str(value)),
            max_score_snapshot=Decimal("10.0"),
            weight_snapshot=Decimal("1.0"),
        ))
    return SimpleNamespace(
        id=choice_id,
        display_order=display_order,
        admission_path=path,
        path_subject_group_config=config,
        scores=score_rows,
        decision="pending",
        bonus_rule_snapshot=None,
        eligibility_check_result=None,
    )


def _make_profile(*, status="reviewing", gpa=None, choices=None):
    """Build AdmissionProfile stand-in."""
    return SimpleNamespace(
        id=42,
        lead_id=99,
        status=status,
        version=1,
        updated_at=None,
        gpa_overall=Decimal(str(gpa)) if gpa is not None else None,
        graduation_year=2024,
        uses_choice_engine=True,
        choices=choices or [],
    )


@pytest.fixture
def db_session():
    s = MagicMock(name="AsyncSession")
    s.flush = AsyncMock()
    return s


@pytest.fixture
def patched_state_and_dispatch():
    """Patch state_service.transition + dispatch_event."""
    with patch(
        "app.services.admission_state_service.transition",
        new=AsyncMock(return_value=(SimpleNamespace(), None)),
    ) as transition_mock, patch(
        "app.services.notification_dispatcher.dispatch_event",
        new=AsyncMock(return_value=([], None)),
    ) as dispatch_mock:
        yield transition_mock, dispatch_mock


# ============================================================================
# resolve_effective_bonus_rule — 3 cases
# ============================================================================


class TestResolveEffectiveBonusRule:
    def test_override_wins_over_method_default(self):
        """Q-P3-11 resolution chain: path.override takes precedence."""
        path, _ = _make_path(
            bonus_rule_override={"version": 2, "rule": "override"},
            method_default_bonus_rule={"version": 1, "rule": "default"},
        )
        result = resolve_effective_bonus_rule(path)
        assert result == {"version": 2, "rule": "override"}

    def test_fallback_to_method_default_when_override_null(self):
        """No path override → fallback to method.default_bonus_rule."""
        path, _ = _make_path(
            bonus_rule_override=None,
            method_default_bonus_rule={"version": 1, "rule": "default"},
        )
        result = resolve_effective_bonus_rule(path)
        assert result == {"version": 1, "rule": "default"}

    def test_both_null_returns_none(self):
        """No bonus rule configured anywhere → None (caller stores NULL)."""
        path, _ = _make_path(
            bonus_rule_override=None,
            method_default_bonus_rule=None,
        )
        result = resolve_effective_bonus_rule(path)
        assert result is None


# ============================================================================
# _evaluate_single_choice — gates + score
# ============================================================================


class TestEvaluateSingleChoice:
    def test_min_gpa_gate_fail_returns_rejected(self):
        """Profile GPA < criteria threshold → reject without scoring."""
        path, config = _make_path(min_gpa=7.0)
        choice = _make_choice(
            choice_id=1, display_order=1, path=path, config=config,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        profile = _make_profile(gpa=5.5)
        decision, score, reasons = _evaluate_single_choice(profile, choice)
        assert decision == "rejected"
        assert score is None  # Gate fail before scoring
        assert "BELOW_MIN_GPA" in reasons

    def test_passing_choice_returns_admitted(self):
        """All gates + scoring pass → admitted."""
        path, config = _make_path(min_gpa=6.0)
        choice = _make_choice(
            choice_id=1, display_order=1, path=path, config=config,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        profile = _make_profile(gpa=7.5)
        decision, score, reasons = _evaluate_single_choice(profile, choice)
        assert decision == "admitted"
        assert score is not None
        assert score.passed is True

    def test_missing_scores_returns_rejected(self):
        """Empty scores → no_valid_scores reject."""
        path, config = _make_path(min_gpa=6.0)
        choice = _make_choice(
            choice_id=1, display_order=1, path=path, config=config,
            scores_dict={},
        )
        profile = _make_profile(gpa=7.5)
        decision, _, reasons = _evaluate_single_choice(profile, choice)
        assert decision == "rejected"
        assert "NO_VALID_SCORES" in reasons


# ============================================================================
# evaluate_cascade — orchestration (anchor cascade-stop + snapshot)
# ============================================================================


class TestEvaluateCascade:
    @pytest.mark.asyncio
    async def test_first_admit_skips_remaining_choices(
        self, db_session, patched_state_and_dispatch,
    ):
        """⭐ Cascade-stop anchor: first admit → remaining marked 'skip'.
        Non-tautological — wrong semantic would mark them 'rejected' or
        leave 'pending'.
        """
        path, config = _make_path(min_gpa=6.0)
        nv1 = _make_choice(
            choice_id=1, display_order=1, path=path, config=config,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        nv2 = _make_choice(
            choice_id=2, display_order=2, path=path, config=config,
            scores_dict={"MATH": 9.5, "PHYS": 8.5, "CHEM": 9.0},
        )
        nv3 = _make_choice(
            choice_id=3, display_order=3, path=path, config=config,
            scores_dict={"MATH": 10.0, "PHYS": 9.5, "CHEM": 9.5},
        )
        profile = _make_profile(gpa=7.5, choices=[nv1, nv2, nv3])

        result, _ = await evaluate_cascade(db_session, profile)

        assert nv1.decision == "admitted"
        assert nv2.decision == "skip", (
            "After first admit, remaining choices MUST be 'skip', NOT "
            f"'{nv2.decision}'. Cascade-stop semantic broken."
        )
        assert nv3.decision == "skip"
        assert result.final_status == "admitted"
        assert result.admitted_choice_id == 1
        assert result.admitted_display_order == 1

    @pytest.mark.asyncio
    async def test_all_reject_results_in_rejected(
        self, db_session, patched_state_and_dispatch,
    ):
        """All gates fail → all rejected + profile final 'rejected'."""
        path, config = _make_path(min_gpa=9.5)  # Very high threshold
        nv1 = _make_choice(
            choice_id=1, display_order=1, path=path, config=config,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        nv2 = _make_choice(
            choice_id=2, display_order=2, path=path, config=config,
            scores_dict={"MATH": 9.5, "PHYS": 8.5, "CHEM": 9.0},
        )
        profile = _make_profile(gpa=7.5, choices=[nv1, nv2])

        result, _ = await evaluate_cascade(db_session, profile)

        assert nv1.decision == "rejected"
        assert nv2.decision == "rejected"
        assert result.final_status == "rejected"
        assert result.admitted_choice_id is None

    @pytest.mark.asyncio
    async def test_bonus_rule_snapshot_written_per_choice(
        self, db_session, patched_state_and_dispatch,
    ):
        """⭐ Q-P3-11 anchor: bonus_rule_snapshot captured tại T6 publish.
        Override wins over method default per resolution chain.
        """
        path1, config1 = _make_path(
            bonus_rule_override={"version": 2, "rule": "override"},
            method_default_bonus_rule={"version": 1, "rule": "default"},
            min_gpa=6.0,
        )
        path2, config2 = _make_path(
            bonus_rule_override=None,
            method_default_bonus_rule={"version": 1, "rule": "default"},
            min_gpa=6.0,
        )
        nv1 = _make_choice(
            choice_id=1, display_order=1, path=path1, config=config1,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        nv2 = _make_choice(
            choice_id=2, display_order=2, path=path2, config=config2,
            scores_dict={"MATH": 9.5, "PHYS": 8.5, "CHEM": 9.0},
        )
        profile = _make_profile(gpa=7.5, choices=[nv1, nv2])

        await evaluate_cascade(db_session, profile)

        # NV1: override wins
        assert nv1.bonus_rule_snapshot == {"version": 2, "rule": "override"}
        # NV2: skip (NV1 admitted) — bonus_rule_snapshot still written for NV2?
        # Per implementation: snapshot is written BEFORE evaluation per choice.
        # NV2 marked 'skip' BEFORE reaching snapshot step → stays None.
        # This is correct per design — skipped choices don't need historical snapshot.
        assert nv2.bonus_rule_snapshot is None
        assert nv2.decision == "skip"

    @pytest.mark.asyncio
    async def test_eligibility_check_result_recorded(
        self, db_session, patched_state_and_dispatch,
    ):
        """Audit trail anchor: eligibility_check_result JSONB written với
        decision + reason_codes + score summary."""
        path, config = _make_path(min_gpa=9.0)
        nv1 = _make_choice(
            choice_id=1, display_order=1, path=path, config=config,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        profile = _make_profile(gpa=5.0, choices=[nv1])  # GPA fail

        await evaluate_cascade(db_session, profile)

        assert nv1.eligibility_check_result is not None
        assert nv1.eligibility_check_result["decision"] == "rejected"
        assert "BELOW_MIN_GPA" in nv1.eligibility_check_result["reason_codes"]
        assert nv1.eligibility_check_result["score"] is None  # Gate fail no scoring

    @pytest.mark.asyncio
    async def test_state_transition_calls_chain(
        self, db_session, patched_state_and_dispatch,
    ):
        """State transition pattern: reviewing → result_published → final
        (state machine forbids reviewing → admitted direct per PR-3B map).
        """
        transition_mock, _ = patched_state_and_dispatch
        path, config = _make_path(min_gpa=6.0)
        nv1 = _make_choice(
            choice_id=1, display_order=1, path=path, config=config,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        profile = _make_profile(gpa=7.5, choices=[nv1])

        await evaluate_cascade(db_session, profile)

        # 2 transition calls: → result_published, then → admitted
        assert transition_mock.await_count == 2
        first_call_status = transition_mock.await_args_list[0].args[2]
        second_call_status = transition_mock.await_args_list[1].args[2]
        assert first_call_status == "result_published"
        assert second_call_status == "admitted"


# ============================================================================
# Cascade-stop count anchor
# ============================================================================


@pytest.mark.asyncio
async def test_cascade_per_choice_decisions_records_all(
    db_session, patched_state_and_dispatch,
):
    """CascadeResult.per_choice_decisions records EVERY choice (including
    skipped ones). Caller (audit) needs full trace per cascade run.
    """
    path, config = _make_path(min_gpa=6.0)
    choices = [
        _make_choice(
            choice_id=i, display_order=i, path=path, config=config,
            scores_dict={"MATH": 9.0, "PHYS": 8.0, "CHEM": 8.5},
        )
        for i in range(1, 4)
    ]
    profile = _make_profile(gpa=7.5, choices=choices)

    result, _ = await evaluate_cascade(db_session, profile)

    assert len(result.per_choice_decisions) == 3
    assert result.per_choice_decisions[0]["decision"] == "admitted"
    assert result.per_choice_decisions[1]["decision"] == "skip"
    assert result.per_choice_decisions[2]["decision"] == "skip"
