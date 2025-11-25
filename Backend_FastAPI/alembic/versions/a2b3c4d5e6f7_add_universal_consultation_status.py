"""add universal consultation status support

Revision ID: a2b3c4d5e6f7
Revises: z3a4b5c6d7e8
Create Date: 2025-11-25 14:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'z3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_universal column - cho phép status dùng ở mọi stage
    op.add_column(
        'consultation_status',
        sa.Column(
            'is_universal',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='True nếu status có thể dùng ở mọi pipeline stage (VD: Không nghe máy)'
        )
    )

    # Add updates_pipeline column - kiểm soát có update lead status không
    op.add_column(
        'consultation_status',
        sa.Column(
            'updates_pipeline',
            sa.Boolean(),
            nullable=False,
            server_default='true',
            comment='False nếu chỉ ghi nhận activity, không thay đổi pipeline progression'
        )
    )

    # Create index for efficient querying of universal statuses
    op.create_index(
        'ix_consultation_status_universal',
        'consultation_status',
        ['is_universal'],
        unique=False
    )

    # ✅ Seed data: Đánh dấu retry/transient statuses
    # Dựa trên dữ liệu thực tế từ screenshot
    op.execute("""
        UPDATE consultation_status
        SET is_universal = true, updates_pipeline = false
        WHERE id IN (
            'sts01',  -- Không nghe máy
            'sts02'   -- Thuê bao
            -- 'sts03' CHƯA THÊM - cần xác nhận với user về logic "Nhầm số"
        )
    """)

    # Note: sts03 (Nhầm số) hiện có is_final_status=true, outcome_type=negative
    # Nếu muốn dùng như universal status, cần:
    # 1. SET is_final_status = false
    # 2. SET outcome_type = 'neutral'
    # 3. SET is_universal = true, updates_pipeline = false
    #
    # Uncomment dòng dưới nếu muốn "Nhầm số" thành universal status:
    # op.execute("""
    #     UPDATE consultation_status
    #     SET
    #         is_universal = true,
    #         updates_pipeline = false,
    #         is_final_status = false,
    #         outcome_type = 'neutral'
    #     WHERE id = 'sts03'
    # """)


def downgrade() -> None:
    op.drop_index('ix_consultation_status_universal', table_name='consultation_status')
    op.drop_column('consultation_status', 'updates_pipeline')
    op.drop_column('consultation_status', 'is_universal')
