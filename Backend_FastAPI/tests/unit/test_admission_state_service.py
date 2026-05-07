"""Unit tests for ``app/services/admission_state_service.py`` (Cold Cutover #16).

Covers the centralized ``transition()`` writer:

  1. State machine validation (raises ``BusinessRuleViolation`` on
     illegal edge).
  2. ``old_status`` capture happens BEFORE the write (so the audit
     row + dispatch payload record the actual prior state).
  3. ``profile.status`` + ``version`` + ``updated_at`` written together;
     ``extra_fields`` applied in the same atomic block.
  4. ``audit_service.log_status_change`` called with the right
     positional + keyword args; ``skip_audit=True`` suppresses it.
  5. ``dispatch_event`` called with mapped ``ADMISSION_*`` event for
     each legacy status; ``event_metadata`` merged into payload;
     ``skip_dispatch=True`` suppresses the call.

The transition() function is async + DB-touching (audit + dispatch).
The tests mock both so coverage stays at the contract level — DB
behaviour is covered by the integration suite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.events import SystemEvents
from app.services import admission_state_service as state_service
from app.utils.exceptions import BusinessRuleViolation


# ---------------------------------------------------------------------------
# Lightweight stand-ins (no DB)
# ---------------------------------------------------------------------------


def _profile(status: str = "draft", profile_id: int = 1, lead_id: int = 99):
    """Mutable namespace mimicking ``AdmissionProfile`` enough for the helper."""
    return SimpleNamespace(
        id=profile_id,
        lead_id=lead_id,
        status=status,
        version=1,
        updated_at=None,
    )


def _actor(user_id: int = 7):
    return SimpleNamespace(id=user_id, full_name="Test Actor", username="actor")


@pytest.fixture
def db_session():
    """AsyncSession stand-in — only used as a passthrough arg."""
    return MagicMock(name="AsyncSession")


@pytest.fixture
def patched_audit_and_dispatch():
    """Patch ``audit_service.log_status_change`` + ``dispatch_event`` so
    the helper runs without touching DB or NotificationOutbox."""
    with patch(
        "app.services.audit_service.log_status_change",
        new=AsyncMock(),
    ) as audit_mock, patch(
        "app.services.notification_dispatcher.dispatch_event",
        new=AsyncMock(return_value=None),
    ) as dispatch_mock:
        yield audit_mock, dispatch_mock


# ---------------------------------------------------------------------------
# 1. Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_raises_business_rule_on_illegal_edge(
    db_session, patched_audit_and_dispatch
):
    """``draft → enrolled`` is illegal per the state machine — must
    raise ``BusinessRuleViolation`` (not the raw ``ValueError`` the
    state machine itself raises) so router layers map to 400 without
    extra try/except glue."""
    audit_mock, dispatch_mock = patched_audit_and_dispatch
    profile = _profile(status="draft")
    actor = _actor()

    with pytest.raises(BusinessRuleViolation):
        await state_service.transition(db_session, profile, "enrolled", actor=actor)

    # Failed validation MUST NOT touch status / audit / dispatch.
    assert profile.status == "draft"
    assert profile.version == 1
    audit_mock.assert_not_called()
    dispatch_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 2 + 3. old_status capture, version bump, extra_fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_captures_old_status_before_write(
    db_session, patched_audit_and_dispatch
):
    """The audit row records the actual prior status, not the
    post-write value. Catches the bug class #15 fixed in
    ``verify_and_confirm`` before #16 centralised it."""
    audit_mock, _ = patched_audit_and_dispatch
    profile = _profile(status="approved")  # legacy approved → confirmed
    actor = _actor()

    await state_service.transition(db_session, profile, "confirmed", actor=actor)

    audit_mock.assert_awaited_once()
    args, kwargs = audit_mock.await_args
    assert kwargs["old_status"] == "approved"
    assert kwargs["new_status"] == "confirmed"
    # Profile actually mutated.
    assert profile.status == "confirmed"


@pytest.mark.asyncio
async def test_transition_increments_version_and_stamps_updated_at(
    db_session, patched_audit_and_dispatch
):
    profile = _profile(status="submitted")
    profile.version = 5
    before = datetime.now(timezone.utc)

    await state_service.transition(db_session, profile, "approved", actor=_actor())

    assert profile.version == 6
    assert profile.updated_at is not None
    assert profile.updated_at >= before


@pytest.mark.asyncio
async def test_transition_applies_extra_fields_atomically(
    db_session, patched_audit_and_dispatch
):
    """Extra-field write is a passthrough so callers can stamp
    ``approved_at`` / ``approved_by_id`` etc. in the same atomic batch
    as the status change. The helper does not validate field names —
    SQLAlchemy raises at flush time if an unknown column is set."""
    profile = _profile(status="submitted")
    actor = _actor()
    extras = {
        "approved_at": datetime(2026, 5, 3, 10, tzinfo=timezone.utc),
        "approved_by_id": actor.id,
        "approval_notes": "Looks good",
    }

    await state_service.transition(
        db_session, profile, "approved", actor=actor, extra_fields=extras,
    )

    assert profile.status == "approved"
    assert profile.approved_at == extras["approved_at"]
    assert profile.approved_by_id == actor.id
    assert profile.approval_notes == "Looks good"


