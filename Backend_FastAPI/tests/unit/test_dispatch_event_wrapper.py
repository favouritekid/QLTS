"""B2.3 — lock-in tests for the ``dispatch_event()`` wrapper.

The wrapper is the single API the admission domain calls to fire a
``SystemEvents`` member. It routes between two paths based on
``EVENT_CATALOG[event]``:

* ``requires_outbox=True`` → INSERT ``NotificationOutbox`` in the
  caller's transaction; return ``None``.
* ``requires_outbox=False`` → return a post-commit callback that
  delegates to ``safe_dispatch()`` (router awaits it after
  ``db.commit()``).

These tests pin both branches plus the input-validation surface so a
service caller cannot accidentally bypass the routing or pass a raw
string instead of an enum.

Tests use lightweight fakes / mocks rather than a real DB session —
the wrapper itself does not touch the DB beyond ``session.add()`` for
the outbox path; the actual persistence is exercised by the alembic +
ORM tests in ``test_notification_outbox_model.py``. Forwarding into
``safe_dispatch()`` is asserted by patching the symbol in the
dispatcher module.
"""
from __future__ import annotations

from typing import Any, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.events import SystemEvents
from app.services.notification_dispatcher import dispatch_event


# --- Fakes / fixtures ------------------------------------------------------


class _FakeSession:
    """Minimal stand-in for ``AsyncSession``.

    The wrapper's outbox path only calls ``session.add(model_instance)``
    inside the caller's transaction. A real session would also stage
    the row for flush; here we just record what got added so the test
    can assert the column values without DB setup.
    """

    def __init__(self) -> None:
        self.added: List[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


# Outbox events — verified live from EVENT_CATALOG post B2.1 merge
# (`docker compose exec backend python -c '...'` 2026-05-03). 7 events
# carry ``requires_outbox=True``; 5 of those also have
# ``bypass_consent_check=True`` but the wrapper only inserts a row for
# the outbox path — bypass is honored downstream by the worker.
#
# This list intentionally pulls each enum by name (not via a comprehension
# over the catalog) so the test shape is locked: any future PR that
# changes the matrix must touch this file too.
_OUTBOX_EVENTS = (
    SystemEvents.ADMISSION_RESULT_PUBLISHED,
    SystemEvents.ADMISSION_DECISION_ADMITTED,
    SystemEvents.ADMISSION_DECISION_WAITLISTED,
    SystemEvents.ADMISSION_DECISION_REJECTED,
    SystemEvents.ADMISSION_WAITLIST_PROMOTED,
    SystemEvents.ADMISSION_ENROLLED,
    SystemEvents.ADMISSION_ROLLED_BACK,
)

# Best-effort events (``requires_outbox=False``). All 5 currently have
# ``bypass_consent_check=False`` per the live catalog — so the
# "True-case forwarding" test patches ``get_event`` with an injected
# twin to prove the wrapper does not hardcode the flag.
_BEST_EFFORT_EVENTS = (
    SystemEvents.ADMISSION_PROFILE_SUBMITTED,
    SystemEvents.ADMISSION_REVISION_REQUESTED,
    SystemEvents.ADMISSION_RESUBMITTED,
    SystemEvents.ADMISSION_CONFIRMED,
    SystemEvents.ADMISSION_WITHDRAWN,
)


# --- Outbox path -----------------------------------------------------------


class TestDispatchEventOutboxPath:
    """7 outbox events INSERT one row in the caller's tx and return None."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event", _OUTBOX_EVENTS)
    async def test_outbox_event_inserts_one_row_and_returns_none(self, event):
        session = _FakeSession()
        payload = {"profile_id": 42, "choice_priority": 1}
        dedupe_key = f"{event.value.upper()}:42:1"

        result = await dispatch_event(
            session,
            event=event,
            payload=payload,
            dedupe_key=dedupe_key,
        )

        assert result is None, (
            f"Outbox event {event.name} must return None; got {result!r}. "
            "Worker drains the outbox table — caller must NOT await a "
            "callback for the outbox path."
        )
        assert len(session.added) == 1, (
            f"Outbox event {event.name} must INSERT exactly one "
            f"NotificationOutbox row; got {len(session.added)} adds."
        )
        from app.models import NotificationOutbox

        row = session.added[0]
        assert isinstance(row, NotificationOutbox), (
            f"Expected NotificationOutbox instance; got {type(row).__name__}"
        )
        assert row.event_code == event.value, (
            f"Outbox row event_code must be enum.value `{event.value}`; "
            f"got {row.event_code!r}"
        )
        assert row.payload == payload, (
            f"Outbox row payload must equal caller payload; got {row.payload!r}"
        )
        assert row.idempotency_key == dedupe_key, (
            f"Outbox row idempotency_key must equal caller dedupe_key "
            f"`{dedupe_key}`; got {row.idempotency_key!r}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event", _OUTBOX_EVENTS)
    async def test_outbox_event_without_dedupe_key_raises(self, event):
        """End-to-end dedupe contract: outbox events MUST carry a
        dedupe_key — it becomes the row's UNIQUE ``idempotency_key``."""
        session = _FakeSession()

        with pytest.raises(ValueError) as excinfo:
            await dispatch_event(
                session,
                event=event,
                payload={"profile_id": 42},
                dedupe_key=None,
            )

        msg = str(excinfo.value)
        assert "requires_outbox" in msg, (
            f"Error must mention `requires_outbox`; got: {msg!r}"
        )
        assert "dedupe_key" in msg, (
            f"Error must mention missing `dedupe_key`; got: {msg!r}"
        )
        assert event.name in msg, (
            f"Error must name the offending event `{event.name}`; got: {msg!r}"
        )
        assert session.added == [], (
            "No outbox row may be added when validation fails."
        )

    @pytest.mark.asyncio
    async def test_outbox_path_does_not_call_safe_dispatch(self):
        """Outbox path is purely DB-INSERT — must not invoke
        safe_dispatch. The worker (B2.4 / T0-4b) is responsible for
        the actual fanout post-commit."""
        session = _FakeSession()
        with patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new_callable=AsyncMock,
        ) as mock_safe:
            await dispatch_event(
                session,
                event=SystemEvents.ADMISSION_DECISION_ADMITTED,
                payload={"profile_id": 1},
                dedupe_key="X:1:0",
            )
            mock_safe.assert_not_awaited()
            mock_safe.assert_not_called()


