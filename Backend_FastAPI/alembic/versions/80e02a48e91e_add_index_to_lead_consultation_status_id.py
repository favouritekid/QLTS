"""Add index to lead.consultation_status_id

Revision ID: 80e02a48e91e
Revises: q2r3s4t5u6v7
Create Date: 2025-11-15 12:22:43.926956

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '80e02a48e91e'
down_revision: Union[str, Sequence[str], None] = 'q2r3s4t5u6v7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ✅ CHỈ GIỮ LẠI LỆNH NÀY:
    # Tạo index cho cột consultation_status_id trong bảng lead
    op.create_index(
        op.f('ix_lead_consultation_status_id'), 
        'lead', 
        ['consultation_status_id'], 
        unique=False
    )


def downgrade() -> None:
    # ✅ LỆNH ROLLBACK TƯƠNG ỨNG:
    op.drop_index(
        op.f('ix_lead_consultation_status_id'), 
        table_name='lead'
    )
