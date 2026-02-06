"""add application_fee to admission_path

Revision ID: fee20260130001
Revises: z7d8e9f0g1h2
Create Date: 2026-01-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fee20260130001'
down_revision: Union[str, None] = 'z7d8e9f0g1h2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add application_fee column to admission_path table
    op.add_column(
        'admission_path',
        sa.Column(
            'application_fee',
            sa.Numeric(precision=12, scale=2),
            nullable=True,
            server_default='0',
            comment='Lệ phí xét tuyển (VND). 0 hoặc NULL = miễn phí'
        )
    )


def downgrade() -> None:
    op.drop_column('admission_path', 'application_fee')