# ---------------------------------------------------------------------------
# 4. Audit log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_audit_call_passes_actor_reason_source(
    db_session, patched_audit_and_dispatch
):
    audit_mock, _ = patched_audit_and_dispatch
    profile = _profile(status="submitted")
    actor = _actor(user_id=42)

    await state_service.transition(
        db_session,
        profile,
        "rejected",
        actor=actor,
        reason="Missing transcript",
        source="bulk_api",
        extra_fields={
            "rejected_by_id": actor.id,
            "rejection_reason": "Missing transcript",
        },
    )

    audit_mock.assert_awaited_once()
    args, kwargs = audit_mock.await_args
    # Positional: db, "AdmissionProfile", profile.id
    assert args[1] == "AdmissionProfile"
    assert args[2] == profile.id
    assert kwargs["actor_user_id"] == 42
    assert kwargs["reason"] == "Missing transcript"
    assert kwargs["source"] == "bulk_api"


@pytest.mark.asyncio
async def test_transition_skip_audit_suppresses_log(
    db_session, patched_audit_and_dispatch
):
    """Override flow uses ``log_changes`` for a richer audit row;
    ``skip_audit=True`` avoids writing a duplicate ``log_status_change``
    row in the same transaction (ADM-014)."""
    audit_mock, _ = patched_audit_and_dispatch
    profile = _profile(status="approved")

    await state_service.transition(
        db_session, profile, "overridden", actor=_actor(), skip_audit=True,
    )

    audit_mock.assert_not_called()
    # State change still happens.
    assert profile.status == "overridden"


@pytest.mark.asyncio
async def test_transition_audit_actor_user_id_none_for_system_flow(
    db_session, patched_audit_and_dispatch
):
    """Magic-link confirm has no authenticated actor; helper accepts
    ``actor=None`` and writes ``actor_user_id=None`` to the audit row."""
    audit_mock, _ = patched_audit_and_dispatch
    profile = _profile(status="approved")

    await state_service.transition(
        db_session, profile, "confirmed", actor=None, source="magic_link",
    )

    args, kwargs = audit_mock.await_args
    assert kwargs["actor_user_id"] is None


