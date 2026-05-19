"""Unit tests for ``--allow-deferred`` flag in
``app/scripts/check_notification_event_coverage.py`` (Cold Cutover #16).

Locks the contract:

  1. The default deferred set (the four ADMISSION_* events with no
     current legacy writer) makes the verdict pass with exit 0 + a
     visible ``Deferred (allow-listed)`` block in the summary.
  2. Misuse — typoed names, wired-but-allow-listed events, events
     with extra gaps beyond ``no-dispatch-site`` — all surface as
     failures so the flag never silently hides a real bug.
  3. The flag never silences blocking gaps like
     ``raw-dispatch-of-outbox-event`` or ``rule-has-zero-actions``.
"""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

# Import the script directly so we can call ``_summarize`` with
# hand-built ``EventStatus`` instances and assert on the verdict
# without spinning up the full grep + AST scan.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "scripts"))
import check_notification_event_coverage as coverage  # noqa: E402

from app.services.admission_state_service import (
    DEFERRED_ADMISSION_EVENTS,
    LEGACY_STATUS_TO_EVENT,
)


# ---------------------------------------------------------------------------
# Stand-in builder
# ---------------------------------------------------------------------------


def _status(
    name: str,
    *,
    in_catalog: bool = True,
    notification_class: str = "user",
    in_seed_defaults: bool = True,
    dispatch_sites: list = None,
    requires_outbox: bool = False,
    raw_dispatch_sites: list = None,
):
    st = coverage.EventStatus(name=name)
    st.in_catalog = in_catalog
    st.notification_class = notification_class
    st.in_seed_defaults = in_seed_defaults
    st.dispatch_sites = dispatch_sites or []
    st.requires_outbox = requires_outbox
    st.raw_dispatch_sites = raw_dispatch_sites or []
    return st


# ---------------------------------------------------------------------------
# Default deferred set ↔ state_service.DEFERRED_ADMISSION_EVENTS parity
# ---------------------------------------------------------------------------


def test_deferred_set_canonical_source_is_state_service() -> None:
    """Locks the contract that ops calls ``--allow-deferred`` with the
    same set of names enumerated in
    ``state_service.DEFERRED_ADMISSION_EVENTS``. Without this, the
    coverage flag and the runtime mapping could drift silently."""
    # Q9 #07 Phase E Wave 1 (2026-05-19) added 3 PRIORITY_* events to
    # catalog seed; dispatch sites ship Wave 2 (override_kv) + Wave 3
    # (verify/reject evidence). Tracked here until those waves merge.
    assert DEFERRED_ADMISSION_EVENTS == frozenset({
        "PRIORITY_KV_OVERRIDDEN",
        "PRIORITY_OBJECT_VERIFIED",
        "PRIORITY_OBJECT_REJECTED",
    })


def test_deferred_events_disjoint_from_mapped_events() -> None:
    """A status that is mapped (writer exists) cannot be deferred."""
    mapped = {ev.name for ev in LEGACY_STATUS_TO_EVENT.values()}
    assert mapped & DEFERRED_ADMISSION_EVENTS == set()


# ---------------------------------------------------------------------------
# _summarize behaviour with --allow-deferred
# ---------------------------------------------------------------------------


def _capture_stderr(callable_):
    """Run ``callable_()`` while capturing its ``sys.stderr`` writes."""
    buf = StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        rc = callable_()
    finally:
        sys.stderr = saved
    return rc, buf.getvalue()


def test_summarize_passes_when_deferred_events_match(capsys) -> None:
    """Q9 #07 Phase E Wave 1 (2026-05-19): DEFERRED set has 3 PRIORITY_*
    events; verify passing the matching --allow-deferred list yields
    rc=0 + "Deferred (allow-listed)" block.
    """
    # Build stand-in statuses with ONLY the single no-dispatch-site gap
    # (allow-list only excuses that exact single gap).
    statuses = [_status(name) for name in DEFERRED_ADMISSION_EVENTS]
    assert len(statuses) == 3
    for st in statuses:
        assert st.gaps == ["no-dispatch-site"]

    rc, output = _capture_stderr(
        lambda: coverage._summarize(
            statuses,
            allow_deferred=set(DEFERRED_ADMISSION_EVENTS),
        )
    )

    assert rc == 0
    # No "with gaps:" failure block — only "Deferred (allow-listed)".
    assert "event(s) with gaps:" not in output
    assert "Deferred (allow-listed)" in output


