"""add notification_rule table for visual management

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2025-11-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'k6l7m8n9o0p1'
down_revision: Union[str, None] = 'j5k6l7m8n9o0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    ✅ PHASE 2.1: Create notification_rule table for visual notification management.

    This table allows administrators to manage notification rules through UI
    instead of hardcoding them in the registry.
    """
    op.create_table(
        'notification_rule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(length=100), nullable=False, comment='SystemEvents enum value (e.g., LEAD_ASSIGNED)'),
        sa.Column('title_template', sa.String(length=255), nullable=False, comment='Title template with {placeholders}'),
        sa.Column('message_template', sa.Text(), nullable=False, comment='Message template with {placeholders}'),
        sa.Column('notification_type', sa.String(length=20), nullable=False, server_default='info', comment='Notification severity: info, success, warning, error'),
        sa.Column('link_template', sa.String(length=512), nullable=True, comment='Optional link template (e.g., /leads/{lead_id})'),
        sa.Column('channels', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='["browser"]', comment='Delivery channels: ["browser", "email", "sms"]'),
        sa.Column('recipient_config', postgresql.JSON(astext_type=sa.Text()), nullable=False, comment='Resolver configuration: {resolver_type, params}'),
        sa.Column('condition', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Optional activation conditions'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true', comment='Enable/disable this rule'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, onupdate=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for efficient querying
    op.create_index(op.f('ix_notification_rule_id'), 'notification_rule', ['id'], unique=False)
    op.create_index(op.f('ix_notification_rule_event'), 'notification_rule', ['event'], unique=False, comment='Fast lookup by event type')
    op.create_index(op.f('ix_notification_rule_enabled'), 'notification_rule', ['enabled'], unique=False, comment='Filter enabled rules')

    # Composite index for the most common query pattern
    op.create_index(
        'ix_notification_rule_event_enabled',
        'notification_rule',
        ['event', 'enabled'],
        unique=False,
        postgresql_where=sa.text('enabled = true')
    )


def downgrade() -> None:
    """Drop notification_rule table."""
    # Drop indexes
    op.drop_index('ix_notification_rule_event_enabled', table_name='notification_rule')
    op.drop_index(op.f('ix_notification_rule_enabled'), table_name='notification_rule')
    op.drop_index(op.f('ix_notification_rule_event'), table_name='notification_rule')
    op.drop_index(op.f('ix_notification_rule_id'), table_name='notification_rule')

    # Drop table
    op.drop_table('notification_rule')
