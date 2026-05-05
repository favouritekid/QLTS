"""Wave 5-B / M-1-19d — register weekly outbox archive task (B-i marker).

Pattern B-i marker migration. Alembic does NOT manage the Celery beat
schedule (per ``app/celery_app.py:118-255`` static-dict pattern — no
DatabaseScheduler), so the actual change ships in two paired code edits:

* ``app/celery_app.py`` adds ``"archive-outbox-dispatched"`` beat entry
  pointed at ``archive_outbox_dispatched_task`` with a Sunday 02:00 VN
  weekly schedule (low-traffic window per existing slot map at
  ``app/celery_app.py:118-255`` — no conflict with KPI / cleanup /
  reminder ticks).
* ``app/tasks/notification_outbox_tasks.py`` adds the task body.

This migration carries the **schema-side commitment** that the archive
table from ``phase1_17`` (Wave 5-E PR #215 squash ``0b17f394``) is
considered the canonical destination for the archive cron's MOVE
operation. The body is a no-op because the DDL was already applied in
``phase1_17``; this revision exists so the alembic history records the
same version-control point that the paired Celery code change locks in.

Cron semantic recap (PLAN line 168-178 — P1 fix #8 outbox 90-day archive)
------------------------------------------------------------------------

```sql
WITH archived AS (
    DELETE FROM notification_outbox
    WHERE dispatched_at IS NOT NULL
      AND dispatched_at < NOW() - INTERVAL '90 days'
    RETURNING id, event_code, payload, idempotency_key, created_at,
              dispatched_at, attempts, last_error, claimed_at, claimed_until
)
INSERT INTO _archived_notification_outbox (
    id, event_code, payload, idempotency_key, created_at,
    dispatched_at, attempts, last_error, claimed_at, claimed_until
)
SELECT * FROM archived;
```

Single-statement atomic move. The archive table's ``archived_at`` column
auto-populates via the ``server_default=now()`` set in ``phase1_17``.
``DELETE...RETURNING *`` snapshot feeds the INSERT in the same
transaction — no second SELECT, no data-loss window.

Idempotent guard
----------------

A marker-only migration has no idempotency surface to guard. Re-running
``alembic upgrade head`` after the chain reaches this revision is a
no-op (Alembic skips already-applied revisions). Re-running ``upgrade``
explicitly (e.g. via ``alembic upgrade phase1_19d --sql``) emits the
empty body with no DDL.

Revision ID: phase1_19d
Revises: phase1_17
Create Date: 2026-05-05
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "phase1_19d"
down_revision: Union[str, None] = "phase1_17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """B-i marker — paired Celery code in ``app/celery_app.py`` and
    ``app/tasks/notification_outbox_tasks.py`` carries the actual change.

    Schema commitment: ``phase1_17`` already created
    ``_archived_notification_outbox``; this revision locks in the
    version-control point for the archive cron beat registration that
    the paired code change adds.
    """
    pass


def downgrade() -> None:
    """No-op — paired code change must be reverted in the application
    repo separately. The archive table itself rolls back via
    ``phase1_17``'s downgrade (drop_index + drop_table)."""
    pass
