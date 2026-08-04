# app/constants/export_formats.py
"""Hằng định dạng tệp xuất — MỘT nguồn cho mọi đường export.

Trước đây mỗi service/router tự khai lại chuỗi media type xlsx (dài 74 ký tự,
gõ sai một chữ là trình duyệt tải về file không mở được) và tự nhớ phải chèn
BOM cho CSV. Gom về đây để:

* Không ai gõ lại chuỗi MIME dài.
* ``CSV_UTF8_BOM`` đứng cạnh lời giải thích vì sao nó BẮT BUỘC: Excel bản
  tiếng Việt đọc CSV không BOM theo ANSI ⇒ tiếng Việt mojibake. Kế toán sửa
  file rồi upload lại thì lệch cột luôn.

⚠️ KHÔNG gom ``sanitize_csv_cell`` vào đây — sanitize là việc của tầng XUẤT
và **chỉ áp cho ô TEXT do người dùng nhập**. Ô số/tiền đi qua nó sẽ bị thêm
dấu nháy (``DANGEROUS_PREFIXES`` có cả ``-``) ⇒ số âm thành text, Excel không
cộng được. Xem ``app/utils/csv_helpers.py``.
"""

# Media type cho .xlsx (OOXML spreadsheet).
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# Media type cho .csv — LUÔN kèm charset để trình duyệt không đoán nhầm.
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"

# BOM UTF-8. Prepend vào nội dung CSV trước khi ``.encode("utf-8")``.
# (Tương đương ghi bằng codec ``utf-8-sig``.)
CSV_UTF8_BOM = "﻿"

# Định dạng số tiền cho openpyxl — dùng chung để mọi báo cáo hiển thị giống nhau.
MONEY_NUMBER_FORMAT = "#,##0"

# Định dạng ép ô về TEXT — giữ số 0 đầu của CCCD / mã tham chiếu / năm học.
TEXT_NUMBER_FORMAT = "@"

__all__ = [
    "XLSX_MEDIA_TYPE",
    "CSV_MEDIA_TYPE",
    "CSV_UTF8_BOM",
    "MONEY_NUMBER_FORMAT",
    "TEXT_NUMBER_FORMAT",
]
