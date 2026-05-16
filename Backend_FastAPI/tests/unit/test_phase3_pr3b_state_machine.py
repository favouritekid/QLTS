"""Phase 3 PR-3B Sub-4 — 22 anchor tests for state machine `transition()`.

17 happy-path transitions (T1-T17 minus T2/T4 no-dispatch, plus legacy T7
approved + T15/T16 withdraw chain) + 5 negative cases per plan v0.7
Q-P3-08.

Non-tautological per memory `pattern-change-impact-audit`: each test
loads real ``state_service.transition()`` + mocks dispatch_event/audit so
contract failure trips immediately (e.g. if pair-lookup gets reverted in
admission_state_service.py, T10 anchor will catch the wrong event).

Follows existing `test_admission_state_service.py` pattern — SimpleNamespace
profile stand-in + MagicMock db_session + AsyncMock for dispatch/audit.
NO real DB (fast ~1s for 22 tests).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.events import SystemEvents
from app.services import admission_state_service as state_service
from app.utils.exceptions import BusinessRuleViolation


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _profile(status: str, profile_id: int = 1, lead_id: int = 99):
    """SimpleNamespace stand-in matching AdmissionProfile fields used by
    transition() body."""
    return SimpleNamespace(
        id=profile_id,
        lead_id=lead_id,
        status=status,
        version=1,
        updated_at=None,
    )


def _actor(user_id: int = 7, role: str = "manager"):
    return SimpleNamespace(
        id=user_id, full_name="Test Actor", username="actor", role=role
    )


@pytest.fixture
def db_session():
    """AsyncSession stand-in — db.add() / db.execute() are no-ops via
    MagicMock, sufficient since transition() doesn't await db results."""
    return MagicMock(name="AsyncSession")


@pytest.fixture
def patched_audit_and_dispatch():
    """Patch dispatch_event + audit_service.log_status_change globally.

    Returns (audit_mock, dispatch_mock) so each test can assert calls.
    """
    with patch(
        "app.services.audit_service.log_status_change",
        new=AsyncMock(),
    ) as audit_mock, patch(
        "app.services.notification_dispatcher.dispatch_event",
        new=AsyncMock(return_value=None),
    ) as dispatch_mock:
        yield audit_mock, dispatch_mock


# ----------------------------------------------------------------------
# 17 happy-path transitions (T1-T17)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t1_draft_to_submitted(db_session, patched_audit_and_dispatch):
    """T1: candidate submits draft profile. Fires ADMISSION_PROFILE_SUBMITTED."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("draft")
    await state_service.transition(db_session, profile, "submitted", actor=_actor())
    assert profile.status == "submitted"
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_PROFILE_SUBMITTED


@pytest.mark.asyncio
async def test_t2_submitted_to_reviewing(db_session, patched_audit_and_dispatch):
    """T2: manager opens review window. NO dispatch (not in LEGACY map).

    Phase 3 design: reviewing is intermediate gate, no candidate notif.
    """
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("submitted")
    await state_service.transition(db_session, profile, "reviewing", actor=_actor())
    assert profile.status == "reviewing"
    dispatch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_t3_reviewing_to_revision_requested(db_session, patched_audit_and_dispatch):
    """T3: manager requests revision during review. Fires
    ADMISSION_REVISION_REQUESTED."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("reviewing")
    await state_service.transition(
        db_session, profile, "revision_requested", actor=_actor()
    )
    assert profile.status == "revision_requested"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_REVISION_REQUESTED


@pytest.mark.asyncio
async def test_t4_revision_requested_to_reviewing(db_session, patched_audit_and_dispatch):
    """T4: candidate fixed docs, profile back to reviewing. NO dispatch."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("revision_requested")
    await state_service.transition(db_session, profile, "reviewing", actor=_actor())
    assert profile.status == "reviewing"
    dispatch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_t5_revision_requested_to_resubmitted(db_session, patched_audit_and_dispatch):
    """T5: officer resubmits after fix. Fires ADMISSION_RESUBMITTED."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("revision_requested")
    await state_service.transition(db_session, profile, "resubmitted", actor=_actor())
    assert profile.status == "resubmitted"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_RESUBMITTED


@pytest.mark.asyncio
async def test_t6_reviewing_to_result_published(db_session, patched_audit_and_dispatch):
    """T6: admin batch publish results. Fires ADMISSION_RESULT_PUBLISHED.

    Wired in PR-3B Sub-2 — previously deferred (T6 in DEFERRED set).
    """
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("reviewing")
    await state_service.transition(
        db_session, profile, "result_published", actor=_actor()
    )
    assert profile.status == "result_published"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_RESULT_PUBLISHED


