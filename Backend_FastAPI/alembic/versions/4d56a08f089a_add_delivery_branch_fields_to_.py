"""add delivery branch fields to notification_action

Revision ID: 4d56a08f089a
Revises: e1_001_consent_v1
Create Date: 2026-03-28 15:15:30.442093

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d56a08f089a'
down_revision: Union[str, Sequence[str], None] = 'e1_001_consent_v1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Phase 3 delivery branch fields to notification_action."""
    op.add_column('notification_action', sa.Column('recipient_config', sa.JSON(), nullable=True,
        comment='Per-action recipient resolver config. Falls back to rule.recipient_config if null.'))
    op.add_column('notification_action', sa.Column('content_mode', sa.String(length=50), nullable=True,
        comment='Content source: inherit_default, template_override, inline_override, channel_native'))
    op.add_column('notification_action', sa.Column('content_override', sa.JSON(), nullable=True,
        comment='Inline title/message/link override when content_mode=inline_override'))
    op.add_column('notification_action', sa.Column('branch_key', sa.String(length=100), nullable=True,
        comment='Human-readable branch identifier for debugging and UI round-trip'))


def downgrade() -> None:
    """Remove Phase 3 delivery branch fields from notification_action."""
    op.drop_column('notification_action', 'branch_key')
    op.drop_column('notification_action', 'content_override')
    op.drop_column('notification_action', 'content_mode')
    op.drop_column('notification_action', 'recipient_config')
