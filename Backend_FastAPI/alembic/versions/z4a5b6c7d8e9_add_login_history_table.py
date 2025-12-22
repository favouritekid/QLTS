"""Add login_history table for security audit

Revision ID: z4a5b6c7d8e9
Revises: a4b5c6d7e8f0
Create Date: 2024-12-22
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = 'z4a5b6c7d8e9'
down_revision = 'a4b5c6d7e8f0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create login_history table for tracking login attempts."""
    op.create_table(
        'login_history',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True),
        
        # Login timestamp
        sa.Column('login_at', sa.DateTime(timezone=True), nullable=False, index=True),
        
        # IP/Location info
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('country', sa.String(100), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        
        # Device/Browser info
        sa.Column('device_type', sa.String(50), nullable=True),
        sa.Column('browser', sa.String(100), nullable=True),
        sa.Column('os', sa.String(100), nullable=True),
        
        # Anomaly flags
        sa.Column('is_new_ip', sa.Boolean(), default=False, nullable=False),
        sa.Column('is_new_device', sa.Boolean(), default=False, nullable=False),
        sa.Column('is_new_location', sa.Boolean(), default=False, nullable=False),
        sa.Column('risk_score', sa.Integer(), default=0, nullable=False),
        
        # User response
        sa.Column('user_response', sa.String(20), nullable=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        
        # OAuth provider
        sa.Column('oauth_provider', sa.String(20), nullable=True),
    )
    
    # Index for fast lookup of recent suspicious logins
    op.create_index(
        'ix_login_history_user_suspicious',
        'login_history',
        ['user_id', 'is_new_ip', 'is_new_device', 'is_new_location'],
        postgresql_where=sa.text("is_new_ip = true OR is_new_device = true OR is_new_location = true")
    )


def downgrade() -> None:
    """Drop login_history table."""
    op.drop_index('ix_login_history_user_suspicious', table_name='login_history')
    op.drop_table('login_history')
