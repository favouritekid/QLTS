"""Add document_audit_log table for compliance

Revision ID: audit20260126001
Revises: fix20260125001
Create Date: 2026-01-26

Purpose:
    Creates audit log table for all document operations.
    Required for compliance and regulatory requirements.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'audit20260126001'
down_revision = 'fix20260125001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'document_audit_log',
        # Primary key
        sa.Column('id', sa.Integer(), nullable=False),

        # Link to document
        sa.Column('profile_document_id', sa.Integer(), nullable=False),

        # Action details
        sa.Column('action', sa.String(length=50), nullable=False,
                  comment='uploaded | verified | rejected | reset | paper_submitted | deleted'),

        # Actor
        sa.Column('actor_user_id', sa.Integer(), nullable=True,
                  comment='User who performed the action'),

        # Status change
        sa.Column('old_status', sa.String(length=20), nullable=True,
                  comment='Status before action'),
        sa.Column('new_status', sa.String(length=20), nullable=True,
                  comment='Status after action'),

        # File tracking
        sa.Column('old_file_path', sa.String(length=500), nullable=True,
                  comment='Previous file path (for re-uploads)'),
        sa.Column('new_file_path', sa.String(length=500), nullable=True,
                  comment='New file path (for uploads)'),

        # Upload metadata
        sa.Column('original_filename', sa.String(length=255), nullable=True,
                  comment='Original filename from user'),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True,
                  comment='File size in bytes'),
        sa.Column('content_type', sa.String(length=100), nullable=True,
                  comment='MIME type of uploaded file'),

        # Action details
        sa.Column('reason', sa.Text(), nullable=True,
                  comment='Reason for rejection/reset'),

        # Format tracking
        sa.Column('declared_format', sa.String(length=50), nullable=True,
                  comment='User declared: original | certified_copy | photo'),
        sa.Column('verified_format', sa.String(length=50), nullable=True,
                  comment='Officer verified: original | certified_copy | photo'),

        # Extra metadata (JSON)
        sa.Column('extra_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  server_default='{}', comment='Additional context data'),

        # Timestamp
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),

        # Client context (for security audit)
        sa.Column('ip_address', sa.String(length=45), nullable=True,
                  comment='Client IP address'),
        sa.Column('user_agent', sa.String(length=500), nullable=True,
                  comment='Client user agent'),

        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['profile_document_id'],
            ['profile_document.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['actor_user_id'],
            ['user.id'],
            ondelete='SET NULL'
        ),
    )

    # Create indexes for common queries
    op.create_index(
        'ix_document_audit_log_profile_document_id',
        'document_audit_log',
        ['profile_document_id']
    )
    op.create_index(
        'ix_document_audit_log_action',
        'document_audit_log',
        ['action']
    )
    op.create_index(
        'ix_document_audit_log_actor_user_id',
        'document_audit_log',
        ['actor_user_id']
    )
    op.create_index(
        'ix_document_audit_log_created_at',
        'document_audit_log',
        ['created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_document_audit_log_created_at', table_name='document_audit_log')
    op.drop_index('ix_document_audit_log_actor_user_id', table_name='document_audit_log')
    op.drop_index('ix_document_audit_log_action', table_name='document_audit_log')
    op.drop_index('ix_document_audit_log_profile_document_id', table_name='document_audit_log')
    op.drop_table('document_audit_log')
