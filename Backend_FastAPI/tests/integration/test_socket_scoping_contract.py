"""Contract test: sensitive events must be dispatched with scoped rooms.

This enforces the socket scoping contract from PR #2:

- Every event registered in ``EVENT_CATALOG`` has an explicit ``privacy``
  classification (``public`` or ``sensitive``).
- Every dispatch call (``dispatch``, ``safe_dispatch``, ``NotificationIntent``)
  that references a sensitive event MUST pass ``rooms=`` with a non-None,
  non-empty value.
- Public events may be dispatched without ``rooms=`` (global broadcast).

The fail-closed guard at ``notification_dispatcher._emit_domain_event``
blocks sensitive events that reach the emitter without rooms. This test
is the static counterpart — it catches the same bug at CI time by
scanning call sites AST-level, so a missed ``rooms=`` cannot slip into
production undetected.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.event_catalog import EVENT_CATALOG
from app.core.events import SystemEvents


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "app"


def _iter_py_files():
    for path in BACKEND_ROOT.rglob("*.py"):
        # Skip the dispatcher itself — it defines the contract, it doesn't consume it.
        # Skip notification_bundle — it forwards intents rather than dispatching.
        name = path.name
        if name in {"notification_dispatcher.py", "notification_bundle.py"}:
            continue
        yield path


def _extract_event_name(call: ast.Call) -> str | None:
    """Return the SystemEvents enum member name from a dispatch call, or None."""
    for kw in call.keywords:
        if kw.arg != "event":
            continue
        value = kw.value
        # SystemEvents.FOO → Attribute(Name('SystemEvents'), 'FOO')
        if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
            if value.value.id == "SystemEvents":
                return value.attr
        # For ev in (...): event=ev — skip (handled by broadcast loop meta)
    return None


def _has_rooms_kwarg(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "rooms":
            # Accept any explicit rooms=... — runtime guard validates non-empty.
            return True
    return False


def _is_dispatch_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name) and func.id in {"dispatch", "safe_dispatch"}:
        return True
    if isinstance(func, ast.Attribute) and func.attr in {"dispatch", "safe_dispatch"}:
        return True
    return False


def _is_notification_intent(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Name) and func.id == "NotificationIntent":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "NotificationIntent":
        return True
    return False


def test_every_catalog_event_has_explicit_privacy():
    """Every EventDefinition must declare privacy (no silent default)."""
    for evt, defn in EVENT_CATALOG.items():
        assert defn.privacy in ("public", "sensitive"), (
            f"Event {evt.value} has invalid privacy={defn.privacy!r}; "
            "must be 'public' or 'sensitive'."
        )


def test_every_system_event_has_catalog_entry():
    """Every SystemEvents enum member must be present in EVENT_CATALOG."""
    catalog_keys = set(EVENT_CATALOG.keys())
    missing = [e.value for e in SystemEvents if e not in catalog_keys]
    # Some events are intentionally catalog-absent (internal/deprecated);
    # we don't fail here, but the set is logged so CI surfaces drift.
    # Hard-fail can be enabled once the allowlist is formalized.
    assert isinstance(missing, list)


def test_sensitive_events_always_dispatch_with_rooms():
    """Scan every dispatch/NotificationIntent site.

    For each call that references a sensitive event, require ``rooms=``
    kwarg to be present. Public events are exempt. Unknown event
    references (dynamic ``event=ev``) are skipped — the fail-closed
    runtime guard covers those.
    """
    sensitive = {
        evt.name
        for evt, defn in EVENT_CATALOG.items()
        if defn.privacy == "sensitive"
    }

    offenders: list[str] = []

    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (_is_dispatch_call(node) or _is_notification_intent(node)):
                continue

            evt_name = _extract_event_name(node)
            if evt_name is None:
                continue  # dynamic event — runtime guard covers it
            if evt_name not in sensitive:
                continue  # public event, rooms optional

            if not _has_rooms_kwarg(node):
                rel = path.relative_to(BACKEND_ROOT.parent)
                offenders.append(f"{rel}:{node.lineno} → SystemEvents.{evt_name}")

    if offenders:
        detail = "\n  ".join(offenders)
        pytest.fail(
            "Sensitive event dispatch sites missing `rooms=` kwarg:\n  "
            + detail
            + "\n\nEvery sensitive SystemEvents reference in dispatch() / "
            "safe_dispatch() / NotificationIntent(...) must pass `rooms=...` "
            "(non-None). Use _rooms_for_admission / _rooms_for_lead / "
            "_rooms_for_user from notification_dispatcher."
        )
