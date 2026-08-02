"""Hàng rào ở TẦNG SCHEMA — đường ``POST /api/leads`` đi thẳng vào đây.

Vì sao cần tệp riêng thay vì dựa vào test nhập-từ-tệp: đường nhập CSV đã
``strip()`` và ``astype(str)`` từ trước khi chạm schema, nên nó **không bao giờ**
đưa xuống một khoảng trắng trần hay một số nguyên. Ba lỗ dưới đây chỉ lộ ra khi
gọi thẳng ``LeadCreate`` / ``LeadUpdate``, tức đúng thứ API nhận từ giao diện.
"""

import pytest
from pydantic import ValidationError

from app import schemas


def _base(**ghi_de):
    """Bộ trường tối thiểu để dựng ``LeadCreate`` hợp lệ."""
    data = {
        "full_name": "Nguyen Van A",
        "phone": "0901234567",
        "source": "website",
        "unit_id": 1,
    }
    data.update(ghi_de)
    return data


class TestSoDienThoaiChinh:
    @pytest.mark.parametrize("gia_tri", ["   ", "\t", "\n", " \t\n ", "\t\n"])
    def test_chi_gom_khoang_trang_bi_tu_choi(self, gia_tri):
        """``min_length=1`` KHÔNG chặn được: ``"   "`` dài 3 ký tự.

        Trước bản vá, giá trị này được ghi thẳng vào cơ sở dữ liệu qua
        ``POST /api/leads``.
        """
        with pytest.raises(ValidationError):
            schemas.LeadCreate(**_base(phone=gia_tri))

    @pytest.mark.parametrize("gia_tri", ["---", "...", "( )", "//", "-"])
    def test_chi_gom_ky_tu_phan_cach_bi_tu_choi(self, gia_tri):
        with pytest.raises(ValidationError):
            schemas.LeadCreate(**_base(phone=gia_tri))

    def test_dau_vao_khong_phai_chuoi_thanh_loi_validate_chu_khong_phai_500(self):
        """JSON number: ``.strip()`` trên ``int`` ném ``AttributeError``.

        Pydantic để lọt lỗi đó ra ngoài thành **500**, trong khi đây là dữ liệu
        người dùng gửi sai — nó phải là 422 kèm thông báo đọc được.
        """
        with pytest.raises(ValidationError):
            schemas.LeadCreate(**_base(phone=901234567))

    def test_so_hop_le_van_qua(self):
        lead = schemas.LeadCreate(**_base(phone="+84 901 234 567"))
        assert lead.phone == "0901234567"


class TestSoDienThoaiPhu:
    def test_o_trong_van_hop_le(self):
        """`phone2` là trường tuỳ chọn — chặn nhầm ô trống sẽ loại phần lớn tệp thật."""
        assert schemas.LeadCreate(**_base(phone2="")).phone2 is None
        assert schemas.LeadCreate(**_base(phone2="   ")).phone2 is None

    def test_ky_tu_phan_cach_bi_tu_choi(self):
        with pytest.raises(ValidationError):
            schemas.LeadCreate(**_base(phone2="---"))


class TestGioiHanDoDai:
    """Khớp cột DB (``models/lead.py``: String(100) / String(255)).

    Không khớp thì ô quá dài qua được Pydantic rồi mới chết ở tầng DB bằng
    ``DataError`` — mà lần chèn là theo LÔ, nên một dòng kéo đổ cả lô đang chạy.
    """

    def test_education_level_qua_100_bi_tu_choi(self):
        with pytest.raises(ValidationError):
            schemas.LeadCreate(**_base(education_level="x" * 101))

    def test_education_level_dung_100_van_qua(self):
        assert len(schemas.LeadCreate(**_base(education_level="x" * 100)).education_level) == 100

    def test_location_qua_255_bi_tu_choi(self):
        with pytest.raises(ValidationError):
            schemas.LeadCreate(**_base(location="x" * 256))

    def test_location_dung_255_van_qua(self):
        assert len(schemas.LeadCreate(**_base(location="x" * 255)).location) == 255

    @pytest.mark.parametrize(
        "truong, do_dai",
        [("education_level", 101), ("location", 256)],
    )
    def test_duong_cap_nhat_cung_gioi_han(self, truong, do_dai):
        with pytest.raises(ValidationError):
            schemas.LeadUpdate(**{truong: "x" * do_dai})


class TestDuongCapNhat:
    """`LeadUpdate` là nhánh anh em — cùng validator, hậu quả khác.

    Ở đây trả ``None`` cho một chuỗi rác nghĩa là **âm thầm xoá** số điện thoại
    đang có, chứ không phải chặn một bản ghi mới.
    """

    @pytest.mark.parametrize("gia_tri", ["---", "...", "( )"])
    def test_ky_tu_phan_cach_khong_lam_xoa_sdt(self, gia_tri):
        with pytest.raises(ValidationError):
            schemas.LeadUpdate(phone=gia_tri)

    def test_khoang_trang_bi_tu_choi(self):
        with pytest.raises(ValidationError):
            schemas.LeadUpdate(phone="   ")

    def test_dau_vao_khong_phai_chuoi_thanh_loi_validate(self):
        with pytest.raises(ValidationError):
            schemas.LeadUpdate(phone=901234567)

    def test_phone2_o_trong_van_ve_None(self):
        assert schemas.LeadUpdate(phone2="").phone2 is None
