"""add timestamps to organization unit

Revision ID: o0p1q2r3s4t5
Revises: n9o0p1q2r3s4
Create Date: 2025-11-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'o0p1q2r3s4t5'
down_revision: Union[str, None] = 'n9o0p1q2r3s4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add created_at and updated_at audit trail columns to organization_unit table.

    These timestamps track when units are created and last modified, which is important
    for auditing, reporting, and understanding organizational structure changes over time.
    """
    # Add created_at column
    op.add_column(
        'organization_unit',
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
            comment='Timestamp when unit was created'
        )
    )

    # Add updated_at column
    op.add_column(
        'organization_unit',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
            comment='Timestamp when unit was last updated'
        )
    )

    # Add index on created_at for sorting/filtering by creation date
    op.create_index(
        'ix_organization_unit_created_at',
        'organization_unit',
        ['created_at']
    )


def downgrade() -> None:
    """Remove timestamp columns."""
    op.drop_index('ix_organization_unit_created_at', table_name='organization_unit')
    op.drop_column('organization_unit', 'updated_at')
    op.drop_column('organization_unit', 'created_at')
