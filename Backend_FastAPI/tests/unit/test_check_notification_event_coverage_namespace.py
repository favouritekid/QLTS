"""Unit tests for the dual-namespace cohabitation detector in
``app/scripts/check_notification_event_coverage.py`` (CI tooling
extension).

Locks the contract:

  1. ``_scan_dual_namespace_pairs`` finds enclosing functions that
     dispatch BOTH an ``ADMISSION_*`` event AND an ``APPLICATION_*``
     event in the same body.
  2. Default mode (``--strict-namespace`` off) prints the report as
     informational and returns 0 — Cold Cutover #16 ships dual
     dispatch on purpose, so the warning is visible without failing
     CI.
  3. ``--strict-namespace`` elevates the warning to a hard failure
     so Phase 4 callers (after legacy bundle retire) can flip the
     flag and have CI block any remaining cohabitation.
  4. Single-namespace functions are NOT flagged (only ADMISSION_* or
     only APPLICATION_*).
  5. Class methods + nested function bodies are walked.
"""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app" / "scripts"))
import check_notification_event_coverage as coverage  # noqa: E402


# ---------------------------------------------------------------------------
# DualNamespacePair shape
# ---------------------------------------------------------------------------


def test_dual_namespace_pair_dataclass_shape() -> None:
    """Lock the shape so future readers know what the report carries."""
    pair = coverage.DualNamespacePair(
        file="x.py",
        function="my_func",
        line=42,
        legacy=["APPLICATION_FOO"],
        new=["ADMISSION_BAR"],
    )
    assert pair.file == "x.py"
    assert pair.function == "my_func"
    assert pair.line == 42
    assert pair.legacy == ["APPLICATION_FOO"]
    assert pair.new == ["ADMISSION_BAR"]


# ---------------------------------------------------------------------------
# _print_dual_namespace_pairs verdict
# ---------------------------------------------------------------------------


def _capture_stderr(callable_):
    buf = StringIO()
    saved = sys.stderr
    sys.stderr = buf
    try:
        rc = callable_()
    finally:
        sys.stderr = saved
    return rc, buf.getvalue()


def test_default_mode_returns_zero_with_warning() -> None:
    """Default ``strict=False`` mode emits informational ``warn`` to
    stderr and returns 0 — Phase 1 ships dual dispatch on purpose."""
    pairs = [
        coverage.DualNamespacePair(
            file="app/services/admission_service.py",
            function="approve_profile",
            line=5325,
            legacy=["APPLICATION_STATUS_CHANGED"],
            new=["ADMISSION_DECISION_ADMITTED"],
        ),
    ]
    rc, output = _capture_stderr(
        lambda: coverage._print_dual_namespace_pairs(pairs, strict=False)
    )
    assert rc == 0
    assert "warn" in output  # severity tag
    assert "approve_profile" in output
    assert "APPLICATION_STATUS_CHANGED" in output
    assert "ADMISSION_DECISION_ADMITTED" in output
    assert "informational" in output
    assert "--strict-namespace" in output


def test_strict_mode_returns_failure_count() -> None:
    """``strict=True`` returns ``len(pairs)`` so the main verdict
    elevates to exit 1 when the legacy bundle is retired."""
    pairs = [
        coverage.DualNamespacePair(
            file="x.py", function="f", line=1,
            legacy=["APPLICATION_X"], new=["ADMISSION_X"],
        ),
        coverage.DualNamespacePair(
            file="y.py", function="g", line=2,
            legacy=["APPLICATION_Y"], new=["ADMISSION_Y"],
        ),
    ]
    rc, output = _capture_stderr(
        lambda: coverage._print_dual_namespace_pairs(pairs, strict=True)
    )
    assert rc == 2
    assert "FAIL" in output
    # No "informational" footer in strict mode — output is a hard error.
    assert "informational" not in output


def test_empty_pairs_returns_zero_no_output() -> None:
    """When no functions cohabitate, the verdict is quiet — the
    report block is suppressed entirely so coverage script's other
    output stays clean."""
    rc, output = _capture_stderr(
        lambda: coverage._print_dual_namespace_pairs([], strict=False)
    )
    assert rc == 0
    assert output == ""


# ---------------------------------------------------------------------------
# AST walk — _collect_dispatches_in_function
# ---------------------------------------------------------------------------


import ast as _ast


