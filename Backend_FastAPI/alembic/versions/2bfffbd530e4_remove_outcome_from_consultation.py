"""remove_outcome_from_consultation

Revision ID: 2bfffbd530e4
Revises: 5dddad54efb9
Create Date: 2025-12-08 06:07:25.982180

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2bfffbd530e4'
down_revision: Union[str, Sequence[str], None] = '5dddad54efb9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove legacy outcome column from consultation table."""
    op.drop_column('consultation', 'outcome')


def downgrade() -> None:
    """Restore outcome column to consultation table."""
    op.add_column(
        'consultation',
        sa.Column('outcome', sa.String(50), nullable=True)
    )

