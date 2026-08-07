# -*- coding: utf-8 -*-
"""Bối cảnh màn đồng bộ: năm học nào được chọn, và schema apply nhận gì.

🔴 Hai thứ được canh ở đây đều là "phạm vi của một lần ghi":

* năm học nào lên màn chọn — một năm đã đóng sổ lọt vào đây là dựng sẵn một
  lượt hạ cờ cả cohort của năm đó;
* request apply được mang theo trường gì — client đặt được ``academic_year``
  nghĩa là client chọn được phạm vi ghi.
"""

import pytest
from pydantic import ValidationError

from app.schemas.dorm_sync import (
    DormSyncApplyRequest,
    DormSyncContextResponse,
    DormSyncPreviewRequest,
)

pytestmark = pytest.mark.unit


class _PhanHoiGia:
    def __init__(self, *, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = [] if payload is None else payload
        self.headers = headers or {}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class _ClientGia:
    """Ghi lại tham số truy vấn — cổng lọc ``open`` phải quan sát được."""

    def __init__(self, phan_hoi):
        self.phan_hoi = phan_hoi
        self.calls = []

    async def get(self, url, headers=None, params=None):
        self.calls.append({"url": url, "params": params})
        return self.phan_hoi


def _api_voi(client):
    from app.services.dorm_sync_service import DormApi

    # Loopback: được miễn hàng rào đường truyền lẫn hàng rào project ref, và
    # client là đồ giả nên không gói tin nào rời khỏi tiến trình.
    api = DormApi("http://127.0.0.1:54321", "khoa-gia", expected_project_ref="")
    api._client = client
    return api


class _NguoiDung:
    """User giả — router chỉ đọc `.id` để ghi nhật ký."""

    def __init__(self, id_):
        self.id = id_


_CAU_HINH_GIA = None  # gán ngay dưới, sau khi import được lớp cấu hình


def _dung_cau_hinh_gia():
    from app.services.dorm_sync_config import DormSyncConfig

    return DormSyncConfig(
        "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts", "1"
    )


_CAU_HINH_GIA = _dung_cau_hinh_gia()


# ---------------------------------------------------------------------------
# Đọc năm học mở
# ---------------------------------------------------------------------------


async def test_chi_lay_nam_DANG_MO():
    """🔴 Cổng lọc nằm ở truy vấn, và ca này quan sát ĐÚNG nó.

    Một năm đã đóng sổ vẫn còn nguyên hàng trong ``dorm_academic_years``. Đưa
    nó lên màn chọn là dựng sẵn một lượt ghi vào năm mà bên đích đã chốt sổ —
    và lượt ấy hạ cờ đủ-điều-kiện của cả cohort năm đó.
    """
    client = _ClientGia(_PhanHoiGia(payload=[{"academic_year": 2026}]))

    nam = await _api_voi(client).fetch_open_academic_years()

    assert nam == (2026,)
    # Khẳng định BỘ LỌC, không chỉ kết quả: fake trả gì thì trả, thứ phải đúng
    # là câu hỏi gửi đi. Không có vế này thì gỡ hẳn `status=eq.open` vẫn xanh.
    assert client.calls[0]["params"]["status"] == "eq.open"
    assert client.calls[0]["url"].endswith("/dorm_academic_years")


async def test_nhieu_nam_mo_thi_sap_giam_dan_va_mac_dinh_la_lon_nhat():
    """Sắp ở PHÍA TA, không tin thứ tự phản hồi.

    Thứ tự của một truy vấn là thứ tự kế hoạch thực thi; "mặc định là năm lớn
    nhất" mà dựa vào nó thì đúng cho tới lần bảng thay đổi.
    """
    client = _ClientGia(
        _PhanHoiGia(
            payload=[
                {"academic_year": 2025},
                {"academic_year": 2027},
                {"academic_year": 2026},
            ]
        )
    )

    nam = await _api_voi(client).fetch_open_academic_years()

    assert nam == (2027, 2026, 2025)
    assert nam[0] == 2027, "mặc định phải là năm MỞ LỚN NHẤT"


async def test_khong_co_nam_mo_thi_danh_sach_RONG_chu_khong_doan():
    """Danh sách rỗng là câu trả lời HỢP LỆ, khác hẳn "không đọc được"."""
    client = _ClientGia(_PhanHoiGia(payload=[]))

    assert await _api_voi(client).fetch_open_academic_years() == ()


@pytest.mark.parametrize(
    "than, vi_sao",
    [
        ({"academic_year": 2026}, "phản hồi là object, không phải mảng"),
        (["2026"], "phần tử không phải object"),
        ([{"academic_year": "2026"}], "năm học là chuỗi"),
        ([{"academic_year": True}], "bool là lớp con của int"),
        ([{"academic_year": None}], "năm học null"),
        ([{}], "vắng hẳn trường"),
    ],
)
async def test_phan_hoi_sai_kieu_thi_TU_CHOI_ro_rang(than, vi_sao):
    """Sai kiểu thì DỪNG, không đoán.

    Một năm học đoán ra là một lượt ghi vào nhầm năm — và bước ghi ấy không có
    đường lùi.
    """
    client = _ClientGia(_PhanHoiGia(payload=than))

    with pytest.raises(RuntimeError) as loi:
        await _api_voi(client).fetch_open_academic_years()

    assert "Danh sách năm học của hệ KTX không đọc được" in str(loi.value), vi_sao


# ---------------------------------------------------------------------------
# Cấu hình thiếu ⇒ KHÔNG gọi sang KTX
# ---------------------------------------------------------------------------


async def test_thieu_cau_hinh_thi_khong_goi_KTX(monkeypatch):
    """🔴 Cổng cấu hình đứng TRƯỚC gói tin đầu tiên.

    Đây là cùng bài học với thứ tự snapshot → open ở vỏ CLI: mọi điều kiện đọc
    xong rồi mới được chạm sang hệ kia. Dựng ``DormApi`` với một đích chưa biết
    là gửi khoá secret đi trước khi trả lời được câu hỏi "đi tới đâu".
    """
    from app.utils.exceptions import DormSyncConfigError

    da_dung_api = []

    class _ApiKhongDuocDung:
        def __init__(self, *a, **kw):
            da_dung_api.append(True)
            raise AssertionError("đã dựng DormApi dù cấu hình thiếu")

    import app.routers.admin.dorm_sync as router_module

    monkeypatch.setattr(router_module, "DormApi", _ApiKhongDuocDung)
    monkeypatch.setattr(router_module.DormSyncConfig, "from_settings", classmethod(
        lambda cls, settings=None: (_ for _ in ()).throw(
            DormSyncConfigError("thiếu DORM_SUPABASE_URL")
        )
    ))

    # 🔴 Gọi hàm BÊN TRONG lớp bọc của limiter.
    #
    # Chính việc phải mở lớp bọc ra là bằng chứng thứ tự decorator đúng: nếu
    # `@limiter.limit` nằm NGOÀI `@router.get` thì `router.get` đăng ký hàm
    # chưa bọc, `__wrapped__` không tồn tại, và endpoint chạy KHÔNG giới hạn
    # dù nhìn vào mã vẫn thấy có rào. Ca `test_endpoint_that_su_bi_limiter_boc`
    # khoá riêng vế này.
    goc = router_module.lay_boi_canh.__wrapped__

    with pytest.raises(DormSyncConfigError):
        await goc(request=None, current_user=None)

    assert da_dung_api == []


def test_endpoint_that_su_bi_limiter_boc():
    """🔴 `@router.get` NGOÀI, `@limiter.limit` TRONG — soi ĐÚNG hàm đã đăng ký.

    Decorator áp từ dưới lên:

    * đúng thứ tự → limiter bọc trước, `router.get` đăng ký hàm ĐÃ BỌC;
    * ngược thứ tự → `router.get` đăng ký hàm THÔ, rồi limiter bọc cái tên ở
      cấp module. Endpoint trông như có rào mà route giữ bản không giới hạn.

    ⚠️ Cả hai trường hợp, ``lay_boi_canh`` ở cấp module ĐỀU có ``__wrapped__``.
    Bản đầu của ca này kiểm đúng thứ đó nên nó không thể đỏ — kiểm ngược đảo
    thứ tự decorator vẫn cho 19/19 xanh. Thứ phân biệt được là **object mà
    route đang giữ**.
    """
    import app.routers.admin.dorm_sync as router_module

    tuyen = [
        r for r in router_module.router.routes
        if getattr(r, "path", "") == "/dorm-sync/context"
    ]
    assert len(tuyen) == 1

    assert tuyen[0].endpoint is router_module.lay_boi_canh, (
        "route đang giữ hàm THÔ, không phải hàm đã qua limiter — "
        "thứ tự decorator đang ngược và endpoint chạy không giới hạn"
    )
    assert hasattr(tuyen[0].endpoint, "__wrapped__"), (
        "hàm đã đăng ký không phải lớp bọc của limiter"
    )


async def test_khong_co_nam_mo_thi_mac_dinh_la_None_KHONG_lui_ve_nam_nao(monkeypatch):
    """🔴 Vế fail-closed nằm ở ROUTER, nên phải kiểm ở router.

    Lõi trả tuple rỗng — điều đó đã có ca riêng. Nhưng thứ quyết định cái
    frontend nhận được là phép ánh xạ `() -> None` ở router. Không có ca này
    thì sửa nó thành `else 2026` vẫn xanh cả bộ, và màn hình dựng sẵn một lượt
    ghi vào năm mà bên đích chưa mở.
    """
    import app.routers.admin.dorm_sync as router_module

    class _ApiGia:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_open_academic_years(self):
            return ()

    monkeypatch.setattr(router_module, "DormApi", _ApiGia)
    monkeypatch.setattr(
        router_module.DormSyncConfig,
        "from_settings",
        classmethod(lambda cls, settings=None: _CAU_HINH_GIA),
    )

    ket_qua = await router_module.lay_boi_canh.__wrapped__(
        request=None, current_user=_NguoiDung(7)
    )

    assert ket_qua.open_academic_years == []
    assert ket_qua.default_academic_year is None


async def test_co_nam_mo_thi_mac_dinh_la_nam_LON_NHAT(monkeypatch):
    """Vế ĐẢO: có năm mở thì mặc định phải là năm lớn nhất, không phải nhỏ nhất.

    Không có vế này thì một bản vá lấy `nam_mo[-1]` vẫn xanh ở ca trên.
    """
    import app.routers.admin.dorm_sync as router_module

    class _ApiGia:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_open_academic_years(self):
            return (2027, 2026, 2025)

    monkeypatch.setattr(router_module, "DormApi", _ApiGia)
    monkeypatch.setattr(
        router_module.DormSyncConfig,
        "from_settings",
        classmethod(lambda cls, settings=None: _CAU_HINH_GIA),
    )

    ket_qua = await router_module.lay_boi_canh.__wrapped__(
        request=None, current_user=_NguoiDung(7)
    )

    assert ket_qua.open_academic_years == [2027, 2026, 2025]
    assert ket_qua.default_academic_year == 2027


# ---------------------------------------------------------------------------
# Schema: client KHÔNG đặt được phạm vi ghi
# ---------------------------------------------------------------------------


def test_apply_chi_nhan_preview_token():
    hop_le = DormSyncApplyRequest(preview_token="abc")
    assert hop_le.preview_token == "abc"


@pytest.mark.parametrize(
    "thua",
    [
        {"academic_year": 2026},
        {"operation_id": "5b2f1c8e-0000-0000-0000-000000000000"},
        {"force": True},
        {"snapshot_hash": "0" * 64},
    ],
)
def test_apply_TU_CHOI_moi_truong_ngoai_preview_token(thua):
    """🔴 ``extra="forbid"``, không phải mặc định "bỏ qua".

    Pydantic mặc định BỎ QUA trường lạ. Ở endpoint này bỏ qua là kiểu hỏng tệ
    nhất: một frontend cũ gửi kèm ``academic_year=2025`` nhận 200 và tin rằng
    lượt vừa chạy là cho năm 2025, trong khi server ghi vào năm đã ký trong
    token — và không có gì trên màn hình nói ra sự chênh lệch đó.

    ``operation_id`` cũng phải bị từ chối: nó do server sinh và ký, nhận từ
    client là mở lại đúng cửa chống-replay mà sổ cái sinh ra để đóng.
    """
    with pytest.raises(ValidationError) as loi:
        DormSyncApplyRequest(preview_token="abc", **thua)

    assert "extra" in str(loi.value).lower()


def test_apply_van_doi_preview_token():
    with pytest.raises(ValidationError):
        DormSyncApplyRequest()

    with pytest.raises(ValidationError):
        DormSyncApplyRequest(preview_token="")


def test_preview_nhan_nam_hoc_va_chan_gia_tri_vo_ly():
    assert DormSyncPreviewRequest(academic_year=2026).academic_year == 2026

    for xau in (1999, 2101):
        with pytest.raises(ValidationError):
            DormSyncPreviewRequest(academic_year=xau)

    with pytest.raises(ValidationError):
        DormSyncPreviewRequest(academic_year=2026, apply=True)


def test_context_cho_phep_mac_dinh_None():
    """Frontend PHẢI xử lý ca "chưa mở năm nào" thay vì tự điền năm hiện tại."""
    rong = DormSyncContextResponse()

    assert rong.open_academic_years == []
    assert rong.default_academic_year is None
