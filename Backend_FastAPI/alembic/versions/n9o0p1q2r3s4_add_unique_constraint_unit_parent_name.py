"""add unique constraint unit parent name

Revision ID: n9o0p1q2r3s4
Revises: m8n9o0p1q2r3
Create Date: 2025-11-12 08:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n9o0p1q2r3s4'
down_revision: Union[str, None] = 'm8n9o0p1q2r3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint on (parent_id, name) to prevent race conditions.

    This ensures that two units cannot have the same name within the same parent,
    even if created concurrently. Prevents race condition where both requests pass
    the check_duplicate_unit_name validation before either commits to database.

    Note: In PostgreSQL, NULL values are treated as distinct, so this allows
    multiple root units (parent_id=NULL) with different names.
    """
    op.create_unique_constraint(
        'uq_unit_parent_name',
        'organization_unit',
        ['parent_id', 'name']
    )


def downgrade() -> None:
    """Remove unique constraint."""
    op.drop_constraint('uq_unit_parent_name', 'organization_unit', type_='unique')
