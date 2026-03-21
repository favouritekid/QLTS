"""add loss_reason to consultation

Revision ID: 1a25aa8e2984
Revises: zt9z0a1b2c3d4
Create Date: 2026-03-21 13:22:37.976760

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a25aa8e2984'
down_revision: Union[str, Sequence[str], None] = 'zt9z0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add loss_reason_code and loss_reason_note to consultation table."""
    op.add_column("consultation", sa.Column("loss_reason_code", sa.String(50), nullable=True))
    op.add_column("consultation", sa.Column("loss_reason_note", sa.Text(), nullable=True))
    op.create_index("ix_consultation_loss_reason_code", "consultation", ["loss_reason_code"])


def downgrade() -> None:
    """Remove loss_reason columns from consultation."""
    op.drop_index("ix_consultation_loss_reason_code", table_name="consultation")
    op.drop_column("consultation", "loss_reason_note")
    op.drop_column("consultation", "loss_reason_code")
