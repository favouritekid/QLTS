"""phase1_01: add degree_level_id FK to major_program

Revision ID: phase1_01
Revises: phase1_19b
Create Date: 2026-05-03

#184 Wave 1 PR-1A — first additive migration of the Phase 1 Schema
chain (PLAN §4 line 2616-2630). Adds the FK column
``major_program.degree_level_id`` referencing the existing
``config_degree_level`` table (seeded earlier by
``l7m8n9o0p1q2_add_system_configuration_tables``). Backfills from
the legacy ``major_program.degree_level`` text column via JOIN on
``lower(trim(name))``; the per-row guard ``WHERE degree_level_id
IS NULL`` keeps re-runs idempotent.

The legacy ``degree_level`` text column STAYS for Phase 4 retire
— consumers that still rely on the text shape keep working
unchanged. New code paths read the FK; old code paths read the
text column. Both columns sit on the row until the retire wave.

Down-revision = ``phase1_19b`` (B1 Casbin deny-first backfill, the
chronological head when this migration was authored). PLAN's
nominal "phase0 → phase1_01" chain ordering is the *naming*
intent; the actual Alembic linear chain follows ship order, so
phase1_01 chains after phase1_19b (B1) which itself chained
after phase1_19a (B2.2 outbox).

Idempotency:
* Re-running the migration body (`alembic upgrade phase1_01`
  twice) is safe — Alembic gates on revision row, body never
  re-executes.
* Re-running just the backfill SQL (e.g. via psql for a partial
  recovery) is safe via the ``WHERE degree_level_id IS NULL``
  guard.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "phase1_01"
down_revision: Union[str, None] = "phase1_19b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. ADD COLUMN — nullable, no server_default. Existing rows are
    #    populated by the backfill SQL below; new rows stay honest
    #    (NULL until the caller sets the FK explicitly).
    op.add_column(
        "major_program",
        sa.Column(
            "degree_level_id",
            sa.Integer(),
            sa.ForeignKey(
                "config_degree_level.id",
                ondelete="SET NULL",
                name="fk_major_program_degree_level_id",
            ),
            nullable=True,
            comment=(
                "FK to config_degree_level. Canonical lookup for new code "
                "paths; legacy degree_level text column stays for Phase 4 "
                "retire."
            ),
        ),
    )

    # 2. Index — same shape as the existing ``ix_major_program_unit_id``
    #    pattern; the planner needs a btree on the FK for join
    #    queries against config_degree_level.
    op.create_index(
        "ix_major_program_degree_level_id",
        "major_program",
        ["degree_level_id"],
    )

    # 3. Backfill — JOIN on lower(trim(name)). Per-row idempotent
    #    guard so a partial replay (e.g. crash mid-migration, restart)
    #    skips rows already populated.
    op.execute(
        """
        UPDATE major_program mp
           SET degree_level_id = cdl.id
          FROM config_degree_level cdl
         WHERE mp.degree_level_id IS NULL
           AND lower(trim(mp.degree_level)) = lower(trim(cdl.name));
        """
    )


def downgrade() -> None:
    # Inverse order: drop index → drop column. The FK constraint is
    # implicit on the column drop; no explicit DROP CONSTRAINT needed
    # because PostgreSQL cascades the constraint with the column.
    op.drop_index(
        "ix_major_program_degree_level_id",
        table_name="major_program",
    )
    op.drop_column("major_program", "degree_level_id")
