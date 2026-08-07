# -*- coding: utf-8 -*-
"""Điều phối bước xem trước: thứ tự hàng rào, số liệu, và ranh giới router.

🔴 Thứ tự các bước ở đây LÀ hàng rào. Ca ``test_thu_tu_hang_rao`` ghi lại dãy
lời gọi thật chứ không kiểm sự hiện diện — kiểm hiện diện thì đảo thứ tự vẫn
xanh, mà đảo thứ tự đúng là lỗi cần chặn.
"""

import pytest
from types import SimpleNamespace

from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_preview_service import (
    chuan_bi_xem_truoc,
    dem_so_lieu_nguon,
)
from app.services.dorm_sync_service import TargetSnapshot

pytestmark = pytest.mark.unit

_CAU_HINH = DormSyncConfig(
    "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts", "1"
)


def _row(**ghi_de):
    base = dict(
        qlts_profile_id=9001,
        full_name="Nguyễn Văn An",
        source_gender_raw="Nam",
        program_name="Cao đẳng Điều dưỡng",
        degree_level="Cao đẳng",
        academic_year=2026,
        officer_qlts_id=101,
        unit_id=14,
        profile_status="confirmed",
        contact_phone="0912345678",
        contact_phone2=None,
    )
    base.update(ghi_de)
    return SimpleNamespace(**base)


def _api_gia(thu_tu=None, nam_mo=(2026,)):
    class _Api:
        def __init__(self, *a, **kw):
            if thu_tu is not None:
                thu_tu.append("dung_api")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_open_academic_years(self):
            if thu_tu is not None:
                thu_tu.append("nam_mo")
            return nam_mo

        async def fetch_target_snapshot(self, nam, cohort_ids):
            if thu_tu is not None:
                thu_tu.append("snapshot_dich")
            return TargetSnapshot(rows=(), fingerprint="c" * 32)

    return _Api


async def _chay(rows, *, thu_tu=None, nam_mo=(2026,), academic_year=2026):
    async def _cohort(nam, **kw):
        if thu_tu is not None:
            thu_tu.append("cohort")
        return rows

    return await chuan_bi_xem_truoc(
        cau_hinh=_CAU_HINH,
        secret="khoa-ky",
        actor_id=7,
        academic_year=academic_year,
        now_ts=1_000_000,
        api_factory=_api_gia(thu_tu, nam_mo),
        cohort_loader=_cohort,
    )


# ---------------------------------------------------------------------------
# Thứ tự hàng rào
# ---------------------------------------------------------------------------


async def test_thu_tu_hang_rao():
    """Đọc nguồn → dựng API → kiểm năm → hỏi đích. Đúng dãy, đúng một lần."""
    thu_tu = []

    await _chay([_row()], thu_tu=thu_tu)

    assert thu_tu == ["cohort", "dung_api", "nam_mo", "snapshot_dich"]


async def test_cohort_RONG_thi_khong_cham_KTX():
    """Nguồn rỗng + ghi = hạ cờ TOÀN BỘ năm đó, mà mọi con số đều khớp nhau."""
    thu_tu = []

    ket_qua = await _chay([], thu_tu=thu_tu)

    assert ket_qua.can_apply is False
    assert ket_qua.preview_token is None
    assert ket_qua.snapshot_hash is None
    assert thu_tu == ["cohort"], "đã chạm sang KTX dù cohort rỗng"


async def test_nam_da_dong_thi_khong_hoi_anh_chup_dich():
    from app.utils.exceptions import BusinessRuleViolation

    thu_tu = []

    with pytest.raises(BusinessRuleViolation):
        await _chay([_row()], thu_tu=thu_tu, nam_mo=(2027,))

    assert "snapshot_dich" not in thu_tu


# ---------------------------------------------------------------------------
# profile_status fail-closed
# ---------------------------------------------------------------------------


async def test_thieu_profile_status_thi_DUNG_TRUOC_khi_cham_KTX():
    """🔴 Thiếu cột do lệch phiên bản KHÔNG được âm thầm ký ``null``.

    Bản trước dùng ``getattr(row, "profile_status", None)``. Hậu quả không phải
    một trường trống: dấu băm khai rằng MỌI hồ sơ đều "không rõ trạng thái", và
    nó khớp với chính nó ở bước ghi — chốt cho qua trong khi nó không hề nhìn
    thấy thứ nó sinh ra để canh.

    Và cổng phải đứng TRƯỚC lời gọi sang KTX: dấu băm nguồn tính SAU khi đã hỏi
    ảnh chụp đích, nên nổ ở đó nghĩa là đã gửi cả danh sách ``qlts_profile_id``
    sang hệ kia rồi mới dừng.
    """
    thieu = _row()
    del thieu.profile_status
    thu_tu = []

    with pytest.raises(RuntimeError) as loi:
        await _chay([thieu], thu_tu=thu_tu)

    assert "profile_status" in str(loi.value)
    # Chỉ SỐ ĐẾM, không danh tính người học.
    assert "Nguyễn Văn An" not in str(loi.value)
    assert thu_tu == ["cohort"], "đã chạm sang KTX dù hợp đồng dữ liệu chưa đạt"


