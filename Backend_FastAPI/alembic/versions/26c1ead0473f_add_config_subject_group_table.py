"""add_config_subject_group_table

Revision ID: 26c1ead0473f
Revises: 598a88fe0141
Create Date: 2026-01-04 10:36:00

Phase 6.1: Add config_subject_group table for admission scoring subject groups.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '26c1ead0473f'
down_revision: Union[str, Sequence[str], None] = '598a88fe0141'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create config_subject_group table."""
    op.create_table(
        'config_subject_group',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=10), nullable=False, 
                  comment="Mã tổ hợp (vd: 'A00', 'D01')"),
        sa.Column('name', sa.String(length=100), nullable=False, 
                  comment="Tên hiển thị (vd: 'Toán - Lý - Hóa')"),
        sa.Column('subjects', sa.JSON(), nullable=False, 
                  comment="Danh sách môn học (vd: ['math', 'physics', 'chemistry'])"),
        sa.Column('display_order', sa.Integer(), nullable=False, default=0,
                  comment='Thứ tự hiển thị trong dropdown'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True,
                  comment='Soft delete flag'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_config_subject_group_code', 'config_subject_group', ['code'], unique=True)
    op.create_index('ix_config_subject_group_id', 'config_subject_group', ['id'], unique=False)
    op.create_index('ix_config_subject_group_is_active', 'config_subject_group', ['is_active'], unique=False)


def downgrade() -> None:
    """Drop config_subject_group table."""
    op.drop_index('ix_config_subject_group_is_active', table_name='config_subject_group')
    op.drop_index('ix_config_subject_group_id', table_name='config_subject_group')
    op.drop_index('ix_config_subject_group_code', table_name='config_subject_group')
    op.drop_table('config_subject_group')