# --- Best-effort path ------------------------------------------------------


class TestDispatchEventBestEffortPath:
    """5 best-effort events return a callable and do NOT touch outbox."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event", _BEST_EFFORT_EVENTS)
    async def test_best_effort_event_returns_callable_and_skips_outbox(
        self, event
    ):
        session = _FakeSession()

        result = await dispatch_event(
            session,
            event=event,
            payload={"profile_id": 42},
            dedupe_key=None,  # best-effort accepts None
        )

        assert callable(result), (
            f"Best-effort event {event.name} must return a callable; "
            f"got {result!r}."
        )
        assert session.added == [], (
            f"Best-effort event {event.name} must NOT add an outbox row; "
            f"got {len(session.added)} adds."
        )

    @pytest.mark.asyncio
    async def test_callback_awaits_safe_dispatch_with_full_kwargs(self):
        """Callback must forward ``db``, ``event``, ``payload``,
        ``dedupe_key``, and ``skip_preference_check`` (read from the
        catalog's ``bypass_consent_check`` flag) into ``safe_dispatch``.
        ``rooms`` is intentionally not forwarded — the wrapper does not
        own room-scoping policy yet (deferred to a future PR or to the
        caller pre-#16)."""
        session = _FakeSession()
        event = SystemEvents.ADMISSION_PROFILE_SUBMITTED  # best-effort, bypass=False
        payload = {"profile_id": 7}
        dedupe_key = "SUBMITTED:7"

        with patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new_callable=AsyncMock,
        ) as mock_safe:
            callback = await dispatch_event(
                session,
                event=event,
                payload=payload,
                dedupe_key=dedupe_key,
            )
            assert callback is not None
            await callback()

            mock_safe.assert_awaited_once_with(
                db=session,
                event=event,
                payload=payload,
                dedupe_key=dedupe_key,
                skip_preference_check=False,  # PROFILE_SUBMITTED: bypass=False per live catalog
            )

    @pytest.mark.asyncio
    async def test_callback_forwards_bypass_consent_true(self):
        """The wrapper must read ``bypass_consent_check`` from the
        catalog (not hardcode False). All 5 best-effort events
        currently have bypass=False; patch ``get_event`` to inject a
        True-case so the forwarding path is exercised end-to-end."""
        from app.core.event_catalog import EventDefinition

        session = _FakeSession()
        event = SystemEvents.ADMISSION_PROFILE_SUBMITTED  # best-effort
        payload = {"profile_id": 9}

        # Build a minimal EventDefinition twin with bypass_consent_check=True.
        # Using MagicMock keeps the test independent of EventDefinition's
        # other field requirements (templates, audience matrix, etc.).
        twin = MagicMock(spec=EventDefinition)
        twin.requires_outbox = False
        twin.bypass_consent_check = True

        with patch(
            "app.services.notification_dispatcher.get_event",
            return_value=twin,
        ), patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new_callable=AsyncMock,
        ) as mock_safe:
            callback = await dispatch_event(
                session,
                event=event,
                payload=payload,
                dedupe_key=None,
            )
            await callback()

            mock_safe.assert_awaited_once_with(
                db=session,
                event=event,
                payload=payload,
                dedupe_key=None,
                skip_preference_check=True,  # the patched True flows through
            )