def test_summarize_fails_when_deferred_event_actually_wired(capsys) -> None:
    """Adding a wired event to the allow-deferred list is misuse —
    the flag is meant to surface gaps, not silence already-wired
    events."""
    wired = _status(
        "ADMISSION_DECISION_ADMITTED",
        dispatch_sites=["app/services/admission_state_service.py:99"],
    )
    assert wired.gaps == []  # no gap

    rc, output = _capture_stderr(
        lambda: coverage._summarize(
            [wired],
            allow_deferred={"ADMISSION_DECISION_ADMITTED"},
        )
    )

    assert rc == 1
    assert "--allow-deferred misuse" in output
    assert "ADMISSION_DECISION_ADMITTED" in output


def test_summarize_fails_on_unknown_deferred_name(capsys) -> None:
    """Typoed name in --allow-deferred — the SystemEvents enum
    doesn't have it. The flag misuses fail loud so a typo never
    silences the real list."""
    statuses = [
        _status(name) for name in DEFERRED_ADMISSION_EVENTS
    ]

    rc, output = _capture_stderr(
        lambda: coverage._summarize(
            statuses,
            allow_deferred=set(DEFERRED_ADMISSION_EVENTS) | {"NON_EXISTENT_EVENT"},
        )
    )

    assert rc == 1
    assert "NON_EXISTENT_EVENT" in output
    assert "--allow-deferred misuse" in output
    assert "not in SystemEvents" in output


def test_summarize_fails_when_deferred_event_has_extra_gap(capsys) -> None:
    """If a deferred event has BOTH ``no-dispatch-site`` AND another
    gap (e.g. ``rule-has-zero-actions``), the allow-list does NOT
    silence it. The flag covers exactly the single dispatch-site
    gap, never anything broader."""
    deferred_with_extra = _status(
        "ADMISSION_RESULT_PUBLISHED",
        in_seed_defaults=False,  # → extra gap "missing-seed-default"
    )
    # Sanity: stand-in actually has BOTH gaps
    assert "missing-seed-default" in deferred_with_extra.gaps
    assert "no-dispatch-site" in deferred_with_extra.gaps

    rc, output = _capture_stderr(
        lambda: coverage._summarize(
            [deferred_with_extra],
            allow_deferred={"ADMISSION_RESULT_PUBLISHED"},
        )
    )

    assert rc == 1
    assert "--allow-deferred misuse" in output
    assert "ADMISSION_RESULT_PUBLISHED" in output


def test_summarize_does_not_silence_outbox_violation(capsys) -> None:
    """``raw-dispatch-of-outbox-event`` is a routing bug; even if the
    event happens to be in the deferred list, the violation must
    still fail. Defense against accidentally widening the flag's
    scope.

    The stand-in event below has BOTH ``no-dispatch-site`` (no
    dispatch_event call sites) AND ``raw-dispatch-of-outbox-event``
    (a raw safe_dispatch call lurking somewhere). Because
    --allow-deferred only excuses the single ``no-dispatch-site``
    gap, the misuse path triggers and CI fails.
    """
    bad = _status(
        "ADMISSION_RESULT_PUBLISHED",
        requires_outbox=True,
        raw_dispatch_sites=["app/services/some_caller.py:42"],
    )
    assert "raw-dispatch-of-outbox-event" in bad.gaps
    assert "no-dispatch-site" in bad.gaps

    rc, output = _capture_stderr(
        lambda: coverage._summarize(
            [bad],
            allow_deferred={"ADMISSION_RESULT_PUBLISHED"},
        )
    )

    assert rc == 1
    # Either the misuse block OR the failing block fires; both are
    # acceptable as long as the verdict is 1.
    assert "ADMISSION_RESULT_PUBLISHED" in output
