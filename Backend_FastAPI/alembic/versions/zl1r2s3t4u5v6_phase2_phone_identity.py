"""phase2: create lead_phone_identity table with partial unique index

Revision ID: zl1r2s3t4u5v6
Revises: zk0q1r2s3t4u5
Create Date: 2026-03-14 14:00:00.000000

PR3 — True Phone Identity Model.

Creates a normalized phone identity table where each phone number maps to
exactly one active lead. Eliminates the cross-column TOCTOU race between
lead.phone and lead.phone2 by enforcing uniqueness at the DB level via a
partial unique index: WHERE deleted_at IS NULL.

Steps:
  1. Create table lead_phone_identity
  2. Create partial unique index uq_lead_phone_active
  3. Backfill from existing active leads (phone + phone2)

KNOWN LIMITATIONS of this backfill (resolved by follow-up zm2s3t4u5v6w7):

  - Uses ON CONFLICT DO NOTHING: if two active leads share the same raw
    phone value (same-slot or cross-slot phone vs phone2), the second
    insert is silently dropped — that lead becomes an orphan.
  - Inserts raw phone values (not normalized): two phones that differ only
    in format (+84901234567 vs 0901234567) are treated as distinct here
    but would collide after normalization.
  - The follow-up migration (zm2s3t4u5v6w7) audits for orphaned leads and
    detects post-normalization conflicts, failing fast in both cases.

PREFLIGHT (run before applying):
  -- 1. Same-slot duplicates
  SELECT phone, count(*) FROM lead
    WHERE deleted_at IS NULL AND phone IS NOT NULL AND phone != ''
    GROUP BY phone HAVING count(*) > 1;
  SELECT phone2, count(*) FROM lead
    WHERE deleted_at IS NULL AND phone2 IS NOT NULL AND phone2 != ''
    GROUP BY phone2 HAVING count(*) > 1;

  -- 2. Cross-slot duplicates (lead A phone = lead B phone2)
  SELECT a.id AS lead_a, a.phone, b.id AS lead_b, b.phone2
    FROM lead a JOIN lead b ON a.phone = b.phone2
    WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL AND a.id != b.id;

  If any rows returned, resolve before running migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "zl1r2s3t4u5v6"
down_revision: Union[str, None] = "zk0q1r2s3t4u5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create table
    op.create_table(
        "lead_phone_identity",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("phone_normalized", sa.String(20), nullable=False),
        sa.Column("slot", sa.String(10), nullable=False, comment="'phone' or 'phone2'"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_phone_identity_lead_id", "lead_phone_identity", ["lead_id"])
    op.create_index("ix_lead_phone_identity_phone_normalized", "lead_phone_identity", ["phone_normalized"])
    op.create_index("ix_lead_phone_identity_deleted_at", "lead_phone_identity", ["deleted_at"])

    # 2. Create partial unique index (the core constraint)
    op.execute(
        text(
            "CREATE UNIQUE INDEX uq_lead_phone_active "
            "ON lead_phone_identity (phone_normalized) "
            "WHERE deleted_at IS NULL"
        )
    )

    # 3. Backfill from existing active leads
    # Insert phone (slot='phone') for all active leads with non-null phone
    # Use ON CONFLICT DO NOTHING to gracefully handle duplicate phones
    # (if two active leads share a phone, only the first one wins)
    op.execute(
        text(
            "INSERT INTO lead_phone_identity (lead_id, phone_normalized, slot, deleted_at) "
            "SELECT id, phone, 'phone', NULL "
            "FROM lead "
            "WHERE deleted_at IS NULL AND phone IS NOT NULL AND phone != '' "
            "ON CONFLICT DO NOTHING"
        )
    )

    # Insert phone2 (slot='phone2') for all active leads with non-null phone2
    op.execute(
        text(
            "INSERT INTO lead_phone_identity (lead_id, phone_normalized, slot, deleted_at) "
            "SELECT id, phone2, 'phone2', NULL "
            "FROM lead "
            "WHERE deleted_at IS NULL AND phone2 IS NOT NULL AND phone2 != '' "
            "ON CONFLICT DO NOTHING"
        )
    )

    # Also backfill soft-deleted leads (with deleted_at matching lead.deleted_at)
    op.execute(
        text(
            "INSERT INTO lead_phone_identity (lead_id, phone_normalized, slot, deleted_at) "
            "SELECT id, phone, 'phone', deleted_at "
            "FROM lead "
            "WHERE deleted_at IS NOT NULL AND phone IS NOT NULL AND phone != ''"
        )
    )
    op.execute(
        text(
            "INSERT INTO lead_phone_identity (lead_id, phone_normalized, slot, deleted_at) "
            "SELECT id, phone2, 'phone2', deleted_at "
            "FROM lead "
            "WHERE deleted_at IS NOT NULL AND phone2 IS NOT NULL AND phone2 != ''"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uq_lead_phone_active"))
    op.drop_table("lead_phone_identity")
