"""Change JSON to JSONB for notification_template columns

This migration changes the column types from JSON to JSONB for:
- supported_channels
- allowed_events

This enables proper PostgreSQL JSONB operators like @> (contains)
for efficient querying.

Revision ID: a4b5c6d7e8f0
Revises: z3a4b5c6d7e8
Create Date: 2024-12-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic
revision = 'a4b5c6d7e8f0'
down_revision = 'r2s3t4u5v6w7'
branch_labels = None
depends_on = None



def upgrade() -> None:
    """Convert JSON columns to JSONB for better query performance."""
    # Change supported_channels from JSON to JSONB
    op.alter_column(
        'notification_template',
        'supported_channels',
        type_=JSONB,
        postgresql_using='supported_channels::jsonb',
        comment='Channels this template supports (["socket", "email", "zalo", "sms"])'
    )
    
    # Change allowed_events from JSON to JSONB
    op.alter_column(
        'notification_template',
        'allowed_events',
        type_=JSONB,
        postgresql_using='allowed_events::jsonb',
        comment='Events this template is designed for (null = all events)'
    )
    

def downgrade() -> None:
    """Revert JSONB columns back to JSON."""
    op.alter_column(
        'notification_template',
        'supported_channels',
        type_=sa.JSON,
        postgresql_using='supported_channels::json',
        comment='Channels this template supports (["socket", "email", "zalo", "sms"])'
    )
    
    op.alter_column(
        'notification_template',
        'allowed_events',
        type_=sa.JSON,
        postgresql_using='allowed_events::json',
        comment='Events this template is designed for (null = all events)'
    )
