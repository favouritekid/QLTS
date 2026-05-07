"""B2.2 — create `notification_outbox` table for guaranteed-delivery dispatch.

The 7 events flagged ``requires_outbox=True`` in ``app/core/event_catalog.py``
need durable post-commit fanout. Service-layer ``dispatch_event()`` (B2.3
sub-PR) INSERTs into this table in the same transaction as the state
change. The Celery beat task ``dispatch_pending_outbox`` (T0-4a skeleton
today, T0-4b real worker via B2.4) claims rows out-of-band and does fanout
through the existing dispatcher.

Schema mirrors PLAN §3.3.e + §3.3.f (claim/dispatch/finalize 2-column
patch). The model ``app/models/notification_outbox.py`` is the ORM half;
``tests/unit/test_notification_outbox_model.py`` locks the parity.

Idempotent guards via SQLAlchemy ``inspector``:

* table create skipped if ``notification_outbox`` already present;
* each named index skipped if already present;
* downgrade short-circuits if the table is gone, then drops indexes
  (defensive — ``DROP TABLE`` cascades indexes anyway, but explicit drops
  let a half-applied downgrade be re-run safely).

Lock-in column shape (T0-4b worker depends on it):

* BIGSERIAL ``id`` PK.
* ``event_code`` VARCHAR(64) NOT NULL — ``SystemEvents.value`` at insert.
* ``payload`` JSONB NOT NULL — dispatcher parses per template by channel.
* ``idempotency_key`` VARCHAR(128) NOT NULL UNIQUE — end-to-end dedupe.
* ``created_at`` TIMESTAMPTZ NOT NULL DEFAULT now().
* ``dispatched_at`` TIMESTAMPTZ NULL.
* ``attempts`` INT NOT NULL DEFAULT 0.
* ``last_error`` TEXT NULL.
* ``claimed_at`` TIMESTAMPTZ NULL — worker lease start.
* ``claimed_until`` TIMESTAMPTZ NULL — worker lease expiry.

Indexes (partial — keeps the hot path fast as the table grows):

* ``ix_outbox_pending`` ON (``created_at``) WHERE ``dispatched_at IS NULL``.
* ``ix_outbox_claim``   ON (``claimed_until``) WHERE ``dispatched_at IS NULL``.

Revision ID: phase1_19a
Revises: phase0br01
Create Date: 2026-05-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "phase1_19a"
down_revision: Union[str, None] = "phase0br01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Stable names — referenced by both upgrade and downgrade and locked from
# the ORM side via ``tests/unit/test_notification_outbox_model.py``.
TABLE = "notification_outbox"
INDEX_PENDING = "ix_outbox_pending"
INDEX_CLAIM = "ix_outbox_claim"
UNIQUE_IDEMPOTENCY = "uq_notification_outbox_idempotency_key"


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
            sa.UniqueConstraint("idempotency_key", name=UNIQUE_IDEMPOTENCY),
        )

    if not index_exists(TABLE, INDEX_PENDING):
        op.create_index(
            INDEX_PENDING,
            TABLE,
            ["created_at"],
            postgresql_where=sa.text("dispatched_at IS NULL"),
        )

    if not index_exists(TABLE, INDEX_CLAIM):
        op.create_index(
            INDEX_CLAIM,
            TABLE,
            ["claimed_until"],
            postgresql_where=sa.text("dispatched_at IS NULL"),
        )


def downgrade() -> None:
    # Short-circuit if the table is already gone — any earlier drop_index
    # would raise on a missing parent table.
    if not table_exists(TABLE):
        return

    if index_exists(TABLE, INDEX_CLAIM):
        op.drop_index(INDEX_CLAIM, table_name=TABLE)
    if index_exists(TABLE, INDEX_PENDING):
        op.drop_index(INDEX_PENDING, table_name=TABLE)

    op.drop_table(TABLE)
