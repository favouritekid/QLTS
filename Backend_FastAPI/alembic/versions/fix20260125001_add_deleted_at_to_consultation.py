"""Add deleted_at column to consultation table

Revision ID: fix20260125001
Revises: opt20260125002
Create Date: 2026-01-25

This migration adds soft-delete support to the consultation table.
When a lead is soft-deleted, all its consultations should also be soft-deleted.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fix20260125001'
down_revision = 'opt20260125002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add deleted_at column to consultation table."""
    # Check if column already exists (idempotent)
    from sqlalchemy import inspect
    from alembic import context

    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('consultation')]

    if 'deleted_at' not in columns:
        op.add_column(
            'consultation',
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)
        )

    # Check if index already exists
    indexes = [idx['name'] for idx in inspector.get_indexes('consultation')]
    if 'ix_consultation_deleted_at' not in indexes:
        op.create_index(
            'ix_consultation_deleted_at',
            'consultation',
            ['deleted_at'],
            unique=False
        )


def downgrade() -> None:
    """Remove deleted_at column from consultation table."""
    op.drop_index('ix_consultation_deleted_at', table_name='consultation')
    op.drop_column('consultation', 'deleted_at')
