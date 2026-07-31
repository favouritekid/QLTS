"""Ô TRỐNG trong file import lead không được biến thành chuỗi "nan".

Ca thật (prod 30-07-2026): import 211 thí sinh, 7 em không có email → cả 7 dòng
bị pydantic từ chối với *"value is not a valid email address: 'nan'"*, dù
``Lead.email`` khai ``nullable=True`` (*"Email is optional"*) và **2425/2535 lead
trên production không có email**. Đường import tự dựng lên một ràng buộc mà không
tầng nào khác đặt ra.

Gốc rễ: pandas đọc ô trống thành ``NaN`` (float), và ``str(NaN)`` cho ra chuỗi
``"nan"`` — bốn ký tự hợp lệ, nên phép ``.strip() or None`` không lọc được.
"""
import io

import pandas as pd
import pytest

from app.services.lead_service import _bo_chu_thich_dau_tep, _cell_or_none

pytestmark = pytest.mark.unit


CSV_CO_O_TRONG = (
    "full_name,email,phone,source,education_level,location\n"
    "Nguyễn Văn A,a@example.com,0901234567,website,THPT,Đắk Lắk\n"
    "Trần Thị B,,0902345678,website,,\n"
)


def _doc_nhu_service():
    """Đọc CSV y hệt service (``dtype=str``) → trả về hai dòng dạng dict."""
    df = pd.read_csv(io.BytesIO(CSV_CO_O_TRONG.encode("utf-8")), dtype=str)
    return df.to_dict("records")


def test_o_trong_cua_pandas_that_su_la_nan_khong_phai_chuoi_rong():
    """Chốt tiền đề: nếu pandas đổi cách đọc ô trống thì cả bài toán này khác đi."""
    _, dong_thieu = _doc_nhu_service()
    assert pd.isna(dong_thieu["email"]), "ô trống phải là NaN"
    assert dong_thieu["email"] != "", "KHÔNG phải chuỗi rỗng — đó là cái bẫy"


def test_str_tren_o_trong_cho_ra_chuoi_nan():
    """Chứng minh vì sao lối viết cũ hỏng, để đừng ai 'đơn giản hoá' nó trở lại.

    ``str(NaN).strip() or None`` cho ra ``"nan"`` chứ không phải ``None``, vì
    ``"nan"`` là chuỗi có 3 ký tự nên vế ``or None`` không bao giờ chạy.
    """
    _, dong_thieu = _doc_nhu_service()
    assert str(dong_thieu["email"]).strip() == "nan"
    assert (str(dong_thieu["email"]).strip() or None) == "nan"


def test_helper_tra_None_cho_o_trong():
    _, dong_thieu = _doc_nhu_service()
    assert _cell_or_none(dong_thieu["email"]) is None
    assert _cell_or_none(dong_thieu["education_level"]) is None
    assert _cell_or_none(dong_thieu["location"]) is None


def test_helper_giu_nguyen_gia_tri_that():
    dong_du, _ = _doc_nhu_service()
    assert _cell_or_none(dong_du["email"]) == "a@example.com"
    assert _cell_or_none(dong_du["education_level"]) == "THPT"
    assert _cell_or_none(dong_du["location"]) == "Đắk Lắk"


@pytest.mark.parametrize(
    "vao,ra",
    [
        (None, None),
        (float("nan"), None),
        ("", None),
        ("   ", None),
        ("  x  ", "x"),
        (0, "0"),           # số 0 là giá trị THẬT, không được nuốt
        (False, "False"),
    ],
)
def test_helper_bien_bao(vao, ra):
    assert _cell_or_none(vao) == ra


def test_bo_chu_thich_dau_tep_bo_dung_phan_dau():
    """Chỉ bỏ dòng ``#`` Ở ĐẦU tệp, không đụng gì phía dưới."""
    tep = (
        b"# Lead Import Template\n"
        b"# Required columns: full_name, phone, source, unit_id\n"
        b"#\n"
        b"full_name,phone,source\n"
        b"Nguyen Van A,0900000001,website\n"
    )
    ra = _bo_chu_thich_dau_tep(tep)
    assert ra.startswith(b"full_name,phone,source\n")
    assert b"Nguyen Van A" in ra
    assert b"#" not in ra


def test_bo_chu_thich_khong_cat_du_lieu_co_dau_thang():
    """🔴 Vì sao KHÔNG dùng ``comment="#"`` của pandas.

    Tham số đó cắt từ dấu ``#`` ở BẤT KỲ đâu trong dòng, nên một địa chỉ như
    "Số 5 # ngõ 3" mất phần đuôi mà không báo gì. Ở đây dữ liệu phải nguyên vẹn.
    """
    tep = (
        b"# chu thich\n"
        b"full_name,phone,source,location\n"
        b"Nguyen Van A,0900000001,website,So 5 # ngo 3\n"
    )
    ra = _bo_chu_thich_dau_tep(tep)
    assert b"So 5 # ngo 3" in ra, "dữ liệu chứa dấu # bị cắt mất"

    # Và đọc bằng pandas thì ô đó phải còn nguyên.
    df = pd.read_csv(io.BytesIO(ra), dtype=str)
    assert df.iloc[0]["location"] == "So 5 # ngo 3"


def test_bo_chu_thich_khong_lam_gi_voi_tep_khong_co_chu_thich():
    tep = b"full_name,phone\nA,0900000001\n"
    assert _bo_chu_thich_dau_tep(tep) == tep


def test_moi_truong_chuoi_deu_di_qua_helper():
    """Chốt cấu trúc: không để một trường chuỗi nào quay lại lối ``str(...)`` trực tiếp.

    Yếu hơn test hành vi ở trên, nhưng bắt được ca thêm trường MỚI vào vòng lặp
    mà quên xử lý ô trống — đúng cách bug này ra đời (``phone2`` làm đúng,
    ``email`` ngay trên nó thì không).

    🔴 Khớp bằng BIỂU THỨC CHÍNH QUY chịu được khoảng trắng, không so chuỗi
    nguyên văn. ``pyproject.toml`` đặt ``line_length = 88`` còn dòng
    ``education_level`` dài 92 ký tự, nên chỉ cần chạy ``black .`` — lệnh nằm
    ngay trong CLAUDE.md như việc thường ngày — là black ngắt dòng đó ra và phép
    so nguyên văn thất bại, kéo theo một cổng CI bắt buộc đỏ với thông báo nói
    rằng ô trống sắp thành chuỗi "nan". Định dạng lại mã không được phép là một
    lỗi nghiệp vụ.
    """
    import inspect
    import re

    from app.services import lead_service

    src = inspect.getsource(lead_service.import_leads_from_file_content)
    for truong in ("full_name", "email", "source", "education_level", "location"):
        mau = re.compile(
            r"_cell_or_none\(\s*row_data\.get\(\s*"
            + re.escape(f'"{truong}"')
            + r"\s*,?\s*\)\s*,?\s*\)"
        )
        assert mau.search(src), (
            f"trường {truong!r} không đi qua _cell_or_none → ô trống sẽ thành "
            f'chuỗi "nan"'
        )
