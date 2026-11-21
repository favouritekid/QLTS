"""Sổ đăng ký vùng khoá tư vấn (advisory lock) PostgreSQL — MỘT nơi khai mọi vùng ``ns`` mới (đặc tả GĐ1b bản 3.6 §5.2,
§5.3; hợp đồng API GĐ1b bản 4 §2.1).

Mọi khoá ở đây dạng HAI khoá int4 ``(ns, k)``. Khoá hai-int4 và khoá một-bigint KHÔNG chồng nhau (tài liệu PostgreSQL), nên
chỉ cần so với các vùng hai-khoá đang có trong mã:

- ``815074`` — ``public_lead_intake_service._INTAKE_ADVISORY_NS`` (khoá thứ hai = ``hashtext(phone)``);
- ``hashtext('council_document_set:dung')`` — ``council_document_repository.BUILD_LOCK_KEY`` (khoá thứ hai = 0);
- ``hashtext('invoice_number:INV')`` — ``invoice_service`` (khoá thứ hai = năm).

Vùng mới PHẢI là int4 dương và khác các giá trị trên — ``tests/unit/test_gd1b_lo_khoa_tu_van.py`` kiểm hằng, còn
``tests/api/test_gd1b_lo_khoa_tu_van_csdl.py`` tính ``hashtext`` THẬT trên CSDL rồi so.

Ánh xạ mã lô → khoá thứ hai: ``k = int.from_bytes(batch_id.bytes[0:4], "big") & 0x7FFFFFFF`` (31 bit ngẫu nhiên của UUID v4,
luôn dương ⇒ ``pg_locks.objid`` không lệch dấu). Va chạm chỉ tạo "đang có người giữ" giả (409 / ``running``), không bao giờ
tạo "gián đoạn" giả hay ghi sai.
"""

from __future__ import annotations

from uuid import UUID

INT4_MAX = 2**31 - 1

#: Lô duyệt giấy: khoá PHIÊN của người chạy trên kết nối L riêng (§5.3 bước 1); khoá GIAO DỊCH của ``finalize`` (§5.7 bước
#: 2) và của bước dọn bản xem trước (§5.2 bước 1) — cùng không gian nên chặn nhau đúng như thiết kế.
BULK_VERIFY_BATCH_NS = 711_170_001

#: Xem trước lô: khoá GIAO DỊCH theo người dùng ``(ns_preview, user_id)`` (§5.2 bước 0) — hai yêu cầu xem trước cùng người
#: chạy lần lượt; người khác nhau không chặn nhau.
BULK_VERIFY_PREVIEW_NS = 711_170_002

#: GĐ2 — "khoá năm" (đặc tả GĐ2 bản 3 §7.2 bước 1, §2 sổ vùng khoá tư vấn): khoá GIAO DỊCH ``(ns, năm tuyển sinh)``. Mọi
#: thao tác ghi bảng chỉ tiêu năm (GĐ2-A: sửa / khoá / mở khoá) và — từ GĐ2-C — khoá lần xét của cùng năm lấy khoá này
#: TRƯỚC mọi khoá dòng ⇒ chạy lần lượt. Khoá thứ hai = năm (int4 dương).
REVIEW_YEAR_NS = 711_170_003

#: Vùng hai-khoá đã có trước GĐ1b (để test so). Đổi / thêm vùng ở mã khác ⇒ cập nhật đây.
EXISTING_INT_NAMESPACES = (815074,)
EXISTING_HASHTEXT_NAMESPACES = ("council_document_set:dung", "invoice_number:INV")

#: Mọi vùng do sổ này cấp.
REGISTERED_NAMESPACES = (BULK_VERIFY_BATCH_NS, BULK_VERIFY_PREVIEW_NS, REVIEW_YEAR_NS)


def batch_lock_key(batch_id: UUID) -> int:
    """Khoá thứ hai của lô: 31 bit đầu của UUID, luôn dương (int4)."""
    return int.from_bytes(batch_id.bytes[0:4], "big") & 0x7FFFFFFF
