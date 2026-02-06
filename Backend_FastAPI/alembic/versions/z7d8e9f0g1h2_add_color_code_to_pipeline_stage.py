"""add color_code to pipeline_stage

Revision ID: z7d8e9f0g1h2
Revises: z6c7d8e9f0g1
Create Date: 2025-01-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z7d8e9f0g1h2'
down_revision: Union[str, None] = 'audit20260126002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default colors for each stage (matching frontend STAGE_COLORS)
STAGE_COLORS = {
    'stg01': '#3B82F6',  # Blue - Chưa tư vấn
    'stg02': '#F59E0B',  # Amber - Đang tư vấn
    'stg03': '#8B5CF6',  # Purple - Đã nộp hồ sơ
    'stg04': '#06B6D4',  # Cyan - Chờ nhập học
    'stg05': '#10B981',  # Emerald - Đã nộp học phí
    'stg06': '#22C55E',  # Green - Đã nhập học
    'stg07': '#EF4444',  # Red - Không theo học
}
DEFAULT_COLOR = '#6B7280'  # Gray fallback


def upgrade() -> None:
    # Add color_code column with default value
    op.add_column(
        'pipeline_stage',
        sa.Column(
            'color_code',
            sa.String(7),
            nullable=False,
            server_default=DEFAULT_COLOR,
            comment='Hex color code for UI (e.g., #3B82F6)'
        )
    )

    # Update existing stages with their specific colors
    connection = op.get_bind()
    for stage_id, color in STAGE_COLORS.items():
        connection.execute(
            sa.text(
                "UPDATE pipeline_stage SET color_code = :color WHERE id = :stage_id"
            ),
            {"color": color, "stage_id": stage_id}
        )


def downgrade() -> None:
    op.drop_column('pipeline_stage', 'color_code')