@pytest.mark.asyncio
async def test_t7_result_published_to_admitted(db_session, patched_audit_and_dispatch):
    """T7 multi-NV: choice-engine admits profile. Fires
    ADMISSION_DECISION_ADMITTED (NOT WAITLIST_PROMOTED — that's T10
    source-aware path waitlisted→admitted).
    """
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("result_published")
    await state_service.transition(db_session, profile, "admitted", actor=_actor())
    assert profile.status == "admitted"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_DECISION_ADMITTED


@pytest.mark.asyncio
async def test_t8_result_published_to_waitlisted(db_session, patched_audit_and_dispatch):
    """T8: choice-engine waitlist decision. Fires
    ADMISSION_DECISION_WAITLISTED. Wired in PR-3B Sub-2."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("result_published")
    await state_service.transition(db_session, profile, "waitlisted", actor=_actor())
    assert profile.status == "waitlisted"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_DECISION_WAITLISTED


@pytest.mark.asyncio
async def test_t9_result_published_to_rejected(db_session, patched_audit_and_dispatch):
    """T9 multi-NV: choice-engine rejects. Fires ADMISSION_DECISION_REJECTED."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("result_published")
    await state_service.transition(db_session, profile, "rejected", actor=_actor())
    assert profile.status == "rejected"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_DECISION_REJECTED


@pytest.mark.asyncio
async def test_t10_waitlisted_to_admitted_fires_waitlist_promoted(
    db_session, patched_audit_and_dispatch
):
    """⭐ T10 SOURCE-AWARE: manual admin promote from waitlist. MUST fire
    ADMISSION_WAITLIST_PROMOTED (NOT generic ADMISSION_DECISION_ADMITTED).

    This is the critical non-tautological anchor — if pair lookup gets
    reverted in admission_state_service.py:transition(), this test
    catches the regression because target alone (admitted) would map to
    DECISION_ADMITTED via LEGACY_STATUS_TO_EVENT.
    """
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("waitlisted")
    await state_service.transition(db_session, profile, "admitted", actor=_actor())
    assert profile.status == "admitted"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_WAITLIST_PROMOTED, (
        "T10 must use TRANSITION_PAIR_TO_EVENT[(waitlisted, admitted)] = "
        "ADMISSION_WAITLIST_PROMOTED. If this test fails, the pair-lookup "
        "in admission_state_service.transition() likely got reverted to "
        "target-only LEGACY_STATUS_TO_EVENT.get(new_status)."
    )


@pytest.mark.asyncio
async def test_t11_waitlisted_to_rejected(db_session, patched_audit_and_dispatch):
    """T11: admin finalize reject from waitlist. Fires
    ADMISSION_WAITLIST_REJECTED (source-aware, Wave 5 ship 2026-05-16).

    Before Wave 5: pair (waitlisted, rejected) fell through to generic
    ADMISSION_DECISION_REJECTED. After Wave 5: PAIR map distinguishes
    second-pass admin finalize (T11 source) from first-pass cascade
    reject (T9 source). Consumers cần distinguish for audit + UX.
    """
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("waitlisted")
    await state_service.transition(db_session, profile, "rejected", actor=_actor())
    assert profile.status == "rejected"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_WAITLIST_REJECTED


@pytest.mark.asyncio
async def test_t12_admitted_to_confirmed(db_session, patched_audit_and_dispatch):
    """T12 multi-NV: candidate confirms enrollment intent. Fires
    ADMISSION_CONFIRMED."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("admitted")
    await state_service.transition(db_session, profile, "confirmed", actor=_actor())
    assert profile.status == "confirmed"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_CONFIRMED


@pytest.mark.asyncio
async def test_t13_confirmed_to_enrolled(db_session, patched_audit_and_dispatch):
    """T13: candidate enrolls. Fires ADMISSION_ENROLLED. Final state."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("confirmed")
    await state_service.transition(db_session, profile, "enrolled", actor=_actor())
    assert profile.status == "enrolled"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_ENROLLED


@pytest.mark.asyncio
async def test_t14_submitted_to_withdrawn(db_session, patched_audit_and_dispatch):
    """T14: candidate withdraws before review. Fires ADMISSION_WITHDRAWN."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("submitted")
    await state_service.transition(db_session, profile, "withdrawn", actor=_actor())
    assert profile.status == "withdrawn"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_WITHDRAWN


@pytest.mark.asyncio
async def test_t15_revision_requested_to_withdrawn(db_session, patched_audit_and_dispatch):
    """T15: candidate withdraws during revision. Fires ADMISSION_WITHDRAWN."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("revision_requested")
    await state_service.transition(db_session, profile, "withdrawn", actor=_actor())
    assert profile.status == "withdrawn"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_WITHDRAWN


