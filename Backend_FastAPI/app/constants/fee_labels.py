# app/constants/fee_labels.py
"""Nhãn tiếng Việt cho loại phí / trạng thái khoản phí — dùng cho TỆP XUẤT.

🔴 Các chuỗi ở đây phải khớp TỪNG CHỮ với nhãn người dùng đang thấy trên màn
hình (``frontend/src/types/finance.types.ts`` — ``FEE_TYPE_LABELS`` và
``FEE_STATUS_LABELS``). Lý do: sheet phụ của tệp xuất bảo kế toán "lọc theo cột
Loại phí trước khi cộng", nhưng nếu tệp ghi "Lệ phí xét tuyển" trong khi màn
hình ghi "Lệ phí hồ sơ" thì Ctrl+F từ tệp về màn hình không ra gì, và hai bên
trông như hai hệ thống khác nhau.

Đây là bản sao có chủ đích của nhãn frontend (backend không đọc được TS), nên
đổi một bên thì PHẢI đổi bên kia — ``tests/unit/test_fee_labels_match_frontend.py``
đọc thẳng tệp TS và so từng khoá để chặn drift.
"""

# Khớp frontend/src/types/finance.types.ts::FEE_TYPE_LABELS
FEE_TYPE_LABELS = {
    "application": "Lệ phí hồ sơ",
    "tuition": "Học phí",
    "enrollment": "Phí nhập học",
    "insurance": "Bảo hiểm",
    "dormitory": "Ký túc xá",
    "other": "Khác",
}

# Khớp frontend/src/types/finance.types.ts::FEE_STATUS_LABELS
FEE_STATUS_LABELS = {
    "pending": "Chờ tính phí",
    "calculated": "Đã tính phí",
    "invoiced": "Đã xuất hóa đơn",
    "partial": "Thanh toán một phần",
    "paid": "Đã thanh toán",
    "overdue": "Quá hạn",
    "waived": "Đã miễn giảm",
    "cancelled": "Đã hủy",
}

__all__ = ["FEE_TYPE_LABELS", "FEE_STATUS_LABELS"]
