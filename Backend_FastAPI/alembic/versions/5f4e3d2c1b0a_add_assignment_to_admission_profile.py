"""add_assignment_to_admission_profile

Revision ID: 5f4e3d2c1b0a
Revises: a1ad22f9812a
Create Date: 2026-01-21 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f4e3d2c1b0a'
down_revision: Union[str, None] = 'a1ad22f9812a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add assigned_reviewer_id column
    op.add_column('admission_profile', sa.Column('assigned_reviewer_id', sa.Integer(), nullable=True, comment='Assigned Manager/Reviewer ID'))
    op.create_index(op.f('ix_admission_profile_assigned_reviewer_id'), 'admission_profile', ['assigned_reviewer_id'], unique=False)
    op.create_foreign_key(None, 'admission_profile', 'user', ['assigned_reviewer_id'], ['id'], ondelete='SET NULL')

    # 2. Add assigned_at column
    op.add_column('admission_profile', sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp when profile was assigned/claimed'))


def downgrade() -> None:
    # 1. Drop assigned_at column
    op.drop_column('admission_profile', 'assigned_at')

    # 2. Drop assigned_reviewer_id column
    op.drop_constraint(None, 'admission_profile', type_='foreignkey')
    op.drop_index(op.f('ix_admission_profile_assigned_reviewer_id'), table_name='admission_profile')
    op.drop_column('admission_profile', 'assigned_reviewer_id')
