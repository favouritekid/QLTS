"""add_counts_for_kpi_to_consultation_status

Revision ID: 4a1e0590423f
Revises: z6c7d8e9f0g1
Create Date: 2026-01-02 01:48:29.865899

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4a1e0590423f'
down_revision: Union[str, Sequence[str], None] = 'z6c7d8e9f0g1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add counts_for_kpi column to consultation_status."""
    op.add_column(
        'consultation_status', 
        sa.Column(
            'counts_for_kpi', 
            sa.Boolean(), 
            server_default='true', 
            nullable=False, 
            comment="True nếu status được đếm vào KPI enrollments (VD: False cho 'Đã rút học phí')"
        )
    )
    
    # Set counts_for_kpi = false for 'Đã rút lại học phí' (sts14)
    op.execute("UPDATE consultation_status SET counts_for_kpi = false WHERE id = 'sts14'")


def downgrade() -> None:
    """Remove counts_for_kpi column from consultation_status."""
    op.drop_column('consultation_status', 'counts_for_kpi')
