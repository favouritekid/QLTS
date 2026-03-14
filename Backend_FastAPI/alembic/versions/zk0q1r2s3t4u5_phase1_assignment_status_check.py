"""phase1: add CHECK constraint for assignment_status

Revision ID: zk0q1r2s3t4u5
Revises: zj9p0q1r2s3t4
Create Date: 2026-03-14 12:01:00.000000

P0 safe-hardening: Enforce assignment_status values at DB level.
Previously only validated in app layer via StatusHelper.set_assignment_status().

Production caveat:
  If existing data contains values outside the allowed set, this migration
  will FAIL. Run the diagnostic query below before deploying:

    SELECT DISTINCT assignment_status, count(*)
    FROM lead
    GROUP BY assignment_status;

  Only 'pending', 'assigned', 'failed', 'reassign_pending' are allowed.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "zk0q1r2s3t4u5"
down_revision: Union[str, None] = "zj9p0q1r2s3t4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text(
            "ALTER TABLE lead ADD CONSTRAINT ck_lead_assignment_status "
            "CHECK (assignment_status IN ('pending', 'assigned', 'failed', 'reassign_pending'))"
        )
    )


def downgrade() -> None:
    op.execute(
        text("ALTER TABLE lead DROP CONSTRAINT IF EXISTS ck_lead_assignment_status")
    )
