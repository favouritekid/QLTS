"""PATCH-20 — create `_archived_notification_outbox` table for 90-day archive.

Companion to ``phase1_16`` (Wave 5-D archive table for admission profile).
PLAN line 168-178 (Phần 1 #08 fix) + cheat sheet line 3464-3468 + slot
assignment §8 line 4492 ship 2 archive tables under PATCH-20:

* ``_archived_admission_profile`` (phase1_16, Wave 5-D ✅ shipped PR #214)
* ``_archived_notification_outbox`` (this migration, slot phase1_17, Wave 5-E)

The cron ``archive_outbox_dispatched_task`` (NOT shipped here — paired with
Wave 5-B ``phase1_19d`` Celery beat registration which depends on this table
existing) runs weekly and MOVES rows whose ``dispatched_at`` is older than 90
days from the live ``notification_outbox`` into this archive. Per PLAN line
3464-3468 the archive holds BOTH dispatched and failed (DLQ) outbox rows
post-90-days, NOT only failed.

Cron semantic (PLAN line 170-176)
---------------------------------

```sql
WITH archived AS (
    DELETE FROM notification_outbox
    WHERE dispatched_at IS NOT NULL
      AND dispatched_at < NOW() - INTERVAL '90 days'
    RETURNING *
)
INSERT INTO _archived_notification_outbox SELECT * FROM archived;
```

This is a MOVE (DELETE + INSERT), unlike Wave 5-D's COPY pattern where the
source profile row is preserved. The cron's RETURNING-clause snapshot is
enough to populate the archive INSERT — no second SELECT needed.

Schema parity rules
-------------------

* Mirror the 10 columns of ``notification_outbox`` exactly (types +
  nullability + server_default) so the cron CTE INSERT has perfect column
  alignment.
* + 1 archive-metadata column ``archived_at TIMESTAMPTZ NOT NULL DEFAULT
  now()`` — set automatically when cron INSERTs the archive row.
* NO foreign keys (the source notification_outbox has no FKs either).
* NO unique constraints — the source ``idempotency_key`` UNIQUE is dropped
  on the archive side. Reason: archived rows are by definition outside the
  worker's dedupe window (they're 90+ days dispatched), so the live UNIQUE
  contract no longer needs to extend across the archive table. Dropping it
  also keeps the archive append-only even in the unlikely event a stale
  worker re-INSERTs an idempotency_key that has since been archived.
* NO check constraints — archive must round-trip historical rows even if
  the live table contract evolves.
* NO partial indexes — the source's ``ix_outbox_pending`` /
  ``ix_outbox_claim`` are partial WHERE ``dispatched_at IS NULL`` filters
  serving the worker's claim path. Every archived row has
  ``dispatched_at IS NOT NULL`` (the cron's archive predicate), so the
  partial filter would match zero rows on the archive side — the indexes
  are useless here and we drop them.

Archive index
-------------

``ix_archived_outbox_archived_at`` on ``archived_at`` — Option II chốt
2026-05-05. PLAN does NOT mandate an archive-side index (line 168-178 + 3464
silent), but the typical admin query against the archive is a time-range
debug ("show me rows archived in window X-Y", weekly archive volume report,
forensic lookup post-incident). Indexing ``archived_at`` keeps that query
fast as the archive grows toward the 60-180k-row 5-year ceiling that
motivated this archive policy in the first place. ``dispatched_at`` was
considered (Option III) but rejected — every archived row has
``dispatched_at < NOW() - 90 days`` by definition, so an index there has low
selectivity for the typical admin query.

Idempotent guards via SQLAlchemy ``inspector`` mirror the ``phase1_19a``
template (PR #198) and ``phase1_16`` (PR #214):

* table create skipped if ``_archived_notification_outbox`` already present;
* named index skipped if already present;
* downgrade short-circuits if the table is gone.

Defer to follow-up (NOT in Wave 5-E D-i scope)
----------------------------------------------

* ORM class ``ArchivedNotificationOutbox`` — ship together with whichever
  caller needs to query the archive (none today; deferred until forensic
  query or DLQ-replay tooling lands).
* ``archive_outbox_dispatched_task`` itself — ship in Wave 5-B
  ``phase1_19d`` paired with the Celery beat registration (the marker
  migration registers the schedule entry; the task body lives in
  ``app/tasks/notification_outbox_tasks.py`` and references THIS table).

Revision ID: phase1_17
Revises: phase1_16
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "phase1_17"
down_revision: Union[str, None] = "phase1_16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "_archived_notification_outbox"
INDEX_ARCHIVED_AT = "ix_archived_outbox_archived_at"


def table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not table_exists(TABLE):
        op.create_table(
            TABLE,
            # ── Mirror notification_outbox columns (FK/UQ/CHECK omitted) ──
            sa.Column(
                "id",
                sa.BigInteger(),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column("event_code", sa.String(64), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "attempts",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
            # ── Archive metadata (1 column only) ──
            sa.Column(
                "archived_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not index_exists(TABLE, INDEX_ARCHIVED_AT):
        op.create_index(
            INDEX_ARCHIVED_AT,
            TABLE,
            ["archived_at"],
        )


def downgrade() -> None:
    if not table_exists(TABLE):
        return

    if index_exists(TABLE, INDEX_ARCHIVED_AT):
        op.drop_index(INDEX_ARCHIVED_AT, table_name=TABLE)

    op.drop_table(TABLE)
