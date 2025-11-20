"""add quick disposition columns

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2024-01-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q3r4s5t6u7v8'
down_revision: Union[str, None] = 'p2q3r4s5t6u7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add next_activity_at to lead table for bubble-up sorting
    op.add_column('lead', sa.Column('next_activity_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_lead_next_activity_at'), 'lead', ['next_activity_at'], unique=False)

    # Add scheduled_at to consultation table for follow-up scheduling
    op.add_column('consultation', sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_consultation_scheduled_at'), 'consultation', ['scheduled_at'], unique=False)


def downgrade() -> None:
    # Remove scheduled_at from consultation
    op.drop_index(op.f('ix_consultation_scheduled_at'), table_name='consultation')
    op.drop_column('consultation', 'scheduled_at')

    # Remove next_activity_at from lead
    op.drop_index(op.f('ix_lead_next_activity_at'), table_name='lead')
    op.drop_column('lead', 'next_activity_at')