@pytest.mark.asyncio
async def test_t16_resubmitted_to_withdrawn(db_session, patched_audit_and_dispatch):
    """T16: candidate withdraws after resubmit. Fires ADMISSION_WITHDRAWN."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("resubmitted")
    await state_service.transition(db_session, profile, "withdrawn", actor=_actor())
    assert profile.status == "withdrawn"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_WITHDRAWN


@pytest.mark.asyncio
async def test_legacy_t7_submitted_to_approved(db_session, patched_audit_and_dispatch):
    """Legacy single-NV T7: manager approves submitted profile directly.
    Preserved for uses_choice_engine=false path. Fires
    ADMISSION_DECISION_ADMITTED."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("submitted")
    await state_service.transition(db_session, profile, "approved", actor=_actor())
    assert profile.status == "approved"
    assert dispatch_mock.await_args.kwargs["event"] == SystemEvents.ADMISSION_DECISION_ADMITTED


# ----------------------------------------------------------------------
# 5 negative cases
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_negative_illegal_edge_raises(db_session, patched_audit_and_dispatch):
    """(i) Illegal edge: draft → admitted (skips submitted/reviewing/
    result_published). Must raise BusinessRuleViolation, no state change,
    no audit, no dispatch."""
    audit_mock, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("draft")
    with pytest.raises(BusinessRuleViolation):
        await state_service.transition(db_session, profile, "admitted", actor=_actor())
    assert profile.status == "draft"
    audit_mock.assert_not_called()
    dispatch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_negative_final_state_blocks_further_transition(
    db_session, patched_audit_and_dispatch
):
    """(ii) ENROLLED is terminal — any further transition rejected."""
    audit_mock, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("enrolled")
    with pytest.raises(BusinessRuleViolation):
        await state_service.transition(db_session, profile, "draft", actor=_actor())
    assert profile.status == "enrolled"
    audit_mock.assert_not_called()
    dispatch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_negative_skip_dispatch_suppresses_event(
    db_session, patched_audit_and_dispatch
):
    """(iii) skip_dispatch=True: audit row still written but no event
    dispatched. Use case: test fixtures + maintenance scripts."""
    audit_mock, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("submitted")
    await state_service.transition(
        db_session, profile, "approved", actor=_actor(), skip_dispatch=True
    )
    assert profile.status == "approved"
    audit_mock.assert_awaited_once()  # audit still fires
    dispatch_mock.assert_not_called()  # dispatch suppressed


@pytest.mark.asyncio
async def test_negative_skip_audit_still_dispatches(
    db_session, patched_audit_and_dispatch
):
    """(iv) skip_audit=True: dispatch still fires but audit suppressed.
    Use case: caller writes richer audit row separately (vd override
    profile per ADM-014)."""
    audit_mock, dispatch_mock = patched_audit_and_dispatch
    profile = _profile("submitted")
    await state_service.transition(
        db_session, profile, "approved", actor=_actor(), skip_audit=True
    )
    assert profile.status == "approved"
    audit_mock.assert_not_called()  # audit suppressed
    dispatch_mock.assert_awaited_once()  # dispatch still fires


@pytest.mark.asyncio
async def test_negative_pair_lookup_priority_over_target_lookup(
    db_session, patched_audit_and_dispatch
):
    """(v) Critical regression catch: TRANSITION_PAIR_TO_EVENT MUST be
    consulted BEFORE LEGACY_STATUS_TO_EVENT. Anchor for source-aware
    design (memory `pattern-change-impact-audit`).

    Tests 2 transitions to same target (admitted) from different sources:
    - submitted → approved (legacy, no pair entry) → DECISION_ADMITTED
    - waitlisted → admitted (pair entry T10)        → WAITLIST_PROMOTED

    If pair lookup gets reordered/removed, the 2nd case would fall
    through to LEGACY map and fire wrong event.
    """
    _, dispatch_mock = patched_audit_and_dispatch

    # Case A: submitted → approved → DECISION_ADMITTED (legacy single-NV)
    profile_a = _profile("submitted")
    await state_service.transition(db_session, profile_a, "approved", actor=_actor())
    case_a_event = dispatch_mock.await_args.kwargs["event"]

    # Case B: waitlisted → admitted → WAITLIST_PROMOTED (Phase 3 PR-3B Sub-2)
    profile_b = _profile("waitlisted")
    await state_service.transition(db_session, profile_b, "admitted", actor=_actor())
    case_b_event = dispatch_mock.await_args.kwargs["event"]

    # Both target "admitted" semantically but emit DIFFERENT events
    assert case_a_event == SystemEvents.ADMISSION_DECISION_ADMITTED
    assert case_b_event == SystemEvents.ADMISSION_WAITLIST_PROMOTED
    assert case_a_event != case_b_event, (
        "Pair lookup priority broken — submitted→approved and waitlisted→"
        "admitted both fired same event. Check TRANSITION_PAIR_TO_EVENT "
        "is checked BEFORE LEGACY_STATUS_TO_EVENT in transition()."
    )