def _function_from_source(src: str) -> _ast.AST:
    """Parse ``src`` and return the first FunctionDef."""
    tree = _ast.parse(src)
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            return node
    raise AssertionError("no function in source")


def test_collect_dispatches_finds_dual_namespace() -> None:
    """A function that fires both an ADMISSION_* and an APPLICATION_*
    event surfaces both names in the collected lists."""
    src = """
async def approve(db, profile, actor):
    await dispatch_event(db, event=SystemEvents.ADMISSION_DECISION_ADMITTED, payload={})
    await safe_dispatch(db, event=SystemEvents.APPLICATION_STATUS_CHANGED, payload={})
"""
    func = _function_from_source(src)
    legacy, new = coverage._collect_dispatches_in_function(func)
    assert "APPLICATION_STATUS_CHANGED" in legacy
    assert "ADMISSION_DECISION_ADMITTED" in new


def test_collect_dispatches_single_namespace_only() -> None:
    """A function that fires ONLY one namespace doesn't trigger the
    dual-namespace warning — it's a normal dispatch site."""
    src = """
async def submit(db, profile):
    await dispatch_event(db, event=SystemEvents.ADMISSION_PROFILE_SUBMITTED, payload={})
"""
    func = _function_from_source(src)
    legacy, new = coverage._collect_dispatches_in_function(func)
    assert legacy == []
    assert "ADMISSION_PROFILE_SUBMITTED" in new


def test_collect_dispatches_walks_nested_helpers() -> None:
    """Nested closures + helpers inherit the outer function's
    enclosing scope — both dispatches register against the outer
    function's record."""
    src = """
async def outer(db, profile):
    async def _post_commit():
        await safe_dispatch(db, event=SystemEvents.APPLICATION_STATUS_CHANGED, payload={})
    await dispatch_event(db, event=SystemEvents.ADMISSION_DECISION_ADMITTED, payload={})
    return _post_commit
"""
    func = _function_from_source(src)
    legacy, new = coverage._collect_dispatches_in_function(func)
    assert "APPLICATION_STATUS_CHANGED" in legacy
    assert "ADMISSION_DECISION_ADMITTED" in new


def test_collect_dispatches_skips_non_admission_legacy_namespaces() -> None:
    """``LEAD_*`` / ``CONSULTATION_*`` etc. don't trigger the
    namespace collision detector — only the explicit
    ``APPLICATION_*`` legacy + ``ADMISSION_*`` new pairing is in
    scope (per spec line 111)."""
    src = """
async def other(db):
    await safe_dispatch(db, event=SystemEvents.LEAD_STATUS_CHANGED, payload={})
    await dispatch_event(db, event=SystemEvents.ADMISSION_DECISION_ADMITTED, payload={})
"""
    func = _function_from_source(src)
    legacy, new = coverage._collect_dispatches_in_function(func)
    # LEAD_STATUS_CHANGED doesn't start with APPLICATION_ — skipped.
    assert legacy == []
    assert "ADMISSION_DECISION_ADMITTED" in new


# ---------------------------------------------------------------------------
# Live integration — current codebase produces at least 1 known pair
# ---------------------------------------------------------------------------


def test_live_scan_finds_submit_router_dual_dispatch() -> None:
    """End-to-end: walks the actual codebase and confirms the
    ``submit_admission_profile`` router (where #16 added the
    ADMISSION_PROFILE_SUBMITTED dispatch alongside the existing
    APPLICATION_STATUS_CHANGED bundle) shows up in the report.

    This is the canonical Phase 1 cohabitation pair — the lint MUST
    keep finding it until Phase 4 retires the legacy bundle. If this
    test fails, either:
    * the router stopped firing one of the two events (check what
      changed in admissions.py); or
    * the namespace detector regressed.
    """
    pairs = coverage._scan_dual_namespace_pairs()
    # At least one pair exists post-#16 — the router-level submit
    # flow that emits both bundles side-by-side.
    submit_pairs = [
        p for p in pairs
        if "submit_admission_profile" in p.function
    ]
    assert len(submit_pairs) >= 1, (
        f"Expected at least one dual-namespace pair from submit router; "
        f"got: {[p.function for p in pairs]}"
    )
    pair = submit_pairs[0]
    assert "APPLICATION_STATUS_CHANGED" in pair.legacy
    assert "ADMISSION_PROFILE_SUBMITTED" in pair.new
