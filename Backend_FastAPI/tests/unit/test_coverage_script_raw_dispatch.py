"""B2.3 — regression tests for the raw-dispatch detector in
``app/scripts/check_notification_event_coverage.py``.

Locks the AST detector behavior so future refactors of the script do
not regress to keyword-only matching (the bug Codex caught between
the B2.3 first-cut and the amend: the original detector missed
positional calls like ``safe_dispatch(db, SystemEvents.X, payload={})``
because it only walked ``node.keywords``).

The tests come in three slices:

1. **Per-call AST helper** ``_extract_systemevents_from_event_arg``
   — pure function, parsed-snippet inputs. Covers keyword form,
   positional form (the regression slot), parameterized values, and
   the no-event-arg edge case.
2. **Filesystem walker** ``_scan_raw_dispatch_calls`` end-to-end via
   ``tmp_path`` + ``monkeypatch`` on the module-level
   ``REPO_ROOT`` / ``SCAN_DIRS`` constants. Covers the allowlist,
   the dispatch_event-is-not-flagged contract, and the parameterized
   skip.
3. **Gap surfacing** ``_build_statuses`` integration — confirms an
   outbox event with a raw call site lights up the
   ``raw-dispatch-of-outbox-event`` gap, and a best-effort event
   with the same shape does not.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Tuple

import pytest

from app.scripts.check_notification_event_coverage import (
    RAW_DISPATCH_ALLOWLIST,
    _build_statuses,
    _extract_systemevents_from_event_arg,
    _scan_raw_dispatch_calls,
)


# --- Helpers ---------------------------------------------------------------


def _parse_first_call(src: str) -> ast.Call:
    """Parse a Python snippet and return its first ``ast.Call`` node."""
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return node
    raise AssertionError(f"No ast.Call found in:\n{src}")


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# --- 1. Per-call AST helper ------------------------------------------------


class TestExtractSystemEventsFromEventArg:
    def test_keyword_event_systemevents_member_returns_name(self):
        node = _parse_first_call(
            "safe_dispatch(db, event=SystemEvents.ADMISSION_DECISION_ADMITTED, payload={})"
        )
        assert (
            _extract_systemevents_from_event_arg(node)
            == "ADMISSION_DECISION_ADMITTED"
        )

    def test_positional_event_systemevents_member_returns_name(self):
        """Second positional arg is ``event`` for both ``dispatch()`` and
        ``safe_dispatch()`` — this is the regression slot the original
        keyword-only detector missed."""
        node = _parse_first_call(
            "safe_dispatch(db, SystemEvents.ADMISSION_DECISION_REJECTED, {})"
        )
        assert (
            _extract_systemevents_from_event_arg(node)
            == "ADMISSION_DECISION_REJECTED"
        )

    def test_keyword_parameterized_event_returns_none(self):
        """``event=event`` — forwarded parameter — is not statically
        resolvable; detector returns None rather than guess."""
        node = _parse_first_call(
            "safe_dispatch(db, event=event_var, payload={})"
        )
        assert _extract_systemevents_from_event_arg(node) is None

    def test_keyword_parameterized_takes_precedence_over_positional(self):
        """If the call gives ``event`` as a keyword, that is the only
        slot to check — even if it's parameterized (we must not fall
        through and misread some unrelated positional arg as event)."""
        node = _parse_first_call(
            "safe_dispatch(db, SystemEvents.X, event=event_var, payload={})"
        )
        # event=event_var → not resolvable → return None;
        # we must not silently fall back to args[1].
        assert _extract_systemevents_from_event_arg(node) is None

    def test_positional_parameterized_event_returns_none(self):
        node = _parse_first_call(
            "safe_dispatch(db, event_var, payload={})"
        )
        assert _extract_systemevents_from_event_arg(node) is None

    def test_no_event_arg_returns_none(self):
        node = _parse_first_call("safe_dispatch(db)")
        assert _extract_systemevents_from_event_arg(node) is None


# --- 2. Filesystem walker --------------------------------------------------


class TestScanRawDispatchCalls:
    def test_keyword_form_in_service_file_is_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("services",))
        _write(
            tmp_path,
            "services/foo.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                await safe_dispatch(
                    db=db,
                    event=SystemEvents.ADMISSION_DECISION_ADMITTED,
                    payload={},
                )
            """,
        )
        hits = cov._scan_raw_dispatch_calls()
        assert "ADMISSION_DECISION_ADMITTED" in hits
        assert any("services/foo.py" in s for s in hits["ADMISSION_DECISION_ADMITTED"])

    def test_positional_form_in_service_file_is_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression coverage for the bug Codex caught: positional
        ``safe_dispatch(db, SystemEvents.X, ...)`` MUST flag."""
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("services",))
        _write(
            tmp_path,
            "services/foo.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                await dispatch(db, SystemEvents.ADMISSION_DECISION_REJECTED, {})
                await safe_dispatch(db, SystemEvents.ADMISSION_RESULT_PUBLISHED, {})
            """,
        )
        hits = cov._scan_raw_dispatch_calls()
        assert "ADMISSION_DECISION_REJECTED" in hits, hits
        assert "ADMISSION_RESULT_PUBLISHED" in hits, hits

    def test_dispatch_event_wrapper_calls_are_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``dispatch_event`` is not in ``RAW_DISPATCH_FUNCS`` → calls
        through the wrapper must not appear in the raw-dispatch hits,
        in either form. That's the entire point of B2.3."""
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("services",))
        _write(
            tmp_path,
            "services/foo.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                await dispatch_event(
                    db,
                    event=SystemEvents.ADMISSION_DECISION_ADMITTED,
                    payload={},
                )
                await dispatch_event(db, SystemEvents.ADMISSION_DECISION_REJECTED, {})
            """,
        )
        assert cov._scan_raw_dispatch_calls() == {}

    def test_parameterized_event_argument_is_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Forwarded variables are not statically resolvable —
        deliberately not flagged to avoid false positives."""
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("services",))
        _write(
            tmp_path,
            "services/foo.py",
            """
            async def caller(db, event_var):
                await safe_dispatch(db, event=event_var, payload={})
                await dispatch(db, event_var, payload={})
            """,
        )
        assert cov._scan_raw_dispatch_calls() == {}

    def test_allowlisted_files_are_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``app/services/notification_dispatcher.py`` and
        ``app/tasks/notification_outbox_tasks.py`` are intentional raw
        callers (the dispatcher defines the primitives, the outbox
        worker drains the queue) — they must never appear in hits."""
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("app/services", "app/tasks"))
        # Use raw calls in BOTH allowlisted paths, both forms — none
        # should be flagged.
        _write(
            tmp_path,
            "app/services/notification_dispatcher.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                await dispatch(
                    db, SystemEvents.ADMISSION_DECISION_ADMITTED, payload={}
                )
            """,
        )
        _write(
            tmp_path,
            "app/tasks/notification_outbox_tasks.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                await safe_dispatch(
                    db, event=SystemEvents.ADMISSION_DECISION_REJECTED, payload={}
                )
            """,
        )
        # Sanity: confirm the allowlist contains these two paths so the
        # test's intent stays aligned with the constant.
        assert (
            "app/services/notification_dispatcher.py" in RAW_DISPATCH_ALLOWLIST
        )
        assert (
            "app/tasks/notification_outbox_tasks.py" in RAW_DISPATCH_ALLOWLIST
        )
        assert cov._scan_raw_dispatch_calls() == {}

    def test_unknown_function_name_is_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calls to other functions that happen to take a SystemEvents
        argument (e.g. logging helpers, custom wrappers) must not be
        flagged — only ``dispatch`` and ``safe_dispatch`` are routing
        primitives."""
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("services",))
        _write(
            tmp_path,
            "services/foo.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                await some_logging_helper(
                    db, event=SystemEvents.ADMISSION_DECISION_ADMITTED
                )
                await another_helper(db, SystemEvents.ADMISSION_DECISION_REJECTED, {})
            """,
        )
        assert cov._scan_raw_dispatch_calls() == {}


# --- 3. Gap surfacing ------------------------------------------------------


class TestRawDispatchOfOutboxEventGap:
    def test_outbox_event_with_raw_call_surfaces_the_gap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: positional raw safe_dispatch on an outbox event
        in a non-allowlisted file must surface the
        ``raw-dispatch-of-outbox-event`` gap on that event's status."""
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("services",))
        _write(
            tmp_path,
            "services/foo.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                await safe_dispatch(
                    db, SystemEvents.ADMISSION_DECISION_ADMITTED, {}
                )
            """,
        )
        statuses = cov._build_statuses(db_data=None)
        admitted = next(
            s for s in statuses if s.name == "ADMISSION_DECISION_ADMITTED"
        )
        assert admitted.requires_outbox is True
        assert admitted.raw_dispatch_sites, (
            "Detector must populate raw_dispatch_sites for the call"
        )
        assert "raw-dispatch-of-outbox-event" in admitted.gaps, admitted.gaps

    def test_best_effort_event_with_raw_call_does_not_surface_gap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``requires_outbox=False`` event MAY have raw dispatch sites
        — that is the legacy pre-B2.3 pattern (best-effort callers
        existed before the wrapper). No gap should surface for them."""
        from app.scripts import check_notification_event_coverage as cov

        monkeypatch.setattr(cov, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(cov, "SCAN_DIRS", ("services",))
        _write(
            tmp_path,
            "services/foo.py",
            """
            from app.core.events import SystemEvents
            async def caller(db):
                # ADMISSION_PROFILE_SUBMITTED has requires_outbox=False
                # in the live catalog (verified during B2.3 testing).
                await safe_dispatch(
                    db, SystemEvents.ADMISSION_PROFILE_SUBMITTED, {}
                )
            """,
        )
        statuses = cov._build_statuses(db_data=None)
        submitted = next(
            s for s in statuses if s.name == "ADMISSION_PROFILE_SUBMITTED"
        )
        assert submitted.requires_outbox is False
        # raw_dispatch_sites may be populated, but the gap rule only
        # fires for outbox events.
        assert "raw-dispatch-of-outbox-event" not in submitted.gaps