# ---------------------------------------------------------------------------
# 5. Dispatch event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_dispatches_mapped_event(
    db_session, patched_audit_and_dispatch
):
    """Each legacy status → mapped ADMISSION_* event. ``transition()``
    only forwards what ``LEGACY_STATUS_TO_EVENT`` resolves; the parity
    test below locks the full mapping."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile(status="submitted")
    profile.version = 3
    actor = _actor()

    await state_service.transition(db_session, profile, "approved", actor=actor)

    dispatch_mock.assert_awaited_once()
    args, kwargs = dispatch_mock.await_args
    assert kwargs["event"] == SystemEvents.ADMISSION_DECISION_ADMITTED
    payload = kwargs["payload"]
    assert payload["application_id"] == profile.id
    assert payload["lead_id"] == profile.lead_id
    assert payload["old_status"] == "submitted"
    assert payload["new_status"] == "approved"
    assert payload["actor_id"] == actor.id
    # Dedupe key includes ``v{post_transition_version}`` so repeated
    # legal cycles (rejected → resubmitted → rejected) get distinct
    # idempotency_key values; the cycle regression test below proves it.
    # ``profile.version`` was 3 before the call, so post-transition is 4.
    assert kwargs["dedupe_key"] == f"admission:{profile.id}:approved:v4"


@pytest.mark.asyncio
async def test_transition_event_metadata_merged_into_payload(
    db_session, patched_audit_and_dispatch
):
    """``override=True`` etc. flows through ``event_metadata`` and
    overlays the canonical payload keys on conflict. Locks the
    overridden → T7 + override=True contract."""
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile(status="approved")
    profile.version = 5

    await state_service.transition(
        db_session,
        profile,
        "overridden",
        actor=_actor(),
        skip_audit=True,
        event_metadata={"override": True, "override_reason": "Special case"},
    )

    args, kwargs = dispatch_mock.await_args
    assert kwargs["event"] == SystemEvents.ADMISSION_DECISION_ADMITTED
    payload = kwargs["payload"]
    assert payload["override"] is True
    assert payload["override_reason"] == "Special case"
    # Dedupe key includes ``new_status`` AND ``v{post_version}`` — even
    # though approved + overridden both fire T7, the new_status segment
    # ("overridden" vs "approved") + version (post-write) keeps the two
    # outbox rows distinct.
    assert kwargs["dedupe_key"] == f"admission:{profile.id}:overridden:v6"


@pytest.mark.asyncio
async def test_transition_dedupe_key_includes_version_for_legal_cycle(
    db_session, patched_audit_and_dispatch
):
    """Legal cycle ``rejected → resubmitted → rejected`` MUST produce
    distinct dedupe keys for each ``rejected`` outbox row.

    Without the ``v{post_version}`` suffix, both rejection rows would
    share ``admission:{id}:rejected`` and the second outbox INSERT
    would suppress as a duplicate (the dedupe contract treats same key
    as same event), causing the second
    ``ADMISSION_DECISION_REJECTED`` to silently drop. This is the
    bug class the patch closes.
    """
    _, dispatch_mock = patched_audit_and_dispatch

    # Profile starts at ``submitted`` (version 1) — submit → reject →
    # resubmit → reject is the canonical cycle the state machine
    # allows when an applicant fixes documents and re-submits.
    profile = _profile(status="submitted", profile_id=42)
    actor = _actor()

    # First rejection: submitted → rejected (version 1 → 2)
    await state_service.transition(
        db_session, profile, "rejected", actor=actor,
    )
    first_reject_key = dispatch_mock.await_args.kwargs["dedupe_key"]

    # Resubmit: rejected → resubmitted (version 2 → 3)
    await state_service.transition(
        db_session, profile, "resubmitted", actor=actor,
    )

    # Second rejection: resubmitted → rejected (version 3 → 4)
    await state_service.transition(
        db_session, profile, "rejected", actor=actor,
    )
    second_reject_key = dispatch_mock.await_args.kwargs["dedupe_key"]

    # Same profile.id + same new_status, but DIFFERENT post-transition
    # versions → DIFFERENT dedupe keys.
    assert first_reject_key == "admission:42:rejected:v2"
    assert second_reject_key == "admission:42:rejected:v4"
    assert first_reject_key != second_reject_key, (
        "Legal cycle rejected → resubmitted → rejected MUST produce "
        "distinct dedupe keys; without the v{post_version} suffix the "
        "second outbox row would collide with the first."
    )


@pytest.mark.asyncio
async def test_transition_skip_dispatch_suppresses_event(
    db_session, patched_audit_and_dispatch
):
    _, dispatch_mock = patched_audit_and_dispatch
    profile = _profile(status="draft")

    profile_out, callback = await state_service.transition(
        db_session, profile, "submitted", actor=_actor(), skip_dispatch=True,
    )

    dispatch_mock.assert_not_called()
    assert callback is None
    assert profile_out.status == "submitted"


@pytest.mark.asyncio
async def test_transition_returns_dispatch_callback(
    db_session, patched_audit_and_dispatch
):
    """Best-effort events return a callback (the router awaits it
    after ``db.commit()``); outbox events return ``None`` (the worker
    drains the row asynchronously). Locks the contract: helper passes
    through whatever ``dispatch_event`` returns."""
    _, dispatch_mock = patched_audit_and_dispatch
    sentinel_callback = AsyncMock()
    dispatch_mock.return_value = sentinel_callback

    profile = _profile(status="submitted")
    _, callback = await state_service.transition(
        db_session, profile, "approved", actor=_actor(),
    )

    assert callback is sentinel_callback


@pytest.mark.asyncio
async def test_transition_no_event_for_unmapped_status(
    db_session, patched_audit_and_dispatch
):
    """If a future legal status has no row in
    ``LEGACY_STATUS_TO_EVENT`` (e.g. an experimental transient state),
    the helper writes status + audit and skips dispatch. The coverage
    script + parity test catch unmapped events at CI."""
    _, dispatch_mock = patched_audit_and_dispatch
    # Use a status the state machine accepts but the mapping omits —
    # there isn't one in the legacy set, so monkey-patch the mapping
    # for this single test.
    profile = _profile(status="submitted")
    with patch.dict(
        state_service.LEGACY_STATUS_TO_EVENT,
        {"approved": None},  # type: ignore[dict-item]
    ):
        # Re-fetch via .get() returns None → branch below skips dispatch
        # The mapping monkey-patch above isn't sufficient because .get()
        # still returns the original SystemEvents value due to default
        # arg evaluation; instead, exercise the code path by removing
        # the key entirely.
        del state_service.LEGACY_STATUS_TO_EVENT["approved"]
        try:
            _, callback = await state_service.transition(
                db_session, profile, "approved", actor=_actor(),
            )
            dispatch_mock.assert_not_called()
            assert callback is None
        finally:
            # Restore for other tests.
            state_service.LEGACY_STATUS_TO_EVENT["approved"] = (
                SystemEvents.ADMISSION_DECISION_ADMITTED
            )


# ---------------------------------------------------------------------------
# Returned tuple
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_returns_profile_and_callback_tuple(
    db_session, patched_audit_and_dispatch
):
    profile = _profile(status="submitted")

    out_profile, callback = await state_service.transition(
        db_session, profile, "approved", actor=_actor(),
    )

    assert out_profile is profile  # same instance
    # callback is whatever dispatch_mock returned (None in default fixture)
    assert callback is None
