# app/models/base.py
from sqlalchemy import String
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import TypeDecorator

# Tạo một lớp Base dùng chung cho tất cả các model
Base = declarative_base()


class TruncatedString(TypeDecorator):
    """``VARCHAR(n)`` tự cắt giá trị GHI xuống đúng ``n`` ký tự (PR-D, F12).

    Dành cho cột lưu chuỗi do MÁY KHÁCH gửi mà nghiệp vụ không cần nguyên văn — User-Agent trong các bảng nhật ký. Trước
    đây một User-Agent dài hơn cột làm câu ghi nhật ký lỗi ``22001`` ⇒ thao tác nghiệp vụ 500 (lẻ) / ``system_error`` (lô).

    MỘT chỗ chủ sở hữu cho mỗi bảng đích: độ dài đọc từ CHÍNH khai báo cột (``TruncatedString(500)``), áp ở tầng kiểu nên
    phủ MỌI đường ghi — đối tượng ORM, ``__table__.insert().values(...)``, executemany. Nơi gọi KHÔNG tự cắt ``[:n]``.
    DDL không đổi: kiểu biên dịch thành ``VARCHAR(n)`` như ``String(n)`` (không cần migration).
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        limit = self.impl.length
        if isinstance(value, str) and limit is not None and len(value) > limit:
            return value[:limit]
        return value
