"""Phase 3 PR-3C Sub-3.2 — Router-facing service helpers.

Anchor tests cho 3 thin wrappers trong `admission_choice_engine_service`:
- `publish_result(db, profile)` — T6 entry point + pre-checks
- `promote_waitlisted_choice(db, choice, profile, actor)` — T10
- `admin_rollback_profile(db, profile, reason, actor)` — T17

Non-tautological per memory `pattern-change-impact-audit`:
- Pre-check tests assert SPECIFIC BusinessRuleViolation message hints
- T17 anchor verifies pair-lookup fires ROLLED_BACK (not generic event)
- T10 anchor verifies WAITLIST_PROMOTED event (not generic ADMITTED)
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.admission_choice_engine_service import (
    admin_rollback_profile,
    promote_waitlisted_choice,
    publish_result,
)
from app.utils.exceptions import BusinessRuleViolation


# ============================================================================
# Fixtures
# ============================================================================


def _make_profile(*, status="reviewing", uses_choice_engine=True, choices=None):
    return SimpleNamespace(
        id=42,
        lead_id=99,
        status=status,
        version=1,
        updated_at=None,
        uses_choice_engine=uses_choice_engine,
        gpa_overall=Decimal("7.5"),
        graduation_year=2024,
        choices=choices or [],
    )


def _make_actor(user_id=7):
    return SimpleNamespace(id=user_id, full_name="Test Admin", username="admin")


def _make_choice(decision="waitlisted", profile_id=42):
    return SimpleNamespace(
        id=5,
        admission_profile_id=profile_id,
        display_order=2,
        decision=decision,
        bonus_rule_snapshot=None,
        eligibility_check_result=None,
    )


@pytest.fixture
def db_session():
    s = MagicMock(name="AsyncSession")
    s.flush = AsyncMock()
    return s


@pytest.fixture
def patched_evaluate_cascade():
    """Patch evaluate_cascade so publish_result tests don't exercise full loop."""
    fake_result = SimpleNamespace(
        profile_id=42,
        final_status="admitted",
        admitted_choice_id=1,
        admitted_display_order=1,
        per_choice_decisions=[],
    )
    with patch(
        "app.services.admission_choice_engine_service.evaluate_cascade",
        new=AsyncMock(return_value=(fake_result, None)),
    ) as mock:
        yield mock


@pytest.fixture
def patched_state_transition():
    """Patch state_service.transition globally to avoid touching real DB."""
    with patch(
        "app.services.admission_state_service.transition",
        new=AsyncMock(return_value=(SimpleNamespace(), None)),
    ) as mock:
        yield mock


# ============================================================================
# publish_result — T6 entry point
# ============================================================================


class TestPublishResult:
    @pytest.mark.asyncio
    async def test_uses_choice_engine_false_blocked(
        self, db_session, patched_evaluate_cascade,
    ):
        """Pre-check 1: profile.uses_choice_engine=False → reject before cascade."""
        profile = _make_profile(uses_choice_engine=False, status="reviewing")
        with pytest.raises(BusinessRuleViolation) as exc:
            await publish_result(db_session, profile)
        assert "choice engine" in str(exc.value).lower()
        patched_evaluate_cascade.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_status_blocked(
        self, db_session, patched_evaluate_cascade,
    ):
        """Pre-check 2: profile.status != 'reviewing' → reject."""
        profile = _make_profile(status="draft", uses_choice_engine=True)
        with pytest.raises(BusinessRuleViolation) as exc:
            await publish_result(db_session, profile)
        assert "reviewing" in str(exc.value).lower()
        patched_evaluate_cascade.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_calls_cascade(
        self, db_session, patched_evaluate_cascade,
    ):
        """Pre-checks pass → evaluate_cascade called with profile."""
        profile = _make_profile(status="reviewing", uses_choice_engine=True)
        result, callback = await publish_result(db_session, profile)
        patched_evaluate_cascade.assert_awaited_once_with(db_session, profile)
        assert result.profile_id == 42


# ============================================================================
# promote_waitlisted_choice — T10
# ============================================================================


