"""add_discount_policy_ids_to_academic_info

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2025-11-22 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add applied_discount_policy_ids column to offering_academic_info table.

    This column stores an array of tuition discount policy IDs that are
    explicitly applied to this specific offering/year combination.
    """
    op.add_column(
        'offering_academic_info',
        sa.Column(
            'applied_discount_policy_ids',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Danh sách ID chính sách ưu đãi áp dụng (JSON array of integers)'
        )
    )


def downgrade() -> None:
    """Remove applied_discount_policy_ids column."""
    op.drop_column('offering_academic_info', 'applied_discount_policy_ids')
