"""Regression test: every beat-scheduled task must be importable & registered.

Context: 2026-04-20 we discovered that ``app/tasks/__init__.py`` did not
import ``finance_tasks`` and ``collaborator_tasks``. Beat scheduled their
tasks by string name (``celery_app.conf.beat_schedule``), but the worker
never saw them → every day we lost:

- ``check_overdue_invoices_task`` (daily 05:00 VN — invoices never marked
  overdue, PAYMENT_OVERDUE never dispatched)
- ``check_ctv_attribution_expiry_task`` (daily 04:00 VN)
- ``send_ctv_weekly_summary_task`` (weekly)

Errors were silent: worker logged ``Received unregistered task of type X``
and discarded the message, no retry, no alert.

This test catches the class of bug by asserting the beat schedule and the
registry stay in sync. Any future task added to the schedule without a
matching import here will fail this test loudly.
"""
import app.tasks  # noqa: F401  — trigger registration via package __init__
from app.celery_app import celery_app


def test_every_beat_scheduled_task_is_registered():
    registered = set(celery_app.tasks.keys())
    missing = [
        (schedule_name, entry["task"])
        for schedule_name, entry in celery_app.conf.beat_schedule.items()
        if entry["task"] not in registered
    ]
    assert not missing, (
        "Beat schedules tasks that the worker cannot resolve. Each missing "
        "entry will be silently discarded every time beat fires it. Add the "
        "import to app/tasks/__init__.py. Missing:\n"
        + "\n".join(f"  - {n} -> {t}" for n, t in missing)
    )


def test_previously_unregistered_finance_and_ctv_tasks_are_registered():
    """Explicit guard for the 3 tasks that were silently failing in prod."""
    expected = [
        "check_overdue_invoices_task",
        "check_ctv_attribution_expiry_task",
        "send_ctv_weekly_summary_task",
    ]
    registered = set(celery_app.tasks.keys())
    missing = [t for t in expected if t not in registered]
    assert not missing, (
        f"Tasks regressed to unregistered state: {missing}. "
        "Check app/tasks/__init__.py imports."
    )