async def test_du_profile_status_thi_di_tiep():
    """Vế ĐẢO: không có nó thì một cổng viết quá tay — chặn mọi lượt — vẫn xanh."""
    ket_qua = await _chay([_row()])

    assert ket_qua.can_apply is True
    assert ket_qua.preview_token is not None


# ---------------------------------------------------------------------------
# Số liệu khuyến cáo
# ---------------------------------------------------------------------------


def test_so_lieu_nguon_dem_dung_thu_chung_khai():
    """Ba con số dễ sai và đã sai một lần ở vỏ CLI.

    * "không có số liên hệ" nghĩa là KHÔNG CÓ SỐ NÀO — chỉ đếm ô chính sẽ báo
      nhầm những em chỉ khai số phụ là không liên hệ được;
    * "số bị bỏ vì quá dài" đếm SỐ, không phải HỒ SƠ, và phủ cả hai ô;
    * ô phụ bị bỏ vì TRÙNG số chính KHÔNG phải "quá dài" — đó là dữ liệu bình
      thường.
    """
    dai = "0" * 21
    rows = [
        _row(qlts_profile_id=1, contact_phone=None, contact_phone2=None),
        _row(qlts_profile_id=2, contact_phone=None, contact_phone2="0900000002"),
        _row(qlts_profile_id=3, contact_phone="0900000003", contact_phone2="0900000003"),
        _row(qlts_profile_id=4, contact_phone=dai, contact_phone2=dai),
        _row(qlts_profile_id=5, source_gender_raw="chưa rõ", degree_level=None),
        _row(qlts_profile_id=6, program_name=None),
    ]

    so = dem_so_lieu_nguon(rows)

    assert so.khong_co_so_lien_he == 1, "chỉ hồ sơ 1 không khai số nào"
    assert so.co_so_phu == 1, "hồ sơ 2; hồ sơ 3 trùng số chính nên không tính"
    assert so.so_bi_bo_vi_qua_dai == 2, "hồ sơ 4 đóng góp HAI số"
    assert so.khong_ro_gioi_tinh == 1
    assert so.chua_ro_trinh_do == 1
    assert so.chua_chot_nganh == 1


async def test_so_lieu_di_kem_ket_qua_xem_truoc():
    """Admin phải ĐỌC ĐƯỢC những con số này, không chỉ có chúng ở đâu đó."""
    ket_qua = await _chay([_row(), _row(qlts_profile_id=9002, source_gender_raw="?")])

    assert ket_qua.counts is not None
    assert ket_qua.counts.khong_ro_gioi_tinh == 1
    assert ket_qua.source_count == 2


# ---------------------------------------------------------------------------
# Ranh giới router
# ---------------------------------------------------------------------------


def test_router_KHONG_giu_nghiep_vu():
    """🔴 Router chỉ dựng phụ thuộc và serialize.

    Thứ tự các bước LÀ hàng rào. Để chuỗi ấy trong hàm handler nghĩa là nó chỉ
    kiểm được qua HTTP, và bước sau (sổ cái, máy trạng thái) sẽ chồng thêm vào
    cùng chỗ cho tới lúc không ai đọc nổi thứ tự nữa.

    ⚠️ Soi MÃ NGUỒN của handler. Kiểm hành vi không phân biệt được "router gọi
    service" với "router tự làm rồi cho ra cùng kết quả".
    """
    import inspect

    import app.routers.admin_v2_dorm_sync as router_module

    ma = inspect.getsource(router_module.xem_truoc.__wrapped__)

    assert "chuan_bi_xem_truoc(" in ma
    for dau_hieu in (
        "fetch_cohort",
        "fetch_target_snapshot",
        "fetch_open_academic_years",
        "hash_source_snapshot",
        "phat_hanh_token",
        "if not rows",
    ):
        assert dau_hieu not in ma, f"nghiệp vụ còn sót trong router: {dau_hieu}"
