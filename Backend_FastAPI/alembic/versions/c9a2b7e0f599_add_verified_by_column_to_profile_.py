"""add verified_by column to profile_document

Revision ID: c9a2b7e0f599
Revises: 6g5h4i3j2k1l
Create Date: 2026-01-23 10:12:35.703431

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9a2b7e0f599'
down_revision: Union[str, Sequence[str], None] = '6g5h4i3j2k1l'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add verified_by column to track officer who verified document."""
    # Add verified_by column to profile_document table
    op.add_column(
        'profile_document',
        sa.Column(
            'verified_by',
            sa.Integer(),
            nullable=True,
            comment='Officer who verified the document'
        )
    )

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_profile_document_verified_by',
        'profile_document',
        'user',
        ['verified_by'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove verified_by column from profile_document."""
    # Drop foreign key constraint
    op.drop_constraint(
        'fk_profile_document_verified_by',
        'profile_document',
        type_='foreignkey'
    )

    # Drop column
    op.drop_column('profile_document', 'verified_by')
