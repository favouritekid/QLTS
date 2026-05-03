"""Outbox worker registration + safety contract.

Originally shipped with T0-4a (skeleton task before B2 + M-1-19a)
under the name "skeleton tests". After B2.4 / T0-4b retired the
skeleton in favor of the real claim/dispatch/finalize body, this
file keeps the **registration / discoverability** half of the
contract — the things every consumer of
``celery_app.send_task("dispatch_pending_outbox", ...)`` relies on
regardless of which generation of the worker ships it.

Retired in B2.4 (worker body landed):

* ``test_skeleton_module_does_not_reference_notification_outbox_in_code``
  — the model + table now exist (B2.2 / M-1-19a), and the worker
  module legitimately calls into ``SystemEvents`` / ``get_event``
  / ``dispatch`` to drain the table. Positive worker coverage
  lives in ``tests/unit/test_outbox_worker.py``.
* ``test_skeleton_call_returns_stable_no_op_shape`` — the result
  dict shape changed in B2.4 (status / claimed / dispatched /
  failed / task_id="T0-4b"). Re-asserted by the worker tests.

Kept (still applies to the real worker):

* Beat schedule entry + cadence.
* ``celery_app.conf.include`` lists ``app.tasks``.
* Cold-import (subprocess) registration guard.
* In-process registration guard after ``import app.tasks``.
* ``dispatch_pending_outbox`` exported from the tasks package.
* Autodiscover smoke (no syntax error / bad import).
* Zero-required-argument signature (beat fires with no args).
* ``app/tasks/__init__.py`` AST guard against accidental
  ``NotificationOutbox`` re-export.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


# --- Module path constants -------------------------------------------------

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
TASKS_INIT_PATH = REPO_BACKEND_ROOT / "app" / "tasks" / "__init__.py"


# --- Beat schedule contract ----------------------------------------------


def test_beat_schedule_registers_dispatch_pending_outbox_every_30s():
    from app.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "dispatch-pending-outbox" in schedule, (
        "beat schedule entry `dispatch-pending-outbox` is missing — "
        "T0-4a / T0-4b both depend on this 30s cadence"
    )

    entry = schedule["dispatch-pending-outbox"]
    assert entry["task"] == "dispatch_pending_outbox", (
        f"beat entry must point at task name `dispatch_pending_outbox`, "
        f"got {entry['task']!r}"
    )
    assert entry["schedule"] == 30.0, (
        f"30s cadence per RUNBOOK §3.5; got {entry['schedule']!r}"
    )


# --- Task registry contract ----------------------------------------------


def test_celery_app_explicitly_includes_app_tasks_package():
    """Static guard: `celery_app.conf.include` must list `app.tasks`.

    Worker entrypoint `celery -A app.celery_app worker/beat` imports only
    `app.celery_app`. Celery resolves `conf.include` (and `conf.imports`)
    at `loader.import_default_modules()` during boot, which is the canonical
    way to make business tasks register without relying on the
    `autodiscover_tasks` package-walking heuristic. If this list ever
    becomes empty the beat schedule will fire `dispatch_pending_outbox`
    against a worker that does not know it and the message is silently
    discarded.
    """
    from app.celery_app import celery_app

    include = list(celery_app.conf.include or [])
    assert "app.tasks" in include, (
        "celery_app.conf.include must include 'app.tasks' so the worker "
        f"entrypoint registers business tasks at boot. Current include: {include}"
    )


def test_worker_entrypoint_registers_outbox_task_without_explicit_app_tasks_import():
    """Cold-import contract: a fresh Python interpreter that does ONLY
    ``from app.celery_app import celery_app`` must see
    ``dispatch_pending_outbox`` already in ``celery_app.tasks``.

    Why this test runs in a subprocess: pytest keeps imported modules in
    ``sys.modules`` for the whole session, so once any earlier test loads
    ``app.tasks`` the registry stays populated and an in-process check would
    silently pass even if the worker entrypoint were broken.

    Why no manual ``finalize()`` or ``import_default_modules()``: ``celery
    -A app.celery_app worker/beat`` does call ``import_default_modules``
    during boot, but other consumers (the FastAPI process pulling in
    ``celery_utils`` to ``.delay()`` a task, ad-hoc REPL inspection, the
    pytest helpers used by other test files) only do the bare import.
    Registration must work on *that* path too — otherwise
    ``celery_app.send_task("dispatch_pending_outbox", ...)`` from those
    callers fires against an empty registry. The fix is the explicit
    ``import app.tasks`` at the bottom of ``app/celery_app.py``.
    """
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent(
        """
        # Cold import only — no finalize, no import_default_modules.
        from app.celery_app import celery_app

        if "dispatch_pending_outbox" in celery_app.tasks:
            print("REGISTERED")
        else:
            non_builtin = sorted(
                t for t in celery_app.tasks if not t.startswith("celery.")
            )
            print(f"MISSING; non_builtin_tasks={non_builtin}")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "REGISTERED" in result.stdout, (
        "Cold `from app.celery_app import celery_app` did NOT register "
        "dispatch_pending_outbox. Beat would queue this task against any "
        "consumer that has not already imported `app.tasks`, and the worker/"
        "FastAPI side would silently discard it as unregistered.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_dispatch_pending_outbox_registers_after_app_tasks_import():
    """Companion sanity: with the explicit `import app.tasks` path, the task
    is in the registry. This catches regression A (a task module missing
    from `app/tasks/__init__.py`); regression B (worker-entrypoint
    cold-import) is covered by the subprocess test above.
    """
    import app.tasks  # noqa: F401  — trigger package __init__

    from app.celery_app import celery_app

    assert "dispatch_pending_outbox" in celery_app.tasks, (
        "Celery did not register `dispatch_pending_outbox` even after "
        "`import app.tasks`. Check `app/tasks/__init__.py` imports and the "
        "`@celery_app.task` decorator on the worker."
    )


def test_dispatch_pending_outbox_exported_from_tasks_package():
    """Lock the import surface so consumers can do `from app.tasks import dispatch_pending_outbox`."""
    from app.tasks import dispatch_pending_outbox

    assert callable(dispatch_pending_outbox)


# --- Tasks package __init__ AST guard --------------------------------------


def _ast_references_to_notification_outbox(src: str) -> list[str]:
    """Return human-readable AST hits for ``NotificationOutbox`` in real code.

    Walks the parse tree and looks at imports, name refs, and attribute
    references. Docstrings and comments are intentionally ignored — they're
    the legitimate place to *explain why we're NOT importing the model*.
    """
    import ast

    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "NotificationOutbox":
                    hits.append(f"line {node.lineno}: from-import")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "NotificationOutbox" in alias.name.split("."):
                    hits.append(f"line {node.lineno}: import")
        elif isinstance(node, ast.Name) and node.id == "NotificationOutbox":
            hits.append(f"line {node.lineno}: name reference")
        elif isinstance(node, ast.Attribute) and node.attr == "NotificationOutbox":
            hits.append(f"line {node.lineno}: attribute reference")
    return hits


def test_tasks_package_init_does_not_reference_notification_outbox_in_code():
    """``app/tasks/__init__.py`` should re-export task callables only, not
    leak the ORM model into the package import surface. Worker code can
    import ``NotificationOutbox`` directly from ``app.models``; the tasks
    package itself stays model-free."""
    src = TASKS_INIT_PATH.read_text(encoding="utf-8")
    hits = _ast_references_to_notification_outbox(src)
    assert not hits, (
        "Tasks package __init__ now references NotificationOutbox in CODE; "
        "the package should only re-export task callables. "
        f"Hits in {TASKS_INIT_PATH}:\n  - " + "\n  - ".join(hits)
    )


# --- Worker-load smoke: autodiscover does not crash with the worker ------


def test_celery_autodiscover_loads_outbox_task_module():
    """If the worker module had a syntax error or bad import, this would raise."""
    spec = importlib.util.find_spec("app.tasks.notification_outbox_tasks")
    assert spec is not None, "module spec missing — package layout drift"

    module = importlib.import_module("app.tasks.notification_outbox_tasks")
    assert hasattr(module, "dispatch_pending_outbox")

    # Confirm the symbol is a Celery Task object (decorator was applied).
    task = module.dispatch_pending_outbox
    assert getattr(task, "name", None) == "dispatch_pending_outbox", (
        f"Decorator did not register the task name correctly; "
        f"got name={getattr(task, 'name', None)!r}"
    )


# --- Source quality: callable signature is stable across T0-4a/T0-4b -------


def test_dispatch_pending_outbox_takes_no_required_arguments():
    """Beat fires the task with no args, so the signature must accept
    zero required args. This contract holds across the T0-4a → T0-4b
    body swap."""
    from app.tasks.notification_outbox_tasks import dispatch_pending_outbox

    raw = getattr(dispatch_pending_outbox, "run", dispatch_pending_outbox)
    sig = inspect.signature(raw)
    required = [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    assert not required, (
        f"dispatch_pending_outbox must accept zero required args (beat fires "
        f"with none); required parameters found: {[p.name for p in required]}"
    )
