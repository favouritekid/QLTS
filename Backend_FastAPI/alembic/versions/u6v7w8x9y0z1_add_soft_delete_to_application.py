"""add_soft_delete_to_application

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2025-11-18 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'u6v7w8x9y0z1'
down_revision: Union[str, None] = 't5u6v7w8x9y0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add soft delete support to Application model.

    Changes:
    - Add deleted_at column (nullable DateTime with timezone, indexed)

    Impact:
    - Existing applications will have deleted_at = NULL (active)
    - Future delete operations will set deleted_at timestamp instead of hard delete
    - Queries need to filter WHERE deleted_at IS NULL to exclude deleted applications
    """
    # Add deleted_at column to application table
    op.add_column(
        'application',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)
    )

    # Add index for soft delete filtering (improves query performance)
    op.create_index(
        op.f('ix_application_deleted_at'),
        'application',
        ['deleted_at'],
        unique=False
    )


def downgrade() -> None:
    """
    Remove soft delete support from Application model.

    WARNING: This will permanently delete all soft-deleted applications!
    Only run this if you're sure you want to remove the soft delete feature.
    """
    # Drop index first
    op.drop_index(op.f('ix_application_deleted_at'), table_name='application')

    # Drop deleted_at column
    op.drop_column('application', 'deleted_at')
