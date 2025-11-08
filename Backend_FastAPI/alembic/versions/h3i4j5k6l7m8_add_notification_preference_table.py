"""add notification preference table

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2025-11-07 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'h3i4j5k6l7m8'
down_revision: Union[str, None] = 'g2h3i4j5k6l7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create notification_preference table."""
    op.create_table(
        'notification_preference',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('email_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sound_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('browser_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('email_digest', sa.String(length=20), nullable=False, server_default='instant'),
        sa.Column('type_preferences', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('quiet_hours_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('quiet_hours_start', sa.Time(), nullable=True),
        sa.Column('quiet_hours_end', sa.Time(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_notification_preference_id'), 'notification_preference', ['id'], unique=False)
    op.create_index(op.f('ix_notification_preference_user_id'), 'notification_preference', ['user_id'], unique=True)


def downgrade() -> None:
    """Drop notification_preference table."""
    op.drop_index(op.f('ix_notification_preference_user_id'), table_name='notification_preference')
    op.drop_index(op.f('ix_notification_preference_id'), table_name='notification_preference')
    op.drop_table('notification_preference')
