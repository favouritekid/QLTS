"""add CTV abuse flag columns

Revision ID: za0g1h2i3j4k5
Revises: z9f0g1h2i3j4
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'za0g1h2i3j4k5'
down_revision: Union[str, None] = 'z9f0g1h2i3j4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'collaborator',
        sa.Column(
            'expired_attribution_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Count of expired attributions for abuse detection',
        ),
    )
    op.add_column(
        'collaborator',
        sa.Column(
            'is_flagged',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Flagged for review after 5+ expired attributions',
        ),
    )


def downgrade() -> None:
    op.drop_column('collaborator', 'is_flagged')
    op.drop_column('collaborator', 'expired_attribution_count')
