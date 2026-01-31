"""add notes column to fee table

Revision ID: fin20260131004
Revises: fin20260131003
Create Date: 2026-01-31

Adds notes column to fee table for audit trail (waive/cancel reasons).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fin20260131004'
down_revision: Union[str, None] = 'fin20260131002'  # Changed: run BEFORE fin20260131003
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add notes column to fee table
    op.add_column(
        'fee',
        sa.Column(
            'notes',
            sa.Text(),
            nullable=True,
            comment='Notes for waive/cancel/audit trail'
        )
    )


def downgrade() -> None:
    # Remove notes column from fee table
    op.drop_column('fee', 'notes')
