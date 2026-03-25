"""add notification_delivery and notification_consent tables

Revision ID: zw2c3d4e5f6g7
Revises: zv1b2c3d4e5f6
Create Date: 2026-03-25

Phase B: delivery persistence + consent foundation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'zw2c3d4e5f6g7'
down_revision: Union[str, None] = 'zv1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- notification_delivery ---
    op.create_table(
        'notification_delivery',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('notification_id', sa.Integer(),
                  sa.ForeignKey('notification.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event', sa.String(100), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('recipient_kind', sa.String(20), nullable=False, server_default='internal'),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=True),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('destination', sa.String(255), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='queued'),
        sa.Column('error_reason', sa.Text(), nullable=True),
        sa.Column('payload_snapshot', postgresql.JSONB(), nullable=True),
        sa.Column('provider_message_id', sa.String(128), nullable=True),
        sa.Column('dedupe_key', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index('ix_delivery_channel_status_created',
                     'notification_delivery',
                     ['channel', 'status', sa.text('created_at DESC')])
    op.create_index('ix_delivery_event_created',
                     'notification_delivery',
                     ['event', sa.text('created_at DESC')])
    op.create_index('ix_delivery_user_created',
                     'notification_delivery',
                     ['user_id', sa.text('created_at DESC')])
    op.create_index('ix_delivery_source',
                     'notification_delivery',
                     ['source_type', 'source_id', sa.text('created_at DESC')])

    # --- notification_consent ---
    op.create_table(
        'notification_consent',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('normalized_phone', sa.String(20), nullable=True),
        sa.Column('normalized_email', sa.String(255), nullable=True),
        sa.Column('consent_status', sa.String(20), nullable=False, server_default='granted'),
        sa.Column('consent_source', sa.String(50), nullable=False, server_default='manual'),
        sa.Column('granted_by', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('granted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('channel', 'source_type', 'source_id',
                            name='uq_consent_channel_source'),
    )


def downgrade() -> None:
    op.drop_table('notification_consent')
    op.drop_table('notification_delivery')
