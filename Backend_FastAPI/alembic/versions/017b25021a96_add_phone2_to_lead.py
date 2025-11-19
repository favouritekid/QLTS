"""add_phone2_to_lead

Revision ID: 017b25021a96
Revises: u6v7w8x9y0z1
Create Date: 2025-11-19 12:04:49.520640

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '017b25021a96'
down_revision: Union[str, Sequence[str], None] = 'u6v7w8x9y0z1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add phone2 column to lead table."""
    op.add_column('lead', sa.Column('phone2', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_lead_phone2'), 'lead', ['phone2'], unique=False)


def downgrade() -> None:
    """Remove phone2 column from lead table."""
    op.drop_index(op.f('ix_lead_phone2'), table_name='lead')
    op.drop_column('lead', 'phone2')
