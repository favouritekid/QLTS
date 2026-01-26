"""Add version column to lead for optimistic locking

Revision ID: opt20260125001
Revises: fsm20260125004
Create Date: 2026-01-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'opt20260125001'
down_revision = 'fsm20260125004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add version column for optimistic locking."""
    op.add_column(
        'lead',
        sa.Column(
            'version',
            sa.Integer(),
            nullable=False,
            server_default='1',
            comment='Optimistic locking version - incremented on each update'
        )
    )


def downgrade() -> None:
    """Remove version column."""
    op.drop_column('lead', 'version')
