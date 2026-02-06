"""Add state machine columns to admission_profile

Revision ID: p7a1b2c3d4e5
Revises: p6a1b2c3d4e5
Create Date: 2026-01-06

Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md:
- Add timestamp and actor columns for each state transition
- Add notes/reason columns for documentation
- All columns nullable (legacy profiles won't have these values)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'p7a1b2c3d4e5'
down_revision = 'p6a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add state machine tracking columns to admission_profile table.

    These columns track:
    - Who performed each state transition (actor_id)
    - When the transition occurred (timestamp)
    - Why the transition occurred (notes/reason)
    """
    conn = op.get_bind()

    # Add columns for APPROVED state
    op.add_column('admission_profile', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('admission_profile', sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))
    op.add_column('admission_profile', sa.Column('approval_notes', sa.Text(), nullable=True))

    # Add columns for REJECTED state
    op.add_column('admission_profile', sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('admission_profile', sa.Column('rejected_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))
    op.add_column('admission_profile', sa.Column('rejection_reason', sa.Text(), nullable=True))

    # Add columns for RESUBMITTED state
    op.add_column('admission_profile', sa.Column('resubmitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('admission_profile', sa.Column('resubmitted_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))
    op.add_column('admission_profile', sa.Column('resubmit_notes', sa.Text(), nullable=True))

    # Add columns for CONFIRMED state
    op.add_column('admission_profile', sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('admission_profile', sa.Column('confirmed_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))

    # Add columns for OVERRIDDEN state (Admin exception path)
    op.add_column('admission_profile', sa.Column('overridden_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('admission_profile', sa.Column('overridden_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True))
    op.add_column('admission_profile', sa.Column('override_reason', sa.Text(), nullable=True))

    # Add indexes for common queries
    op.create_index('ix_admission_profile_approved_at', 'admission_profile', ['approved_at'])
    op.create_index('ix_admission_profile_rejected_at', 'admission_profile', ['rejected_at'])
    op.create_index('ix_admission_profile_confirmed_at', 'admission_profile', ['confirmed_at'])

    print("✅ Added state machine tracking columns to admission_profile")


def downgrade():
    """
    Remove state machine tracking columns.

    WARNING: This will lose all state transition audit data.
    """
    # Drop indexes first
    op.drop_index('ix_admission_profile_confirmed_at', table_name='admission_profile')
    op.drop_index('ix_admission_profile_rejected_at', table_name='admission_profile')
    op.drop_index('ix_admission_profile_approved_at', table_name='admission_profile')

    # Drop OVERRIDDEN columns
    op.drop_column('admission_profile', 'override_reason')
    op.drop_column('admission_profile', 'overridden_by_id')
    op.drop_column('admission_profile', 'overridden_at')

    # Drop CONFIRMED columns
    op.drop_column('admission_profile', 'confirmed_by_id')
    op.drop_column('admission_profile', 'confirmed_at')

    # Drop RESUBMITTED columns
    op.drop_column('admission_profile', 'resubmit_notes')
    op.drop_column('admission_profile', 'resubmitted_by_id')
    op.drop_column('admission_profile', 'resubmitted_at')

    # Drop REJECTED columns
    op.drop_column('admission_profile', 'rejection_reason')
    op.drop_column('admission_profile', 'rejected_by_id')
    op.drop_column('admission_profile', 'rejected_at')

    # Drop APPROVED columns
    op.drop_column('admission_profile', 'approval_notes')
    op.drop_column('admission_profile', 'approved_by_id')
    op.drop_column('admission_profile', 'approved_at')

    print("✅ Removed state machine tracking columns from admission_profile")
