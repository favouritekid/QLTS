"""add audit columns to admission_profile

✅ FIX #6: Add approval/rejection tracking columns for audit trail
Fixes AttributeError when approve_profile/reject_profile try to set non-existent columns

Revision ID: z8e9f0g1h2i3
Revises: z7d8e9f0g1h2
Create Date: 2026-01-07 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'q3a1b2c3d4e5'
down_revision: Union[str, None] = 'q2a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in the table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def fk_exists(table_name: str, fk_name: str) -> bool:
    """Check if a foreign key exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    fks = [fk['name'] for fk in inspector.get_foreign_keys(table_name)]
    return fk_name in fks


def upgrade() -> None:
    """
    Add audit trail columns to admission_profile table.
    
    IDEMPOTENT: Checks if columns/indexes/FKs exist before creating.
    """
    # Approval tracking columns
    if not column_exists('admission_profile', 'approved_at'):
        op.add_column('admission_profile', sa.Column(
            'approved_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when profile was approved by Manager/Admin"
        ))
    if not column_exists('admission_profile', 'approved_by_id'):
        op.add_column('admission_profile', sa.Column(
            'approved_by_id',
            sa.Integer(),
            nullable=True,
            comment="User ID who approved the profile (Manager/Admin)"
        ))
    if not column_exists('admission_profile', 'approval_notes'):
        op.add_column('admission_profile', sa.Column(
            'approval_notes',
            sa.String(length=1000),
            nullable=True,
            comment="Optional approval notes from Manager/Admin"
        ))

    # Rejection tracking columns
    if not column_exists('admission_profile', 'rejected_at'):
        op.add_column('admission_profile', sa.Column(
            'rejected_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when profile was rejected by Manager/Admin"
        ))
    if not column_exists('admission_profile', 'rejected_by_id'):
        op.add_column('admission_profile', sa.Column(
            'rejected_by_id',
            sa.Integer(),
            nullable=True,
            comment="User ID who rejected the profile (Manager/Admin)"
        ))
    if not column_exists('admission_profile', 'rejection_reason'):
        op.add_column('admission_profile', sa.Column(
            'rejection_reason',
            sa.String(length=1000),
            nullable=True,
            comment="Rejection reason (required when rejecting)"
        ))

    # Create indexes (if not exist)
    if not index_exists('admission_profile', 'ix_admission_profile_approved_at'):
        op.create_index(
            'ix_admission_profile_approved_at',
            'admission_profile',
            ['approved_at'],
            unique=False
        )
    if not index_exists('admission_profile', 'ix_admission_profile_rejected_at'):
        op.create_index(
            'ix_admission_profile_rejected_at',
            'admission_profile',
            ['rejected_at'],
            unique=False
        )

    # Create foreign key constraints (if not exist)
    if not fk_exists('admission_profile', 'fk_admission_profile_approved_by'):
        op.create_foreign_key(
            'fk_admission_profile_approved_by',
            'admission_profile',
            'user',
            ['approved_by_id'],
            ['id'],
            ondelete='SET NULL'
        )
    if not fk_exists('admission_profile', 'fk_admission_profile_rejected_by'):
        op.create_foreign_key(
            'fk_admission_profile_rejected_by',
            'admission_profile',
            'user',
            ['rejected_by_id'],
            ['id'],
            ondelete='SET NULL'
        )


def downgrade() -> None:
    """
    Remove audit trail columns from admission_profile table.

    WARNING: This will permanently delete audit data.
    Only downgrade if absolutely necessary.
    """
    # Drop foreign key constraints (if exist)
    if fk_exists('admission_profile', 'fk_admission_profile_rejected_by'):
        op.drop_constraint('fk_admission_profile_rejected_by', 'admission_profile', type_='foreignkey')
    if fk_exists('admission_profile', 'fk_admission_profile_approved_by'):
        op.drop_constraint('fk_admission_profile_approved_by', 'admission_profile', type_='foreignkey')

    # Drop indexes (if exist)
    if index_exists('admission_profile', 'ix_admission_profile_rejected_at'):
        op.drop_index('ix_admission_profile_rejected_at', table_name='admission_profile')
    if index_exists('admission_profile', 'ix_admission_profile_approved_at'):
        op.drop_index('ix_admission_profile_approved_at', table_name='admission_profile')

    # Drop columns (if exist)
    if column_exists('admission_profile', 'rejection_reason'):
        op.drop_column('admission_profile', 'rejection_reason')
    if column_exists('admission_profile', 'rejected_by_id'):
        op.drop_column('admission_profile', 'rejected_by_id')
    if column_exists('admission_profile', 'rejected_at'):
        op.drop_column('admission_profile', 'rejected_at')
    if column_exists('admission_profile', 'approval_notes'):
        op.drop_column('admission_profile', 'approval_notes')
    if column_exists('admission_profile', 'approved_by_id'):
        op.drop_column('admission_profile', 'approved_by_id')
    if column_exists('admission_profile', 'approved_at'):
        op.drop_column('admission_profile', 'approved_at')

