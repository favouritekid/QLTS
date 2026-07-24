"""major-change reprice 1G — Payment.recognized_major_id (doanh thu theo ngành
lúc xác minh).

Edge-case đổi ngành SAU KHI đã thu tiền: ``reprice_for_major_change`` relabel
``Fee.resolved_major_id`` A→B, nên báo cáo doanh thu-theo-ngành (đọc resolved
LIVE) chuyển sạch tiền đã thu từ ngành A sang B — lệch sổ kế toán (tiền thực thu
cho A khi hồ sơ còn ở A).

Chốt nghiệp vụ (owner): doanh thu được ghi nhận cho ngành TẠI THỜI ĐIỂM Payment
verified, BẤT BIẾN. Cột này snapshot ngành đó trên chính phiếu thu:

* ``recognized_major_id INT NULL FK major_program SET NULL`` — stamp =
  ``fee.resolved_major_id`` lúc payment chuyển 'verified', CHỈ với TUITION fee
  (lệ phí xét tuyển không phân bổ ngành → NULL). Không đổi khi reprice/
  resnapshot. NULL = "Chưa xác định" (thu khi fee chưa chốt ngành).

Backfill: các payment ĐÃ GHI NHẬN (verified/refunded) thuộc tuition fee ←
``fee.resolved_major_id`` hiện tại. Prod chưa ai đổi ngành (flag OFF) nên resolved
= ngành gốc → backfill chính xác. Pending/rejected + application payment để NULL.

Cột thuần cộng thêm, mọi báo cáo hiện tại CHƯA đọc field này (đọc ở PR report
riêng) → deploy no-op về hành vi.

Revision ID: majchg1g_pay_recmajor_20260724
Revises: majchg1d_notif_seed_20260723
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# ⚠️ Revision ID ≤ 32 ký tự (alembic_version.version_num VARCHAR(32)).
revision: str = "majchg1g_pay_recmajor_20260724"
down_revision: Union[str, None] = "majchg1d_notif_seed_20260723"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "payment"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "recognized_major_id",
            sa.Integer(),
            sa.ForeignKey("major_program.id", ondelete="SET NULL"),
            nullable=True,
            comment="Ngành ghi nhận doanh thu tại thời điểm verified (bất "
                    "biến; tuition-only, NULL nếu chưa xác định).",
        ),
    )
    op.create_index(
        "ix_payment_recognized_major_id",
        TABLE,
        ["recognized_major_id"],
        unique=False,
    )
    # Backfill: payment ĐÃ GHI NHẬN (verified/refunded) thuộc TUITION fee ←
    # fee.resolved_major_id hiện tại (prod chưa đổi ngành nên = ngành gốc).
    # Pending/rejected + application để NULL (không phân bổ ngành / chưa chốt).
    op.execute(
        """
        UPDATE payment p
        SET recognized_major_id = f.resolved_major_id
        FROM invoice i
        JOIN fee f ON f.id = i.fee_id
        WHERE p.invoice_id = i.id
          AND p.status IN ('verified', 'refunded')
          AND f.fee_type = 'tuition'
          AND f.resolved_major_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_payment_recognized_major_id", table_name=TABLE)
    op.drop_column(TABLE, "recognized_major_id")
