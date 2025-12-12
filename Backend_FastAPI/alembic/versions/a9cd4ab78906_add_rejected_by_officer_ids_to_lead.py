"""add_rejected_by_officer_ids_to_lead

Revision ID: a9cd4ab78906
Revises: 64500df482c6
Create Date: 2025-12-12 14:15:56.485521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a9cd4ab78906'
down_revision: Union[str, Sequence[str], None] = '64500df482c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add rejected_by_officer_ids column to lead table."""
    op.add_column(
        'lead',
        sa.Column(
            'rejected_by_officer_ids',
            sa.JSON(),
            nullable=True,
            comment='List of officer IDs who reassigned this lead - prevents reassignment back to them'
        )
    )


def downgrade() -> None:
    """Remove rejected_by_officer_ids column from lead table."""
    op.drop_column('lead', 'rejected_by_officer_ids')
