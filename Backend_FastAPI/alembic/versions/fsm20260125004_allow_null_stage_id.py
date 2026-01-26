"""allow null stage_id for universal statuses

Revision ID: fsm20260125004
Revises: fsm20260125003
Create Date: 2026-01-25 19:00:00.000000

Universal statuses (activity type) don't belong to any stage,
so stage_id must be nullable.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fsm20260125004'
down_revision = 'fsm20260125003'
branch_labels = None
depends_on = None


def upgrade():
    """Allow NULL values in stage_id column."""
    op.alter_column('consultation_status', 'stage_id',
                    existing_type=sa.String(50),
                    nullable=True)


def downgrade():
    """Revert stage_id to NOT NULL (will fail if NULL values exist)."""
    op.alter_column('consultation_status', 'stage_id',
                    existing_type=sa.String(50),
                    nullable=False)
