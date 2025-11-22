"""add_is_heavy_to_major_program

Revision ID: a1b2c3d4e5f6
Revises: 800336b03c5a
Create Date: 2025-11-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '800336b03c5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_heavy column to major_program table.

    This field indicates whether a major/program is classified as
    hazardous, toxic, or dangerous work ("ngành nghề nặng nhọc, độc hại, nguy hiểm").
    Students in these programs are eligible for special policies/benefits.
    """
    op.add_column(
        'major_program',
        sa.Column(
            'is_heavy',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Ngành nghề nặng nhọc, độc hại, nguy hiểm (được hưởng chính sách đặc biệt)'
        )
    )

    # Create index for filtering
    op.create_index(
        'idx_major_program_is_heavy',
        'major_program',
        ['is_heavy'],
        unique=False
    )


def downgrade() -> None:
    """Remove is_heavy column from major_program table."""
    op.drop_index('idx_major_program_is_heavy', table_name='major_program')
    op.drop_column('major_program', 'is_heavy')
