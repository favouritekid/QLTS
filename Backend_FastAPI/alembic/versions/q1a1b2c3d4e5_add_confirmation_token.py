"""Add admission confirmation token table and analytics fields

Revision ID: q1a1b2c3d4e5
Revises: p9a1b2c3d4e5
Create Date: 2026-01-07

Per Magic Link Confirm Flow Implementation Plan:
- Create admission_confirmation_token table for magic link verification
- Add confirmed_at and confirmed_via columns to admission_profile for analytics
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'q1a1b2c3d4e5'
down_revision: Union[str, None] = 'p9a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add confirmation token table and analytics columns.
    """
    conn = op.get_bind()
    
    # =========================================================================
    # 1. Create admission_confirmation_token table (with existence check)
    # =========================================================================
    print("📦 Checking admission_confirmation_token table...")
    
    # Check if table already exists (for partial migration recovery)
    table_exists = conn.execute(sa.text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'admission_confirmation_token'
        )
    """)).scalar()
    
    if not table_exists:
        op.create_table(
            'admission_confirmation_token',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('profile_id', sa.Integer(), 
                      sa.ForeignKey('admission_profile.id', ondelete='CASCADE'), 
                      nullable=False, unique=True),
            sa.Column('token', sa.String(64), nullable=False, unique=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('attempt_count', sa.Integer(), nullable=False, default=0),
            sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, 
                      server_default=sa.func.now()),
        )
        
        # Create indexes for fast lookups
        op.create_index(
            'ix_admission_confirmation_token_token', 
            'admission_confirmation_token', 
            ['token']
        )
        op.create_index(
            'ix_admission_confirmation_token_profile_id', 
            'admission_confirmation_token', 
            ['profile_id']
        )
        print("   ✅ admission_confirmation_token table created")
    else:
        print("   ⏭️ admission_confirmation_token table already exists, skipping")
    
    # =========================================================================
    # 2. Add analytics columns to admission_profile (with existence check)
    # =========================================================================
    print("📊 Adding analytics columns to admission_profile...")
    
    # Check if columns already exist (for partial migration recovery)
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'admission_profile'
        AND column_name IN ('confirmed_at', 'confirmed_via')
    """))
    existing_columns = {row[0] for row in result.fetchall()}
    
    # Add confirmed_at column with index for date range queries
    if 'confirmed_at' not in existing_columns:
        op.add_column(
            'admission_profile',
            sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True)
        )
        op.create_index(
            'ix_admission_profile_confirmed_at',
            'admission_profile',
            ['confirmed_at']
        )
        print("   ✅ confirmed_at column added")
    else:
        print("   ⏭️ confirmed_at column already exists, skipping")
    
    # Add confirmed_via column for confirmation method tracking
    if 'confirmed_via' not in existing_columns:
        op.add_column(
            'admission_profile',
            sa.Column('confirmed_via', sa.String(20), nullable=True)
        )
        print("   ✅ confirmed_via column added")
    else:
        print("   ⏭️ confirmed_via column already exists, skipping")
    
    print("")
    print("📋 Migration complete!")
    print("   - admission_confirmation_token table created")
    print("   - admission_profile.confirmed_at (with index)")
    print("   - admission_profile.confirmed_via")


def downgrade() -> None:
    """
    Remove confirmation token table and analytics columns.
    """
    # Remove analytics columns from admission_profile
    print("🔄 Removing analytics columns from admission_profile...")
    op.drop_index('ix_admission_profile_confirmed_at', table_name='admission_profile')
    op.drop_column('admission_profile', 'confirmed_via')
    op.drop_column('admission_profile', 'confirmed_at')
    
    # Drop confirmation token table
    print("🔄 Dropping admission_confirmation_token table...")
    op.drop_index('ix_admission_confirmation_token_profile_id', table_name='admission_confirmation_token')
    op.drop_index('ix_admission_confirmation_token_token', table_name='admission_confirmation_token')
    op.drop_table('admission_confirmation_token')
    
    print("✅ Rollback complete")
