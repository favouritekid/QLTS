"""add notification action table for workflow support

Revision ID: i5j6k7l8m9n0
Revises: h3i4j5k6l7m8
Create Date: 2025-11-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'i5j6k7l8m9n0'
down_revision: Union[str, None] = '91129728ac99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    ✅ NOTIFICATION 2.0 - PHASE 1: Create notification_action table.

    This table supports multi-step notification workflows. Each notification rule
    can have multiple actions that execute sequentially with optional delays,
    supporting different channels (socket, email, zalo, sms).

    Features:
        - Multi-step workflows (Step 1, 2, 3...)
        - Different channels per step
        - Optional delays between steps
        - Channel-specific configuration
        - Template reference by code (flexible)
    """
    op.create_table(
        'notification_action',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rule_id', sa.Integer(), nullable=False, comment='Foreign key to notification_rule'),
        sa.Column('step', sa.Integer(), nullable=False, server_default='1', comment='Step number in workflow (1, 2, 3...)'),
        sa.Column('channel', sa.String(length=50), nullable=False, comment='Delivery channel: socket, email, zalo, sms'),
        sa.Column('template_code', sa.String(length=100), nullable=True, comment='Optional reference to NotificationTemplate.template_code'),
        sa.Column('delay_minutes', sa.Integer(), nullable=False, server_default='0', comment='Delay in minutes before executing this action (0 = immediate)'),
        sa.Column('config', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='Channel-specific configuration (e.g., Zalo template ID)'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['rule_id'], ['notification_rule.id'], ondelete='CASCADE')
    )

    # Create indexes for efficient querying
    op.create_index(op.f('ix_notification_action_id'), 'notification_action', ['id'], unique=False)
    op.create_index(op.f('ix_notification_action_rule_id'), 'notification_action', ['rule_id'], unique=False)
    op.create_index(op.f('ix_notification_action_step'), 'notification_action', ['step'], unique=False)

    # Create unique constraint to prevent duplicate steps per rule
    op.create_unique_constraint(
        'uq_notification_action_rule_step',
        'notification_action',
        ['rule_id', 'step']
    )


def downgrade() -> None:
    """
    Rollback: Drop notification_action table.
    """
    # Drop unique constraint
    op.drop_constraint('uq_notification_action_rule_step', 'notification_action', type_='unique')

    # Drop indexes
    op.drop_index(op.f('ix_notification_action_step'), table_name='notification_action')
    op.drop_index(op.f('ix_notification_action_rule_id'), table_name='notification_action')
    op.drop_index(op.f('ix_notification_action_id'), table_name='notification_action')

    # Drop table
    op.drop_table('notification_action')
