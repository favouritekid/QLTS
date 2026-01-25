"""add display_order to consultation_status

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-25 14:05:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add display_order to consultation_status table for sorting.

    This field controls the order in which statuses appear in UI dropdowns
    and FSM transition lists.
    """
    # Add display_order column
    op.add_column('consultation_status',
        sa.Column('display_order',
                  sa.Integer(),
                  nullable=False,
                  server_default='0',
                  comment="Sort order for displaying statuses (lower = first)")
    )

    # Create index for sorting queries
    op.create_index('ix_consultation_status_display_order',
                   'consultation_status',
                   ['display_order'])


def downgrade():
    """Remove display_order from consultation_status table."""
    op.drop_index('ix_consultation_status_display_order', table_name='consultation_status')
    op.drop_column('consultation_status', 'display_order')