class TestPromoteWaitlistedChoice:
    @pytest.mark.asyncio
    async def test_choice_not_waitlisted_blocked(
        self, db_session, patched_state_transition,
    ):
        """Pre-check 1: choice.decision != 'waitlisted' → reject."""
        choice = _make_choice(decision="admitted")
        profile = _make_profile(status="waitlisted")
        actor = _make_actor()
        with pytest.raises(BusinessRuleViolation) as exc:
            await promote_waitlisted_choice(db_session, choice, profile, actor)
        assert "waitlisted" in str(exc.value).lower()
        patched_state_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_profile_not_waitlisted_blocked(
        self, db_session, patched_state_transition,
    ):
        """Pre-check 2: profile.status != 'waitlisted' → reject."""
        choice = _make_choice(decision="waitlisted")
        profile = _make_profile(status="admitted")  # Wrong state
        actor = _make_actor()
        with pytest.raises(BusinessRuleViolation):
            await promote_waitlisted_choice(db_session, choice, profile, actor)
        patched_state_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_calls_transition_with_pair_aware_metadata(
        self, db_session, patched_state_transition,
    ):
        """⭐ T10 anchor: transition() called với new_status='admitted' +
        actor source='waitlist_promote'. State service PAIR-first lookup
        fires WAITLIST_PROMOTED (verified Sub-2 anchor test elsewhere).
        Here we verify wrapper passes correct args downstream.
        """
        choice = _make_choice(decision="waitlisted")
        profile = _make_profile(status="waitlisted")
        actor = _make_actor()

        result, callback = await promote_waitlisted_choice(
            db_session, choice, profile, actor,
        )

        assert choice.decision == "admitted"  # Choice updated FIRST
        assert result["profile_id"] == 42
        assert result["choice_id"] == 5
        assert result["decision"] == "admitted"
        assert result["profile_status"] == "admitted"

        # Verify transition() args reflect source-aware promote intent
        patched_state_transition.assert_awaited_once()
        call_args = patched_state_transition.await_args
        assert call_args.args[2] == "admitted"  # new_status arg
        assert call_args.kwargs["source"] == "waitlist_promote"
        assert call_args.kwargs["event_metadata"]["promoted_from_waitlist"] is True


# ============================================================================
# admin_rollback_profile — T17
# ============================================================================


class TestAdminRollbackProfile:
    @pytest.mark.asyncio
    async def test_enrolled_final_state_blocked(
        self, db_session, patched_state_transition,
    ):
        """Terminal state ENROLLED không thể rollback."""
        profile = _make_profile(status="enrolled")
        actor = _make_actor()
        with pytest.raises(BusinessRuleViolation) as exc:
            await admin_rollback_profile(
                db_session, profile, "Valid 10+ char reason", actor,
            )
        assert "enrolled" in str(exc.value).lower() or "cuối" in str(exc.value).lower()
        patched_state_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_withdrawn_final_state_blocked(
        self, db_session, patched_state_transition,
    ):
        """Terminal state WITHDRAWN không thể rollback."""
        profile = _make_profile(status="withdrawn")
        actor = _make_actor()
        with pytest.raises(BusinessRuleViolation):
            await admin_rollback_profile(
                db_session, profile, "Valid 10+ char reason", actor,
            )
        patched_state_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_reason_blocked(
        self, db_session, patched_state_transition,
    ):
        """Reason < 10 chars → reject (defensive double-check; schema also enforces)."""
        profile = _make_profile(status="admitted")
        actor = _make_actor()
        with pytest.raises(BusinessRuleViolation) as exc:
            await admin_rollback_profile(db_session, profile, "short", actor)
        assert "10" in str(exc.value) or "lý do" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_empty_reason_blocked(
        self, db_session, patched_state_transition,
    ):
        """Empty reason → reject."""
        profile = _make_profile(status="admitted")
        actor = _make_actor()
        with pytest.raises(BusinessRuleViolation):
            await admin_rollback_profile(db_session, profile, "", actor)

    @pytest.mark.asyncio
    async def test_happy_path_captures_rolled_back_from(
        self, db_session, patched_state_transition,
    ):
        """⭐ T17 anchor: response captures pre-rollback status, transition()
        called với new_status='draft' + source='admin_rollback' + reason.
        PAIR map fires ADMISSION_ROLLED_BACK (verified Sub-3.5 anchor).
        """
        profile = _make_profile(status="admitted")
        actor = _make_actor()
        reason = "Hồ sơ admit nhầm, candidate withdraw qua CCCD verify"

        result, callback = await admin_rollback_profile(
            db_session, profile, reason, actor,
        )

        assert result["profile_id"] == 42
        assert result["status"] == "draft"
        assert result["rolled_back_from"] == "admitted"

        patched_state_transition.assert_awaited_once()
        call_args = patched_state_transition.await_args
        assert call_args.args[2] == "draft"  # new_status
        assert call_args.kwargs["reason"] == reason
        assert call_args.kwargs["source"] == "admin_rollback"
        assert call_args.kwargs["event_metadata"]["rolled_back_from"] == "admitted"

    @pytest.mark.asyncio
    async def test_rollback_from_each_non_final_source_state(
        self, db_session, patched_state_transition,
    ):
        """T17 parametrized anchor: each of 11 non-final source states
        passes pre-checks. Verifies wrapper KHÔNG hardcode source state.
        State machine ALLOWED_TRANSITIONS extension handles edges.
        """
        non_final_sources = [
            "submitted", "reviewing", "revision_requested", "resubmitted",
            "result_published", "admitted", "waitlisted", "rejected",
            "approved", "overridden", "confirmed",
        ]
        actor = _make_actor()

        for source_state in non_final_sources:
            patched_state_transition.reset_mock()
            profile = _make_profile(status=source_state)
            result, _ = await admin_rollback_profile(
                db_session, profile,
                "Valid rollback reason for parametric test",
                actor,
            )
            assert result["rolled_back_from"] == source_state, (
                f"Failed source state: {source_state}"
            )
            assert patched_state_transition.await_count == 1
