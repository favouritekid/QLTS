"""add_verified_format_to_profile_document

Revision ID: a1ad22f9812a
Revises: 9e1d24f91416
Create Date: 2026-01-21 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1ad22f9812a'
down_revision: Union[str, None] = '9e1d24f91416'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add verified_format column
    op.add_column('profile_document', sa.Column(
        'verified_format', 
        sa.String(length=50), 
        nullable=True, 
        comment='original | certified_copy | photo'
    ))


def downgrade() -> None:
    op.drop_column('profile_document', 'verified_format')
