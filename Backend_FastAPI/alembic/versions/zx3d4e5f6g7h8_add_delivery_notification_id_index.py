"""add missing notification_id index on notification_delivery

Revision ID: zx3d4e5f6g7h8
Revises: zw2c3d4e5f6g7
Create Date: 2026-03-25

Patch: model declares index=True on notification_id but original migration
only created composite indexes. This adds the individual index.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'zx3d4e5f6g7h8'
down_revision: Union[str, None] = 'zw2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_notification_delivery_notification_id',
        'notification_delivery',
        ['notification_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_notification_delivery_notification_id', 'notification_delivery')
