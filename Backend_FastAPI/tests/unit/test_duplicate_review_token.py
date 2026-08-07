"""Phiếu xác nhận nghi trùng — chữ ký, hạn, và từng vế ràng buộc.

Đây là quyền xác nhận DUY NHẤT sau đợt thiết kế lại, nên mỗi vế ràng buộc cần
một ca riêng nói đúng hậu quả của việc thiếu nó. Một ca gộp kiểu "đổi lung
tung rồi kiểm bị từ chối" sẽ vẫn xanh khi ai đó bỏ sót một vế — vì các vế còn
lại đủ làm nó đỏ.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.duplicate_review_token import (
    TTL_GIAY,
    RangBuoc,
    cap_phieu,
    soat_phieu,
)

pytestmark = pytest.mark.unit

_KHI = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)


def _rb(**doi) -> RangBuoc:
    goc = dict(
        flow="manual",
        user_id=7,
        unit_id=14,
        fee_id=101,
        invoice_id=202,
        amount=Decimal("2000000"),
        payment_date=_KHI,
        guard_version=5,
    )
    goc.update(doi)
    return RangBuoc(**goc)


class TestPhieuHopLe:
    def test_dung_hoan_canh_thi_qua(self):
        rb = _rb()
        assert soat_phieu(cap_phieu(rb), rb) is True

    def test_so_tien_cung_gia_tri_khac_cach_viet_van_qua(self):
        """`2000000` và `2000000.00` là cùng một số tiền.

        Giao diện gửi chuỗi, Pydantic dựng `Decimal` — cách viết đi qua nhiều
        tầng thì đổi, giá trị thì không. Nếu chữ ký bám cách viết, người ghi sẽ
        bị từ chối vì một khác biệt không ai nhìn thấy.
        """
        phieu = cap_phieu(_rb(amount=Decimal("2000000")))
        assert soat_phieu(phieu, _rb(amount=Decimal("2000000.00"))) is True

    def test_cung_thoi_diem_khac_mui_gio_van_qua(self):
        gio_vn = _KHI.astimezone(timezone(timedelta(hours=7)))
        assert soat_phieu(cap_phieu(_rb()), _rb(payment_date=gio_vn)) is True

    def test_hai_lan_cap_cho_cung_hoan_canh_ra_hai_phieu_khac_nhau(self):
        """`jti` làm mỗi phiếu là một chứng từ riêng, truy được trong log."""
        assert cap_phieu(_rb()) != cap_phieu(_rb())


class TestTungVeRangBuoc:
    """Mỗi vế một ca. Xem docstring đầu tệp về lý do không gộp."""

    @pytest.mark.parametrize(
        "doi, vi_sao",
        [
            ({"user_id": 8}, "người khác mượn được phiếu của người này"),
            ({"unit_id": 15}, "phiếu mang được sang đơn vị khác"),
            ({"unit_id": None}, "phạm vi toàn hệ khác phạm vi một đơn vị"),
            ({"fee_id": 102}, "phiếu của khoản phí này mở được khoản phí khác"),
            ({"invoice_id": 203}, "phiếu của hoá đơn này mở được hoá đơn khác"),
            ({"amount": Decimal("2000001")}, "đổi số tiền mà xác nhận vẫn sống"),
            (
                {"payment_date": _KHI + timedelta(days=1)},
                "đổi ngày thu mà xác nhận vẫn sống",
            ),
            (
                {"guard_version": 6},
                "tập ứng viên đã đổi mà phiếu cũ vẫn được nhận — đúng lỗ hổng "
                "mà cả đợt thiết kế lại này sinh ra để đóng",
            ),
            ({"flow": "import"}, "phiếu của luồng ghi tay mở được luồng nhập lô"),
        ],
    )
    def test_lech_mot_ve_thi_bi_tu_choi(self, doi, vi_sao):
        phieu = cap_phieu(_rb())
        assert soat_phieu(phieu, _rb(**doi)) is False, vi_sao

    def test_nhap_lo_khoa_ca_lo_lan_dong(self):
        goc = dict(flow="import", batch_id=9, row_no=2, invoice_id=None)
        rb = _rb(**goc)
        assert soat_phieu(cap_phieu(rb), rb) is True
        for doi, vi_sao in (
            ({"batch_id": 10}, "phiếu của lô này dùng được cho lô khác"),
            ({"row_no": 3}, "phiếu của dòng này dùng được cho dòng khác"),
        ):
            assert soat_phieu(cap_phieu(rb), _rb(**{**goc, **doi})) is False, vi_sao


class TestPhieuMeo:
    def test_het_han_thi_bi_tu_choi(self):
        rb = _rb()
        phieu = cap_phieu(rb)
        sau = datetime.now(timezone.utc) + timedelta(seconds=TTL_GIAY + 1)
        assert soat_phieu(phieu, rb, now=sau) is False

    def test_ngay_truoc_khi_het_han_van_qua(self):
        """Chặn ĐÚNG mốc, không chặn sớm — nếu không, TTL thực tế ngắn hơn TTL
        đã hứa và người ghi bị đá ra giữa chừng mà không ai giải thích được."""
        rb = _rb()
        phieu = cap_phieu(rb)
        sat_han = datetime.now(timezone.utc) + timedelta(seconds=TTL_GIAY - 5)
        assert soat_phieu(phieu, rb, now=sat_han) is True

    @pytest.mark.parametrize(
        "phieu",
        [
            "",
            "khong-co-dau-cham",
            "a.b.c",
            "!!!.!!!",
            "e30.",  # thân hợp lệ, chữ ký rỗng
        ],
    )
    def test_thân_meo_thi_bi_tu_choi_chu_khong_no(self, phieu):
        assert soat_phieu(phieu, _rb()) is False

    def test_sua_mot_ky_tu_trong_than_thi_chu_ky_hong(self):
        phieu = cap_phieu(_rb())
        than, ky = phieu.split(".")
        hong = ("A" if than[0] != "A" else "B") + than[1:]
        assert soat_phieu(f"{hong}.{ky}", _rb()) is False

    def test_giu_than_doi_chu_ky_thi_hong(self):
        than = cap_phieu(_rb()).split(".")[0]
        ky_khac = cap_phieu(_rb(fee_id=999)).split(".")[1]
        assert soat_phieu(f"{than}.{ky_khac}", _rb()) is False

    def test_khong_nhan_phieu_ky_bang_khoa_khac(self):
        """Khoá ký phải là khoá DẪN XUẤT riêng, không phải `SECRET_KEY` trần.

        Lẫn khoá giữa hai loại chứng từ là đường để một chứng từ loại này được
        nhận ở chỗ đang chờ loại kia.
        """
        import base64
        import hashlib
        import hmac
        import json

        from app.config import settings

        than = json.dumps(
            {
                **_rb()._than(),
                "exp": int(datetime.now(timezone.utc).timestamp()) + 600,
                "jti": "gia-mao",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        ky = hmac.new(settings.SECRET_KEY.encode(), than, hashlib.sha256).digest()
        gia = (
            base64.urlsafe_b64encode(than).rstrip(b"=").decode()
            + "."
            + base64.urlsafe_b64encode(ky).rstrip(b"=").decode()
        )
        assert soat_phieu(gia, _rb()) is False
