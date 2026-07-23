"""major-change reprice 1A — fee columns for accountant-confirmation cycle.

Feature "đổi ngành có khấu trừ phiếu thu + kế toán xác nhận": khi officer đổi
ngành trên hồ sơ đã đóng học phí HK1, ``reprice_for_major_change`` định giá lại
Fee tại chỗ (giữ ``paid_amount``), ghi luôn ``invoice.amount``, rồi bật cờ chờ
kế toán duyệt. Ba cột read-model phục vụ gate + worklist + audit của chu kỳ đó:

* ``awaiting_accountant_confirmation BOOLEAN NOT NULL DEFAULT false`` — cờ "đang
  chờ kế toán xác nhận đổi ngành". Bật ở reprice, tắt ở confirm. Là một VẾ của
  ``_major_change_cycle_open`` (vế kia = ``admission_profile.major_change_requested``).
* ``major_change_from_academic_info_id INT NULL FK offering_academic_info SET NULL``
  — snapshot ngành CŨ (trước khi reprice) để hiển thị "A→B" cho kế toán.
* ``major_change_flagged_at TIMESTAMPTZ NULL`` — thời điểm bật cờ.

KHÔNG thêm giá trị ``FeeStatusEnum`` mới (cờ là cột riêng, không đụng máy trạng
thái phí). Cột thuần cộng thêm, mọi hàng cũ nhận default false / NULL — deploy
với ``MAJOR_CHANGE_REPRICE_ENABLED=False`` là no-op tuyệt đối.

Revision ID: majchg1a_fee_cols_20260723
Revises: admderivedcols20260721
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "majchg1a_fee_cols_20260723"
down_revision: Union[str, None] = "admderivedcols20260721"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "fee"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "awaiting_accountant_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Đổi ngành: fee đang chờ kế toán xác nhận (bật ở reprice, tắt ở confirm).",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "major_change_from_academic_info_id",
            sa.Integer(),
            sa.ForeignKey("offering_academic_info.id", ondelete="SET NULL"),
            nullable=True,
            comment="Đổi ngành: snapshot OfferingAcademicInfo ngành CŨ (hiển thị A→B cho kế toán).",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "major_change_flagged_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Đổi ngành: thời điểm bật awaiting_accountant_confirmation (UTC).",
        ),
    )
    # Partial index phục vụ worklist kế toán ("các fee đang chờ xác nhận"). Rất
    # thưa (chỉ hàng đang trong chu kỳ) nên partial WHERE = true là đủ + rẻ.
    op.create_index(
        "ix_fee_awaiting_accountant_confirmation",
        TABLE,
        ["awaiting_accountant_confirmation"],
        unique=False,
        postgresql_where=sa.text("awaiting_accountant_confirmation = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fee_awaiting_accountant_confirmation", table_name=TABLE
    )
    op.drop_column(TABLE, "major_change_flagged_at")
    op.drop_column(TABLE, "major_change_from_academic_info_id")
    op.drop_column(TABLE, "awaiting_accountant_confirmation")
