"""Sổ tiền thừa: idempotency theo payment + nguồn phát sinh.

Đi kèm bản vá mở sổ ``OverpaymentRecord`` tại điểm settlement. Hai hàng rào ở
tầng CSDL:

1. ``uq_overpayment_payment`` — MỘT phiếu thu chỉ sinh ĐÚNG MỘT khoản thừa.
   Không có nó, mỗi lần retry (verify lại, import chạy lại, callback gateway
   lặp) là thêm một nghĩa vụ trả nợ cho cùng số tiền. Phép kiểm ở tầng service
   lo luồng bình thường; ràng buộc này là hàng rào cuối khi hai lượt chạy song
   song cùng vượt qua phép kiểm ấy.

2. ``source_type`` — phân biệt khoản thừa do GHI TIỀN (`payment_settlement`)
   với khoản do đổi giá sau thu (`invoice_reprice`) hay đối soát tay
   (`manual_reconciliation`).

⚠️ Hàng lịch sử để **NULL**, cố ý. Bảng cũ không có cột nào ghi nguồn gốc, nên
provenance của chúng KHÔNG truy được — đoán rồi ghi vào là bịa ra một sự thật.
Prod hiện có 2 hàng như vậy (phát sinh 29/07/2026 do áp chính sách giảm 30% học
phí HK1 sau khi đã thu); `resolution_notes` của chúng nói rõ nguyên nhân nghiệp
vụ, nhưng đó là văn bản người viết, không phải provenance kỹ thuật.

PREFLIGHT: nếu dữ liệu đã có hai hàng cùng ``payment_id``, migration DỪNG thay
vì để `ADD CONSTRAINT` đổ giữa chừng với thông báo khó hiểu — và tuyệt đối
không tự xoá hàng nào: đó là sổ nợ, không phải rác.

Revision ID: ovp20260811
Revises: mrg20260811
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ovp20260811"
down_revision: Union[str, None] = "mrg20260811"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UQ = "uq_overpayment_payment"
_CHK = "chk_overpayment_source_type_valid"


def upgrade() -> None:
    conn = op.get_bind()

    # ── PREFLIGHT: payment_id trùng thì DỪNG ──
    trung = conn.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT payment_id FROM overpayment_record
                GROUP BY payment_id HAVING count(*) > 1
            ) t
            """
        )
    ).scalar_one()
    if trung:
        raise RuntimeError(
            f"[ovp20260811] Có {trung} payment_id xuất hiện nhiều lần trong "
            "overpayment_record. Ràng buộc UNIQUE sẽ đổ, và migration KHÔNG tự "
            "xoá hàng nào — đây là sổ nợ, mỗi hàng là một khoản tiền của người "
            "học.\n"
            "    Tra cứu: SELECT payment_id, count(*), sum(overpayment_amount) "
            "FROM overpayment_record GROUP BY payment_id HAVING count(*) > 1;\n"
            "    Nghiệp vụ phải gộp/huỷ trước, rồi chạy lại."
        )

    # ── source_type: cột mới, hàng cũ để NULL ──
    op.add_column(
        "overpayment_record",
        sa.Column(
            "source_type",
            sa.String(length=30),
            nullable=True,
            comment="payment_settlement | invoice_reprice | manual_reconciliation",
        ),
    )
    op.create_index(
        "ix_overpayment_record_source_type",
        "overpayment_record",
        ["source_type"],
    )
    op.create_check_constraint(
        _CHK,
        "overpayment_record",
        "source_type IS NULL OR source_type IN "
        "('payment_settlement', 'invoice_reprice', 'manual_reconciliation')",
    )

    # ── idempotency theo payment ──
    op.create_unique_constraint(_UQ, "overpayment_record", ["payment_id"])


def downgrade() -> None:
    op.drop_constraint(_UQ, "overpayment_record", type_="unique")
    op.drop_constraint(_CHK, "overpayment_record", type_="check")
    op.drop_index("ix_overpayment_record_source_type", table_name="overpayment_record")
    op.drop_column("overpayment_record", "source_type")
