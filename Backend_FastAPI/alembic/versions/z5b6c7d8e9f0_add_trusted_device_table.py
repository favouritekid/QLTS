# alembic/versions/z5b6c7d8e9f0_add_trusted_device_table.py
"""Add trusted_device table for login security.

Revision ID: z5b6c7d8e9f0
Revises: z4a5b6c7d8e9
Create Date: 2024-12-22

Phase 4: Trusted Devices
- Users can mark devices as trusted to avoid suspicious login alerts
- Device fingerprint is a hash of browser + OS + other stable attributes
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'z5b6c7d8e9f0'
down_revision = 'z4a5b6c7d8e9'  # After login_history migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'trusted_device',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('device_fingerprint', sa.String(64), nullable=False),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('browser', sa.String(100), nullable=True),
        sa.Column('os', sa.String(100), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('trusted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trusted_from_ip', sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'device_fingerprint', name='uq_trusted_device_user_fingerprint')
    )
    
    # Index for user lookups
    op.create_index('ix_trusted_device_user_id', 'trusted_device', ['user_id'])
    
    # Index for fingerprint lookups (used in is_device_trusted checks)
    op.create_index('ix_trusted_device_fingerprint', 'trusted_device', ['device_fingerprint'])


def downgrade() -> None:
    op.drop_index('ix_trusted_device_fingerprint', table_name='trusted_device')
    op.drop_index('ix_trusted_device_user_id', table_name='trusted_device')
    op.drop_table('trusted_device')
