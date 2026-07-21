# tests/unit/test_sms_import_headers.py
"""
Unit test nhận diện header file import liên hệ SMS.

Bối cảnh: `_resolve_columns` chuẩn hóa header chỉ bằng lower/strip/thay dấu
cách nên alias viết cho tiếng Việt KHÔNG BAO GIỜ khớp header có dấu
("Họ tên" → "họ_tên" ≠ "ho_ten") → file hợp lệ bị từ chối 400 "thiếu cột bắt
buộc" (log prod 13-07, group_id=2). Nay bỏ dấu trước khi so alias.

Thuần logic, không chạm DB/HTTP.
"""
import pytest


@pytest.mark.unit
@pytest.mark.parametrize(
    "headers",
    [
        ["full_name", "phone"],                    # tên chuẩn ASCII
        ["Họ tên", "Số điện thoại"],               # có dấu
        ["Họ và tên", "SĐT"],                      # đ + viết tắt
        ["HỌ VÀ TÊN", "Số Điện Thoại"],            # in hoa có dấu
        ["Họ tên học sinh", "Số điện thoại"],      # biến thể hay gặp
        ["  Họ tên  ", " SĐT "],                   # thừa khoảng trắng
        ["Ho ten", "So dien thoai"],               # gõ không dấu
    ],
)
def test_resolve_columns_accepts_vietnamese_headers(headers):
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(headers)
    assert "full_name" in found, f"không nhận cột tên trong {headers}"
    assert "phone" in found, f"không nhận cột sđt trong {headers}"


@pytest.mark.unit
def test_resolve_columns_maps_back_to_original_header():
    """Trả về TÊN CỘT THẬT (chưa chuẩn hóa) để đọc DataFrame."""
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(["Họ và tên", "SĐT", "Ghi chú"])
    assert found["full_name"] == "Họ và tên"
    assert found["phone"] == "SĐT"
    assert found["note"] == "Ghi chú"


@pytest.mark.unit
def test_resolve_columns_missing_required():
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(["Mã học sinh", "Lớp"])
    assert "full_name" not in found
    assert "phone" not in found


@pytest.mark.unit
def test_resolve_columns_keeps_first_on_collision():
    """2 header chuẩn hóa về cùng khóa → giữ cột xuất hiện TRƯỚC."""
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(["Họ tên", "Ho ten"])
    assert found["full_name"] == "Họ tên"


@pytest.mark.unit
def test_slugify_still_ascii_after_refactor():
    """`_slugify` dùng chung helper bỏ dấu — không đổi hành vi group code."""
    from app.services.sms_contact_service import _slugify

    assert _slugify("Trường THPT Số 1 Đông Hòa") == "truong-thpt-so-1-dong-hoa"
    assert _slugify("") == "group"
