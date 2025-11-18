"""add_soft_delete_to_lead

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2025-11-18 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't5u6v7w8x9y0'
down_revision: Union[str, None] = 's4t5u6v7w8x9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add soft delete support to Lead model.

    Changes:
    - Add deleted_at column (nullable DateTime with timezone, indexed)

    Impact:
    - Existing leads will have deleted_at = NULL (active)
    - Future delete operations will set deleted_at timestamp instead of hard delete
    - Queries need to filter WHERE deleted_at IS NULL to exclude deleted leads
    """
    # Add deleted_at column to lead table
    op.add_column(
        'lead',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)
    )

    # Add index for soft delete filtering (improves query performance)
    op.create_index(
        op.f('ix_lead_deleted_at'),
        'lead',
        ['deleted_at'],
        unique=False
    )


def downgrade() -> None:
    """
    Remove soft delete support from Lead model.

    WARNING: This will permanently delete all soft-deleted leads!
    Only run this if you're sure you want to remove the soft delete feature.
    """
    # Drop index first
    op.drop_index(op.f('ix_lead_deleted_at'), table_name='lead')

    # Drop deleted_at column
    op.drop_column('lead', 'deleted_at')
