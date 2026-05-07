"""Unit tests for #184 Wave 5-B migration ``phase1_19d_register_celery_beat_archive_task``
plus the paired Celery code edits (``app/celery_app.py`` beat entry +
``app/tasks/notification_outbox_tasks.py`` task body).

Pattern B-i: the alembic migration is a marker (``upgrade`` /
``downgrade`` are no-ops); the actual change is the Celery beat
registration + task body. Tests cover all three surfaces:

1. Migration revision chain + body=pass marker.
2. Beat schedule entry shape (key + task name + Sunday 02:00 crontab +
   queue).
3. Task body contract: name, callable, zero-arg, retention constant,
   single-statement atomic CTE (text grep), correct column projection
   for archive INSERT (no ``archived_at`` — relies on
   ``server_default=now()`` from ``phase1_17``).
4. Task name registers under the celery app after ``app.tasks`` import.
5. Result-dict validation keys honored (`status`, `archived_count`,
   `task_id`).

What does NOT live here:

* End-to-end SQL execution against a real DB — defer to staging clone
  D12-D14 alongside the rest of Wave 5 live alembic roundtrip.
* Worker pattern coverage of ``dispatch_pending_outbox`` —
  ``test_outbox_worker.py`` owns that.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest
from celery.schedules import crontab


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_19D = (
    _VERSIONS_DIR / "phase1_19d_register_celery_beat_archive_task.py"
)
_TASKS_FILE = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "tasks"
    / "notification_outbox_tasks.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_19D.stem, _PHASE1_19D)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_19d():
    return _load_migration()


# ---------------------------------------------------------------------------
# 1. Migration revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_19d_revision_id(phase1_19d) -> None:
    assert phase1_19d.revision == "phase1_19d"


def test_phase1_19d_chains_off_phase1_17(phase1_19d) -> None:
    """Wave 5-B runs after Wave 5-E so the archive table that the task
    body writes to (``_archived_notification_outbox``) already exists."""
    assert phase1_19d.down_revision == "phase1_17"


# ---------------------------------------------------------------------------
# 2. Migration is B-i marker (no-op)
# ---------------------------------------------------------------------------


def test_phase1_19d_upgrade_body_is_marker(phase1_19d) -> None:
    """B-i pattern — paired Celery code carries the actual change. The
    migration must NOT call any ``op.*`` DDL helper."""
    src = _PHASE1_19D.read_text(encoding="utf-8")
    # The string ``op.`` must not appear inside the upgrade() / downgrade()
    # function bodies (the docstring above does NOT contain ``op.``).
    upgrade_body = src[src.index("def upgrade()") : src.index("def downgrade()")]
    downgrade_body = src[src.index("def downgrade()"):]
    assert "op." not in upgrade_body
    assert "op." not in downgrade_body


def test_phase1_19d_callable_upgrade_and_downgrade(phase1_19d) -> None:
    assert callable(getattr(phase1_19d, "upgrade", None))
    assert callable(getattr(phase1_19d, "downgrade", None))


# ---------------------------------------------------------------------------
# 3. Beat schedule entry
# ---------------------------------------------------------------------------


def test_beat_schedule_registers_archive_outbox_dispatched():
    """Sunday 02:00 VN weekly per PLAN line 168-178 P1 fix #8 — low-traffic
    slot, no conflict with daily KPI / cleanup ticks at 00:05 / 01:00 /
    02:00 day-1 / 02:30 / 03:00 / 03:15 / 04:00 / 05:00 / 07:00 / 09:00."""
    from app.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "archive-outbox-dispatched" in schedule, (
        "beat entry `archive-outbox-dispatched` is missing — "
        "Wave 5-B M-1-19d depends on this weekly cadence"
    )

    entry = schedule["archive-outbox-dispatched"]
    assert entry["task"] == "archive_outbox_dispatched_task"
    assert entry["options"] == {"queue": "default"}


def test_beat_schedule_archive_runs_sunday_two_am():
    """The schedule object is a ``celery.schedules.crontab`` set to
    ``hour=2, minute=0, day_of_week='sunday'``. We verify each field via
    the public crontab attributes rather than the repr."""
    from app.celery_app import celery_app

    sched = celery_app.conf.beat_schedule["archive-outbox-dispatched"]["schedule"]
    assert isinstance(sched, crontab), (
        f"archive sweep must be a crontab schedule; got {type(sched).__name__}"
    )
    assert sched.hour == {2}
    assert sched.minute == {0}
    # ``day_of_week='sunday'`` parses to the sunday set ({0}).
    assert sched.day_of_week == {0}


# ---------------------------------------------------------------------------
# 4. Task module contract
# ---------------------------------------------------------------------------


def test_archive_task_callable_zero_arg():
    """Beat fires the task with no args — its signature must accept zero
    positional args."""
    from app.tasks.notification_outbox_tasks import archive_outbox_dispatched_task

    sig = inspect.signature(archive_outbox_dispatched_task)
    required = [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    assert required == [], (
        f"archive_outbox_dispatched_task must accept zero required args; "
        f"got {required}"
    )


def test_archive_task_name_registered_under_celery_app():
    """After ``import app.tasks``, the task name string must resolve in
    ``celery_app.tasks`` so beat dispatch does not silently drop messages."""
    import app.tasks  # noqa: F401 — registers tasks on the celery app

    from app.celery_app import celery_app

    assert "archive_outbox_dispatched_task" in celery_app.tasks, (
        "archive_outbox_dispatched_task is not registered — "
        "beat will fire with no consumer"
    )


def test_archive_retention_constant_is_ninety_days():
    """PLAN line 168 mandates 90-day retention. Surface as a constant so
    tests + ops can reason about it without grepping a magic number."""
    from app.tasks.notification_outbox_tasks import ARCHIVE_RETENTION_DAYS

    assert ARCHIVE_RETENTION_DAYS == 90


# ---------------------------------------------------------------------------
# 5. SQL contract (text grep — execution defers to D12-D14 staging clone)
# ---------------------------------------------------------------------------


def test_archive_task_uses_single_statement_cte_move():
    """PLAN line 170-176 specifies a single CTE: DELETE...RETURNING *
    feeds INSERT INTO archive. Splitting into two statements (DELETE
    then INSERT) opens a data-loss window if the worker crashes in
    between. This text grep guards against the split."""
    src = _TASKS_FILE.read_text(encoding="utf-8")
    # The CTE must wrap the DELETE so RETURNING flows into the INSERT.
    assert "WITH archived AS (" in src
    assert "DELETE FROM notification_outbox" in src
    assert "RETURNING id, event_code" in src
    assert "INSERT INTO _archived_notification_outbox" in src
    assert "SELECT * FROM archived" in src


def test_archive_task_uses_retention_parameter_not_hardcoded():
    """The retention window is parameterized (``:retention_days``) so the
    constant ``ARCHIVE_RETENTION_DAYS`` is the single source of truth.
    Hardcoding ``INTERVAL '90 days'`` would let the constant drift from
    the SQL silently."""
    src = _TASKS_FILE.read_text(encoding="utf-8")
    assert "make_interval(days => :retention_days)" in src
    assert "INTERVAL '90 days'" not in src


def test_archive_task_does_not_explicit_archived_at_in_insert():
    """``phase1_17`` ships ``archived_at`` with ``server_default=now()``
    — the cron INSERT must NOT specify it explicitly, so the default
    fires automatically. Specifying it would couple the cron to the
    archive table's metadata column shape."""
    src = _TASKS_FILE.read_text(encoding="utf-8")
    insert_block = src[src.index("INSERT INTO _archived_notification_outbox") :]
    insert_columns = insert_block[: insert_block.index(")")]
    # The 10-column projection must exclude ``archived_at``.
    assert '"archived_at"' not in insert_columns
    assert " archived_at" not in insert_columns


def test_archive_task_filters_only_dispatched_rows():
    """``dispatched_at IS NOT NULL`` AND ``dispatched_at < NOW() -
    make_interval(...)`` filter — pending rows (still IS NULL) MUST be
    preserved. Dropping the IS NOT NULL guard would archive pending
    rows."""
    src = _TASKS_FILE.read_text(encoding="utf-8")
    where_block = src[src.index("DELETE FROM notification_outbox") :]
    where_block = where_block[: where_block.index("RETURNING")]
    assert "dispatched_at IS NOT NULL" in where_block
    assert "dispatched_at < NOW() - make_interval(days => :retention_days)" in where_block


# ---------------------------------------------------------------------------
# 6. Result dict shape
# ---------------------------------------------------------------------------


def test_archive_task_validate_keys_match_documented_shape():
    """``run_async_task(validate_keys=...)`` enforces the result-dict
    shape. Ops monitoring + alerting depend on the exact keys."""
    src = _TASKS_FILE.read_text(encoding="utf-8")
    # The validate_keys list is on a single line: lock its content.
    assert (
        'validate_keys=["status", "archived_count", "task_id"]' in src
    ), "validate_keys must be exactly status + archived_count + task_id"
