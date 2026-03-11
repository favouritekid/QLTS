"""backfill kpi_target unit_id for officer-scoped rows

Officer-scoped KpiTarget rows created before R0.6 have unit_id=NULL
because the API didn't enforce unit_id when officer_id was set.
After R0.6, the resolver requires officer_id + unit_id match,
so these rows are invisible. This migration backfills unit_id from
the officer's current users.unit_id.

Revision ID: zg6m7n8o9p0q1
Revises: zf5l6m7n8o9p0
Create Date: 2026-03-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "zg6m7n8o9p0q1"
down_revision = "zf5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill unit_id for officer-scoped KpiTarget rows where unit_id IS NULL
    op.execute(
        sa.text("""
            UPDATE kpi_target
            SET unit_id = u.unit_id
            FROM "user" u
            WHERE kpi_target.officer_id = u.id
              AND kpi_target.officer_id IS NOT NULL
              AND kpi_target.unit_id IS NULL
              AND u.unit_id IS NOT NULL
        """)
    )

    # Same backfill for kpi_config table
    op.execute(
        sa.text("""
            UPDATE kpi_config
            SET unit_id = u.unit_id
            FROM "user" u
            WHERE kpi_config.officer_id = u.id
              AND kpi_config.officer_id IS NOT NULL
              AND kpi_config.unit_id IS NULL
              AND u.unit_id IS NOT NULL
        """)
    )


def downgrade() -> None:
    # Cannot reliably revert — we don't know which rows were NULL before
    pass
