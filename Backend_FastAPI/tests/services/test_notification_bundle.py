"""Unit tests for ``app.services.notification_bundle``.

Covers contract of ``dispatch_bundle`` + ``compose_post_commit_callbacks``
in isolation. The underlying ``dispatch()`` and the SQLAlchemy session
are mocked so these tests do not require a live database.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.events import SystemEvents
from app.services.notification_bundle import (
    BundleDispatchResult,
    NotificationIntent,
    compose_post_commit_callbacks,
    dispatch_bundle,
)


def _structlog_record_extras(record: logging.LogRecord) -> Optional[dict]:
    """The project wraps Python ``logging`` with structlog so ``extra={...}``
    fields land inside the JSON-serialized ``record.message`` body, not on
    ``record.__dict__``. This helper parses the JSON so tests can assert on
    structured fields the same way ops would grep for them."""
    try:
        payload = json.loads(record.getMessage())
    except (ValueError, TypeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("extra"), dict):
        return payload["extra"]
    return payload if isinstance(payload, dict) else None


def _fake_session():
    """Return a session whose ``begin_nested()`` is an async context
    manager. We don't care about its internals — only that the helper
    enters/exits cleanly."""

    @asynccontextmanager
    async def _nested():
        yield None

    session = MagicMock()
    session.begin_nested = _nested
    return session


# ---------------------------------------------------------------------------
# dispatch_bundle — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_bundle_two_intents_succeed(monkeypatch, caplog):
    """Both dispatches succeed → persist_status='ok', ids gathered, callback composed."""
    cb_first = AsyncMock()
    cb_second = AsyncMock()
    dispatch_mock = AsyncMock(side_effect=[([1, 2], cb_first), ([3], cb_second)])
    monkeypatch.setattr(
        "app.services.notification_bundle.dispatch", dispatch_mock
    )

    intents = [
        NotificationIntent(
            event=SystemEvents.APPLICATION_STATUS_CHANGED,
            payload={"app": 1},
            dedupe_key="k1",
        ),
        NotificationIntent(
            event=SystemEvents.LEAD_STATUS_CHANGED,
            payload={"lead": 1},
            dedupe_key="k2",
        ),
    ]

    caplog.set_level(logging.INFO)
    result = await dispatch_bundle(
        _fake_session(), bundle_label="t_ok", intents=intents,
    )

    assert isinstance(result, BundleDispatchResult)
    assert result.persist_status == "ok"
    assert result.notification_ids == [1, 2, 3]
    assert result.intent_events == (
        "application_status_changed",
        "lead_status_changed",
    )
    assert result.callback is not None
    assert dispatch_mock.await_count == 2

    # Composed callback runs both children
    await result.callback()
    cb_first.assert_awaited_once()
    cb_second.assert_awaited_once()
    assert any(
        "notification_bundle_persisted" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# dispatch_bundle — rollback path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_bundle_second_dispatch_raises_rolls_back(
    monkeypatch, caplog,
):
    """If dispatch #2 raises → persist_status='rolled_back', ids empty,
    callback None, log emitted, exception swallowed (does not propagate)."""
    cb_first = AsyncMock()
    dispatch_mock = AsyncMock(
        side_effect=[([7], cb_first), RuntimeError("boom")],
    )
    monkeypatch.setattr(
        "app.services.notification_bundle.dispatch", dispatch_mock
    )

    intents = [
        NotificationIntent(event=SystemEvents.APPLICATION_STATUS_CHANGED, payload={}),
        NotificationIntent(event=SystemEvents.LEAD_STATUS_CHANGED, payload={}),
    ]

    caplog.set_level(logging.WARNING)
    result = await dispatch_bundle(
        _fake_session(), bundle_label="t_rollback", intents=intents,
    )

    assert result.persist_status == "rolled_back"
    assert result.notification_ids == []
    assert result.callback is None
    assert dispatch_mock.await_count == 2

    # First child callback must NOT run (savepoint rolled back the whole bundle)
    cb_first.assert_not_awaited()

    rolled_back_extras = next(
        (
            _structlog_record_extras(r)
            for r in caplog.records
            if "notification_bundle_rolled_back" in r.getMessage()
        ),
        None,
    )
    assert rolled_back_extras is not None, "expected notification_bundle_rolled_back log"
    assert rolled_back_extras.get("bundle_label") == "t_rollback"
    assert rolled_back_extras.get("failed_event") == "lead_status_changed"
    assert rolled_back_extras.get("error_type") == "RuntimeError"


# ---------------------------------------------------------------------------
# dispatch_bundle — empty intents = caller bug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_bundle_empty_intents_raises_value_error():
    """Empty intents list is a programming error — service must guard
    explicitly (e.g. ``if profile.lead_id:``) before calling. The helper
    refuses to silently no-op."""
    with pytest.raises(ValueError, match="at least one NotificationIntent"):
        await dispatch_bundle(
            _fake_session(), bundle_label="t_empty", intents=[],
        )


# ---------------------------------------------------------------------------
# compose_post_commit_callbacks — basic shapes
# ---------------------------------------------------------------------------


def test_compose_returns_none_for_empty_iterable():
    assert compose_post_commit_callbacks(label="x", callbacks=[]) is None


def test_compose_returns_none_when_all_callbacks_are_none():
    assert (
        compose_post_commit_callbacks(label="x", callbacks=[None, None, None])
        is None
    )


def test_compose_passes_through_single_callback():
    cb = AsyncMock()
    result = compose_post_commit_callbacks(label="x", callbacks=[None, cb, None])
    # Single non-None callback is returned as-is, no wrapping
    assert result is cb


# ---------------------------------------------------------------------------
# compose_post_commit_callbacks — partial failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compose_partial_failure_logs_and_continues(caplog):
    """Callback 1 raises → callback 2 still runs → composed function
    does NOT propagate the exception → partial-failure log emitted."""
    cb_a = AsyncMock(side_effect=RuntimeError("first failed"))
    cb_b = AsyncMock()
    cb_c = AsyncMock(side_effect=ValueError("third failed"))

    composed = compose_post_commit_callbacks(
        label="t_partial", callbacks=[cb_a, cb_b, cb_c],
    )
    assert composed is not None

    caplog.set_level(logging.WARNING)
    # Must not raise
    await composed()

    # All three were awaited (no early exit)
    cb_a.assert_awaited_once()
    cb_b.assert_awaited_once()
    cb_c.assert_awaited_once()

    partial_extras = next(
        (
            _structlog_record_extras(r)
            for r in caplog.records
            if "notification_bundle_callback_partial_failure" in r.getMessage()
        ),
        None,
    )
    assert partial_extras is not None, "expected partial-failure log"
    assert partial_extras.get("bundle_label") == "t_partial"
    assert partial_extras.get("callback_count") == 3
    assert partial_extras.get("failed_callback_count") == 2
    assert partial_extras.get("failed_callback_indexes") == [0, 2]
