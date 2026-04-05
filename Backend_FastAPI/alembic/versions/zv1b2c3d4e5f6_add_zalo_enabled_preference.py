"""add zalo_enabled to notification_preference

Revision ID: zv1b2c3d4e5f6
Revises: zu0a1b2c3d4e5
Create Date: 2026-03-24

Adds zalo_enabled boolean column to notification_preference table.
Default false — users must explicitly opt in to Zalo notifications.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'zv1b2c3d4e5f6'
down_revision: Union[str, None] = 'zu0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'notification_preference',
        sa.Column(
            'zalo_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
            comment='Zalo ZNS channel — disabled by default until user opts in',
        ),
    )


def downgrade() -> None:
    op.drop_column('notification_preference', 'zalo_enabled')
