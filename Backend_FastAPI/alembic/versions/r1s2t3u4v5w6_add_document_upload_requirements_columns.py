"""add_document_upload_requirements_columns

Revision ID: r1s2t3u4v5w6
Revises: z6c7d8e9f0g1
Create Date: 2026-01-10 09:30:00.000000

Add requires_upload and submission_format to document_group_item
to support flexible document upload requirements per program.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r1s2t3u4v5w6'
down_revision = 'q5a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add requires_upload column
    op.add_column(
        'document_group_item',
        sa.Column(
            'requires_upload',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='true=Must upload file, false=Checklist only'
        )
    )
    
    # Add submission_format column
    op.add_column(
        'document_group_item',
        sa.Column(
            'submission_format',
            sa.String(20),
            nullable=True,
            comment='photo | certified_copy | original (NULL if requires_upload=false)'
        )
    )
    
    # Add CHECK constraint: If requires_upload=true, submission_format must be set
    op.create_check_constraint(
        'chk_submission_format',
        'document_group_item',
        'requires_upload = false OR submission_format IS NOT NULL'
    )
    
    # Update existing rows: Set default submission_format for existing upload requirements
    # Since all existing rows have requires_upload=true (default), they need a format
    op.execute("""
        UPDATE document_group_item 
        SET submission_format = 'photo' 
        WHERE submission_format IS NULL AND requires_upload = true
    """)


def downgrade() -> None:
    # Drop CHECK constraint
    op.drop_constraint('chk_submission_format', 'document_group_item', type_='check')
    
    # Drop columns
    op.drop_column('document_group_item', 'submission_format')
    op.drop_column('document_group_item', 'requires_upload')
