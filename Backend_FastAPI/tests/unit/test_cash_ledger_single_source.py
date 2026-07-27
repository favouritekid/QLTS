"""Lock-in: MỌI báo cáo tiền phải lấy danh sách loại giao dịch từ MỘT nguồn.

Ba nơi trả lời cùng câu hỏi "thu được bao nhiêu?" — báo cáo tuần tuyển sinh, Excel
tổng hợp năm, sổ kế toán theo kỳ. Trước khi hợp nhất, mỗi nơi tự khai danh sách và
đã drift thật: Excel `JOIN payment` kiểu INNER làm rơi giao dịch không có
`payment_id`; sổ kế toán bỏ hẳn `reversal` nên lô thu bị huỷ vẫn nằm trong doanh
thu kỳ. Test này khoá lại: thêm literal `'payment'`/`'refund'`/`'reversal'` vào một
file riêng lẻ là đỏ, buộc sửa ở `app/constants/cash_ledger.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.constants.cash_ledger import (
    CASH_EXCLUDED_TYPES,
    CASH_INFLOW_TYPES,
    CASH_OUTFLOW_TYPES,
    CASH_TRANSACTION_TYPES,
    sql_in_list,
)

_APP = Path(__file__).resolve().parents[2] / "app"
_WEEKLY_REPO = _APP / "repositories" / "admission_report_repository.py"
_EXCEL = _APP / "services" / "admission_summary_export_service.py"
_ACCOUNTING = _APP / "services" / "accounting_service.py"

# Literal loại giao dịch tiền — xuất hiện trong 3 file này nghĩa là có người khai
# lại danh sách thay vì import.
_TYPE_LITERAL = re.compile(r"""['"](payment|refund|reversal)['"]""")


def test_inflow_outflow_phu_kin_va_khong_chong_nhau():
    assert set(CASH_INFLOW_TYPES) | set(CASH_OUTFLOW_TYPES) == set(
        CASH_TRANSACTION_TYPES
    ), "inflow + outflow phải phủ đúng tập loại giao dịch tiền"
    assert not (set(CASH_INFLOW_TYPES) & set(CASH_OUTFLOW_TYPES)), (
        "một loại không thể vừa là tiền vào vừa là tiền ra"
    )
    assert not (set(CASH_TRANSACTION_TYPES) & set(CASH_EXCLUDED_TYPES)), (
        "adjustment bị loại khỏi dòng tiền — không được nằm cả hai bên"
    )


def test_ba_bao_cao_khong_khai_lai_danh_sach():
    """Không file nào được hard-code literal loại giao dịch tiền."""
    offenders: list[str] = []
    for path in (_WEEKLY_REPO, _EXCEL, _ACCOUNTING):
        src = path.read_text(encoding="utf-8")
        # Bỏ dòng comment (tiếng Việt trong comment có nêu tên loại là bình thường).
        code_lines = [
            line for line in src.splitlines()
            if not line.lstrip().startswith("#") and not line.lstrip().startswith("--")
        ]
        for line in code_lines:
            if _TYPE_LITERAL.search(line):
                offenders.append(f"{path.name}: {line.strip()[:90]}")
    assert not offenders, (
        "Các dòng sau khai lại loại giao dịch tiền thay vì import từ "
        "app/constants/cash_ledger.py — sửa một nơi thì nơi này sẽ không tự cập "
        f"nhật: {offenders}"
    )


def test_ba_bao_cao_deu_import_nguon_chung():
    for path in (_WEEKLY_REPO, _EXCEL, _ACCOUNTING):
        src = path.read_text(encoding="utf-8")
        assert "constants.cash_ledger" in src, (
            f"{path.name} không import nguồn chung — nó đang tự định nghĩa dòng tiền"
        )


def test_excel_dung_left_join_payment():
    """`payment_id` nullable ⇒ INNER JOIN làm Excel rơi tiền so với báo cáo tuần."""
    src = _EXCEL.read_text(encoding="utf-8")
    assert "LEFT JOIN payment pay" in src, (
        "Excel phải LEFT JOIN payment; INNER JOIN bỏ giao dịch payment_id NULL "
        "trong khi báo cáo tuần vẫn tính (bucket chưa-xác-định-ngành) → 2 file lệch"
    )
    assert "JOIN payment pay ON" not in src.replace("LEFT JOIN payment pay ON", ""), (
        "còn sót một INNER JOIN payment"
    )


def test_sql_in_list_render_dung():
    assert sql_in_list(("payment",)) == "('payment')"
    rendered = sql_in_list(CASH_TRANSACTION_TYPES)
    for t in CASH_TRANSACTION_TYPES:
        assert f"'{t}'" in rendered