# --- Input validation ------------------------------------------------------


class TestDispatchEventInputValidation:
    """Wrapper must reject non-catalog inputs (incl. raw strings)."""

    @pytest.mark.asyncio
    async def test_raw_string_event_raises_valueerror(self):
        """``SystemEvents(str, Enum)`` would otherwise let a raw string
        with a matching value silently dict-lookup into the catalog
        (str-enum hashes as its value). The wrapper enforces an explicit
        ``isinstance(event, SystemEvents)`` guard so any downstream
        ``event.value`` / ``event.name`` access is safe — and the
        validation error fires at the front door, not deep inside
        ``safe_dispatch``."""
        session = _FakeSession()

        with pytest.raises(ValueError) as excinfo:
            await dispatch_event(
                session,
                event="admission_profile_submitted",  # raw string — rejected
                payload={},
                dedupe_key="X",
            )

        msg = str(excinfo.value)
        assert "SystemEvents" in msg, (
            "Error must hint that a SystemEvents enum member is "
            f"expected; got: {msg!r}"
        )
        # Mention the actual type so the operator can debug fast.
        assert "str" in msg, (
            f"Error must name the offending type; got: {msg!r}"
        )
        assert session.added == []

    @pytest.mark.asyncio
    async def test_non_enum_int_event_raises_valueerror(self):
        """Non-string non-enum input (e.g. someone confused an event
        with an event id integer) must also be rejected."""
        session = _FakeSession()

        with pytest.raises(ValueError) as excinfo:
            await dispatch_event(
                session,
                event=42,  # integer — wrong type
                payload={},
                dedupe_key="X",
            )

        msg = str(excinfo.value)
        assert "SystemEvents" in msg
        assert "int" in msg
        assert session.added == []

    @pytest.mark.asyncio
    async def test_unknown_systemevents_member_raises_valueerror(self):
        """Some legacy ``SystemEvents`` members predate the catalog
        and may not be registered. The wrapper must raise a clear
        error rather than ``KeyError`` (catalog uses .get() per the
        wrapper contract)."""
        from app.core.event_catalog import EVENT_CATALOG

        # Pick any SystemEvents member that is NOT in EVENT_CATALOG.
        # If every member is in the catalog, skip — the test only
        # applies in the non-empty gap case.
        uncatalogued = [
            ev for ev in SystemEvents if ev not in EVENT_CATALOG
        ]
        if not uncatalogued:
            pytest.skip(
                "All SystemEvents members are in EVENT_CATALOG — no "
                "uncatalogued enum to exercise this branch."
            )
        ev = uncatalogued[0]

        session = _FakeSession()
        with pytest.raises(ValueError) as excinfo:
            await dispatch_event(
                session,
                event=ev,
                payload={},
                dedupe_key="X",
            )

        msg = str(excinfo.value)
        assert "EVENT_CATALOG" in msg
        assert session.added == []


# --- Wrapper public API surface --------------------------------------------


class TestDispatchEventApiSurface:
    """Lock the public surface so a service caller cannot drift."""

    def test_dispatch_event_is_exported_from_dispatcher_module(self):
        from app.services import notification_dispatcher

        assert hasattr(notification_dispatcher, "dispatch_event")
        assert callable(notification_dispatcher.dispatch_event)

    def test_dispatch_event_signature_is_keyword_only(self):
        """``event``, ``payload``, ``dedupe_key`` are keyword-only so a
        future signature add (e.g. ``rooms``) does not silently shift
        positional arguments at call sites."""
        import inspect

        sig = inspect.signature(dispatch_event)
        params = sig.parameters

        # First param is positional ``db``; the rest must be keyword-only.
        names = list(params.keys())
        assert names[0] == "db"
        assert params["db"].kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        )

        for kw in ("event", "payload", "dedupe_key"):
            assert kw in params, f"Missing keyword arg `{kw}`"
            assert params[kw].kind == inspect.Parameter.KEYWORD_ONLY, (
                f"Arg `{kw}` must be keyword-only; got "
                f"{params[kw].kind!r}"
            )

        # dedupe_key has a default (Optional, nullable for best-effort path).
        assert params["dedupe_key"].default is None
