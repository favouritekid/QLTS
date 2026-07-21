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

from app.utils.exceptions import ValidationError


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
        # Header thật luôn có đuôi → phải khớp theo CỤM CON, không so cả chuỗi
        ["Họ và tên học sinh", "SĐT học sinh"],
        ["Họ tên thí sinh", "Số điện thoại phụ huynh"],
        ["Họ và tên", "Số điện thoại (Zalo)"],
        ["﻿Họ và tên", "SĐT"],                # BOM do Excel ghi CSV
    ],
)
def test_resolve_columns_accepts_vietnamese_headers(headers):
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(headers)
    assert "full_name" in found, f"không nhận cột tên trong {headers}"
    assert "phone" in found, f"không nhận cột sđt trong {headers}"


@pytest.mark.unit
def test_dt_column_is_never_read_as_phone():
    """"DT" trong danh sách trường = Dân tộc, và sau khi bỏ dấu thì "ĐT"
    (điện thoại) cũng ra "dt" → không phân biệt được. Nhận nhầm sẽ khiến cả
    file import 0 dòng trong im lặng, tệ hơn hẳn báo thiếu cột."""
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(["STT", "Họ và tên", "DT", "Lớp", "SĐT"])
    assert found["phone"] == "SĐT"
    assert found["full_name"] == "Họ và tên"


@pytest.mark.unit
def test_split_surname_given_name_rejected_loudly():
    """File tách "Họ đệm" + "Tên": nhận cột "Tên" làm họ tên sẽ lưu tên cụt
    mà không báo gì — chặn to tiếng thay vì hỏng dữ liệu âm thầm."""
    from app.services.sms_contact_service import _resolve_columns

    with pytest.raises(ValidationError) as exc:
        _resolve_columns(["Họ đệm", "Tên", "SĐT"])
    assert "gộp" in str(exc.value.detail).lower()


@pytest.mark.unit
def test_ten_alone_still_accepted():
    """Chỉ có 1 cột tên (không tách họ) thì vẫn nhận như trước."""
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(["Tên", "SĐT"])
    assert found["full_name"] == "Tên"


@pytest.mark.unit
@pytest.mark.parametrize(
    "headers",
    [
        ["Tên trường", "SĐT"],      # "ten" là cụm con → không được gán bừa
        ["Tên lớp", "SĐT"],
        ["Tên ngành", "SĐT"],
    ],
)
def test_weak_name_alias_is_exact_match_only(headers):
    from app.services.sms_contact_service import _resolve_columns

    found = _resolve_columns(headers)
    assert "full_name" not in found


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


# ===================================================================
# Ô số điện thoại sau khi qua tay Excel
# ===================================================================
@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0912345678", "0912345678"),        # bình thường
        ("912345678", "0912345678"),         # Excel ép số → mất số 0 đầu
        ('="0912345678"', "0912345678"),     # lớp bọc chống-ép-kiểu ở file mẫu
        ('="912345678"', "0912345678"),      # bọc + đã mất số 0
        (" 0912345678 ", "0912345678"),      # thừa khoảng trắng
        ("+84912345678", "+84912345678"),    # dạng quốc tế: không đụng
        ("02363822655", "02363822655"),      # số cố định: không đụng
        ("123456789", "123456789"),          # 9 số nhưng sai đầu số → giữ nguyên
        ("", ""),
    ],
)
def test_clean_phone_cell(raw, expected):
    from app.services.sms_contact_service import _clean_phone_cell

    assert _clean_phone_cell(raw) == expected
