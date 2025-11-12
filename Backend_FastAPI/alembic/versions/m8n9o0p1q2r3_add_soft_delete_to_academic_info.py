"""add soft delete to academic info

Revision ID: m8n9o0p1q2r3
Revises: l7m8n9o0p1q2
Create Date: 2025-11-12 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm8n9o0p1q2r3'
down_revision: Union[str, None] = 'l7m8n9o0p1q2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_deleted column to offering_academic_info for soft delete support.

    Academic info contains critical financial and historical data (tuition fees, quotas).
    NEVER hard delete this data - use soft delete instead.
    """
    # Add is_deleted column
    op.add_column(
        'offering_academic_info',
        sa.Column(
            'is_deleted',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Soft delete flag - NEVER hard delete academic info (financial/historical data)'
        )
    )

    # Add index for better query performance
    op.create_index(
        'ix_offering_academic_info_is_deleted',
        'offering_academic_info',
        ['is_deleted']
    )


def downgrade() -> None:
    """Remove is_deleted column."""
    op.drop_index('ix_offering_academic_info_is_deleted', table_name='offering_academic_info')
    op.drop_column('offering_academic_info', 'is_deleted')
