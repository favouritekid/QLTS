"""Add legacy_status column to consultation_status for lead status sync

Revision ID: v7w8x9y0z1a2
Revises: q3r4s5t6u7v8
Create Date: 2025-01-21

This migration adds the legacy_status column to the consultation_status table.
This column maps consultation statuses to legacy lead.status values for
backward compatibility (Hybrid Approach for Lead Status Sync).

The legacy_status is populated with default mappings based on the current
pipeline stage and outcome type configuration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'v7w8x9y0z1a2'
down_revision = 'q3r4s5t6u7v8'
branch_labels = None
depends_on = None


# Default legacy_status mappings based on known consultation statuses
# This maps consultation_status.id → lead.status
LEGACY_STATUS_MAPPINGS = {
    # Stage 1: Chưa tư vấn
    "sts00": "new",        # Chưa liên hệ
    "sts01": "new",        # Không nghe máy
    "sts02": "new",        # Thuê bao
    "sts03": "rejected",   # Nhầm số (final, negative)

    # Stage 2: Đang tư vấn
    "sts04": "rejected",   # Không đồng ý (final, negative)
    "sts05": "contacted",  # Cân nhắc
    "sts06": "qualified",  # Đồng ý tư vấn (positive)

    # Stage 3: Đã nộp hồ sơ
    "sts07": "qualified",  # Chờ nhập học
    "sts08": "unqualified", # Không nhập học (final, negative)

    # Stage 4: Chuẩn bị nhập học
    "sts09": "qualified",  # Chờ đóng học phí
    "sts13": "qualified",  # Đã đóng lệ phí

    # Stage 5: Đã nộp học phí
    "sts10": "qualified",  # Đã nộp học phí

    # Stage 6: Đã nhập học
    "sts11": "converted",  # Đã nhập học (final, positive)

    # Stage 7: Không theo học
    "sts12": "unqualified", # Bỏ học (final, negative)
    "sts14": "unqualified", # Đã rút học phí (final, negative)
}


def upgrade() -> None:
    # 1. Add the legacy_status column
    op.add_column(
        'consultation_status',
        sa.Column(
            'legacy_status',
            sa.String(50),
            nullable=True,
            comment='Maps to lead.status for backward compatibility (auto-derived if NULL)'
        )
    )

    # 2. Populate legacy_status for existing records
    # Using raw SQL for efficiency
    connection = op.get_bind()

    for status_id, legacy_status in LEGACY_STATUS_MAPPINGS.items():
        connection.execute(
            sa.text(
                "UPDATE consultation_status SET legacy_status = :legacy_status WHERE id = :status_id"
            ),
            {"legacy_status": legacy_status, "status_id": status_id}
        )

    # 3. Log migration result
    result = connection.execute(
        sa.text("SELECT COUNT(*) FROM consultation_status WHERE legacy_status IS NOT NULL")
    )
    updated_count = result.scalar()
    print(f"✅ Updated {updated_count} consultation_status records with legacy_status")


def downgrade() -> None:
    op.drop_column('consultation_status', 'legacy_status')
