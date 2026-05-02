# app/tasks/notification_outbox_tasks.py
"""T0-4a skeleton — Celery beat registration for the admission notification outbox.

This file ships **before** the outbox table and the SQLAlchemy model exist
(B2 ``EventDefinition`` extension and migration M-1-19a are still on the
admission cutover plan, not yet merged on ``feat/admission-full-cutover``).

The skeleton:

* registers the task name ``dispatch_pending_outbox`` so the beat schedule
  in ``app/celery_app.py`` can reference it without crashing the worker
  on schedule load,
* returns a small structured no-op result so dashboards / log greps written
  against the skeleton tick will not change shape when T0-4b lands,
* does **not** import ``NotificationOutbox``, query ``notification_outbox``,
  or dispatch ``SystemEvents`` — all of that is reserved for T0-4b.

Contract for T0-4b (do not break when replacing the body):

* keep the task name ``dispatch_pending_outbox`` — the beat entry
  ``dispatch-pending-outbox`` points at it.
* keep this module path so Celery autodiscover (`app.tasks`) keeps finding it.
* the result dict may grow more keys, but ``status`` and ``reason`` are
  load-bearing for the no-op tick that staging may still see during the
  cutover dry-run window.

See ``Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`` §3.5 T0-4a.
"""
import logging

from ..celery_app import celery_app


@celery_app.task(name="dispatch_pending_outbox")
def dispatch_pending_outbox() -> dict:
    """No-op tick until T0-4b ships (gated on B2 + M-1-19a).

    Returns a stable shape so:

    * `status="skipped"` — flag for any monitoring that wants to count
      ticks before the worker is wired up,
    * `reason="outbox_not_active"` — explicit reason a human can grep for
      without reading code,
    * `task_id="T0-4a"` — identifies which generation of the worker is
      running (T0-4b will switch this to ``"T0-4b"``).
    """
    task_log = logging.getLogger("dispatch_pending_outbox")
    task_log.info(
        "dispatch_pending_outbox skeleton tick: outbox not yet active "
        "(NotificationOutbox table/model gated behind B2 + M-1-19a). "
        "Returning no-op; T0-4b will replace this body."
    )
    return {
        "status": "skipped",
        "reason": "outbox_not_active",
        "task_id": "T0-4a",
    }
