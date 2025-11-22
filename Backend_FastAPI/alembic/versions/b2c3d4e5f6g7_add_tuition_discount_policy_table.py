"""add_tuition_discount_policy_table

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f7
Create Date: 2025-11-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tuition_discount_policy table.

    This table stores tuition discount policies with support for:
    - Fixed amount or percentage discounts
    - Time-based validity periods
    - Program/offering scope filtering (JSON)
    - Student criteria filtering (JSON)
    - Stackable discounts with priority ordering
    - Usage quota tracking
    """

    # Create enum type for discount_type
    discount_type_enum = postgresql.ENUM(
        'amount', 'percentage',
        name='discount_type_enum',
        create_type=True
    )
    discount_type_enum.create(op.get_bind(), checkfirst=True)

    # Create table
    op.create_table(
        'tuition_discount_policy',
        # Primary key
        sa.Column('id', sa.Integer(), nullable=False),

        # Basic info
        sa.Column('code', sa.String(length=50), nullable=False,
                  comment='Mã chính sách duy nhất (vd: EARLY_BIRD_2025)'),
        sa.Column('name', sa.String(length=200), nullable=False,
                  comment='Tên chính sách hiển thị'),
        sa.Column('description', sa.Text(), nullable=True,
                  comment='Mô tả chi tiết về chính sách'),

        # Discount type and value
        sa.Column('discount_type',
                  sa.Enum('amount', 'percentage', name='discount_type_enum'),
                  nullable=False,
                  comment="Loại ưu đãi: 'amount' (VND) hoặc 'percentage' (%)"),
        sa.Column('discount_value', sa.Numeric(precision=15, scale=2), nullable=False,
                  comment='Giá trị ưu đãi: Số tiền (VND) hoặc phần trăm (0-100)'),

        # Validity period
        sa.Column('valid_from', sa.Date(), nullable=True,
                  comment='Ngày bắt đầu hiệu lực (NULL = không giới hạn)'),
        sa.Column('valid_to', sa.Date(), nullable=True,
                  comment='Ngày kết thúc hiệu lực (NULL = vô thời hạn)'),

        # Scope and criteria (JSON)
        sa.Column('applicable_scope', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}',
                  comment='Phạm vi ngành/chương trình áp dụng (JSON)'),
        sa.Column('target_criteria', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default='{}',
                  comment='Điều kiện đối tượng sinh viên được hưởng (JSON)'),

        # Application rules
        sa.Column('is_stackable', sa.Boolean(), nullable=False, server_default='false',
                  comment='Có thể cộng dồn với ưu đãi khác không'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0',
                  comment='Độ ưu tiên (cao hơn = áp dụng trước)'),
        sa.Column('max_usage', sa.Integer(), nullable=True,
                  comment='Giới hạn số lượt sử dụng (NULL = không giới hạn)'),
        sa.Column('current_usage', sa.Integer(), nullable=False, server_default='0',
                  comment='Số lượt đã sử dụng'),

        # Status
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true',
                  comment='Trạng thái hoạt động (soft delete)'),

        # Audit trail
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()'),
                  comment='Thời điểm tạo'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()'),
                  comment='Thời điểm cập nhật cuối'),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True,
                  comment='User tạo chính sách'),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True,
                  comment='User cập nhật cuối'),

        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['user.id'], ondelete='SET NULL'),
    )

    # Create indexes
    op.create_index('idx_tuition_discount_policy_code', 'tuition_discount_policy', ['code'], unique=True)
    op.create_index('idx_tuition_discount_policy_is_active', 'tuition_discount_policy', ['is_active'])
    op.create_index('idx_tuition_discount_policy_priority', 'tuition_discount_policy', ['priority'])
    op.create_index('idx_tuition_discount_policy_valid_dates', 'tuition_discount_policy', ['valid_from', 'valid_to'])


def downgrade() -> None:
    """Drop tuition_discount_policy table."""
    # Drop indexes
    op.drop_index('idx_tuition_discount_policy_valid_dates', table_name='tuition_discount_policy')
    op.drop_index('idx_tuition_discount_policy_priority', table_name='tuition_discount_policy')
    op.drop_index('idx_tuition_discount_policy_is_active', table_name='tuition_discount_policy')
    op.drop_index('idx_tuition_discount_policy_code', table_name='tuition_discount_policy')

    # Drop table
    op.drop_table('tuition_discount_policy')

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS discount_type_enum")
