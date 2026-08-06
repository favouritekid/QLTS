"""Số tiền phiếu thu không được có quá 2 chữ số thập phân.

Vì sao đây không phải chuyện vài xu: cột là ``Numeric(15,2)``, nên ``100.001``
được **làm tròn âm thầm** thành ``100.00`` khi ghi. Mọi phép so khớp trên
``amount`` — đối soát ngân hàng, và sắp tới là luật dò trùng — chạy trên con số
người dùng **gửi**, nên ``100.001`` không khớp phiếu ``100.00`` đã có, trong khi
hai bản ghi nằm cạnh nhau trong DB thì y hệt nhau. Tức là một hàng rào chống
trùng có thể bị đi vòng bằng cách gõ thêm một chữ số.

Từ chối thẳng ở tầng schema là cách duy nhất giữ cho hai tầng nhìn thấy **cùng
một** con số.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.finance import PaymentCreate

pytestmark = pytest.mark.unit


def _payload(amount):
    return {"invoice_id": 1, "method_id": 1, "amount": amount}


class TestPaymentAmountPrecision:
    @pytest.mark.parametrize(
        "amount",
        ["100", "100.0", "100.00", "100.5", "100.99", "1000000"],
    )
    def test_toi_da_hai_chu_so_le_duoc_chap_nhan(self, amount):
        assert PaymentCreate(**_payload(amount)).amount == Decimal(amount)

    @pytest.mark.parametrize(
        "amount",
        ["1000.000", "1000.0000", "100.500", "0.10000", "1000000.00000000"],
    )
    def test_so_khong_o_duoi_khong_bi_tu_choi_oan(self, amount):
        """Câu hỏi đúng là "làm tròn có MẤT giá trị không", không phải "gõ mấy chữ số".

        `1000.000` đúng bằng `1000.00` và ghi xuống `Numeric(15,2)` không mất
        gì. Đếm chữ số thì nó bị chặn — và bất kỳ client nào định dạng tiền với
        số chữ số lẻ cố định (hoặc một luồng đối soát) đều bị chặn ở một giá
        trị không có gì sai.
        """
        assert PaymentCreate(**_payload(amount)).amount == Decimal(amount)

    @pytest.mark.parametrize(
        "amount",
        ["100.001", "100.999", "0.005", "1000000.123456"],
    )
    def test_qua_hai_chu_so_le_bi_tu_choi(self, amount):
        """Ca quyết định: không được làm tròn hộ rồi ghi tiếp.

        Nếu ràng buộc này bị gỡ, ``100.001`` lọt qua schema, né phép so khớp
        với phiếu ``100.00``, rồi vẫn hạ xuống DB thành ``100.00``.
        """
        with pytest.raises(ValidationError) as exc:
            PaymentCreate(**_payload(amount))
        assert "decimal places" in str(exc.value)

    def test_dang_khoa_hoc_cung_bi_soi(self):
        """``1E-3`` là cùng một số với ``0.001`` — đừng để cách viết lách qua."""
        with pytest.raises(ValidationError):
            PaymentCreate(**_payload("1E-3"))

    def test_so_nguyen_dang_mu_van_hop_le(self):
        """``1E+6`` = 1.000.000, exponent dương ⇒ không có phần lẻ nào."""
        assert PaymentCreate(**_payload("1E+6")).amount == Decimal("1000000")

    @pytest.mark.parametrize("amount", ["0", "-5", "-0.01"])
    def test_khong_duong_van_bi_chan_nhu_cu(self, amount):
        with pytest.raises(ValidationError):
            PaymentCreate(**_payload(amount))


class TestPaymentDateNgoaiTam:
    """Năm ngoài tầm nghiệp vụ phải là 422, không phải 500.

    Hàng rào dò trùng cộng/trừ vài ngày quanh mốc rồi quy về múi giờ Việt Nam:
    `9999-12-31` tràn khỏi `date.max`, `0001-01-01` tràn lúc đổi múi giờ. Cả hai
    ném `OverflowError` — thứ router không bắt — cho một chuỗi ngày người gọi tự
    gõ. Đường XEM TRƯỚC đã chặn khoảng năm này từ trước; ca dưới giữ cho đường
    GHI không tụt lại.
    """

    @pytest.mark.parametrize("ngay", ["9999-12-31T00:00:00", "0001-01-01T00:00:00"])
    def test_nam_ngoai_khoang_bi_tu_choi(self, ngay):
        payload = _payload("100")
        payload["payment_date"] = ngay
        with pytest.raises(ValidationError):
            PaymentCreate(**payload)

    @pytest.mark.parametrize("ngay", ["1900-01-01T00:00:00", "2100-12-31T23:59:59"])
    def test_hai_dau_khoang_van_hop_le(self, ngay):
        payload = _payload("100")
        payload["payment_date"] = ngay
        assert PaymentCreate(**payload).payment_date is not None

    def test_khong_truyen_ngay_van_hop_le(self):
        """`payment_date` là tuỳ chọn — máy chủ tự lấy thời điểm hiện tại."""
        assert PaymentCreate(**_payload("100")).payment_date is None
