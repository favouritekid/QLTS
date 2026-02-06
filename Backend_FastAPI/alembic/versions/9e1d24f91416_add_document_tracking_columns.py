"""add_document_tracking_columns

Revision ID: 9e1d24f91416
Revises: e01bc00eaf03
Create Date: 2026-01-21 02:38:06.693062

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9e1d24f91416'
down_revision: Union[str, Sequence[str], None] = 'e01bc00eaf03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add paper submission and rejection tracking columns to profile_document."""
    # Add paper submission tracking columns
    op.add_column('profile_document', sa.Column(
        'paper_submitted_at', 
        sa.DateTime(timezone=True), 
        nullable=True, 
        comment='When officer confirmed paper was received'
    ))
    op.add_column('profile_document', sa.Column(
        'paper_submitted_by', 
        sa.Integer(), 
        nullable=True, 
        comment='Officer who confirmed paper receipt'
    ))
    
    # Add rejection tracking columns
    op.add_column('profile_document', sa.Column(
        'rejected_at', 
        sa.DateTime(timezone=True), 
        nullable=True, 
        comment='When document was rejected'
    ))
    op.add_column('profile_document', sa.Column(
        'rejected_by', 
        sa.Integer(), 
        nullable=True, 
        comment='Officer who rejected'
    ))
    
    # Add foreign keys
    op.create_foreign_key(
        'fk_profile_document_paper_submitted_by', 
        'profile_document', 'user', 
        ['paper_submitted_by'], ['id'], 
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_profile_document_rejected_by', 
        'profile_document', 'user', 
        ['rejected_by'], ['id'], 
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove paper submission and rejection tracking columns."""
    op.drop_constraint('fk_profile_document_rejected_by', 'profile_document', type_='foreignkey')
    op.drop_constraint('fk_profile_document_paper_submitted_by', 'profile_document', type_='foreignkey')
    op.drop_column('profile_document', 'rejected_by')
    op.drop_column('profile_document', 'rejected_at')
    op.drop_column('profile_document', 'paper_submitted_by')
    op.drop_column('profile_document', 'paper_submitted_at')
