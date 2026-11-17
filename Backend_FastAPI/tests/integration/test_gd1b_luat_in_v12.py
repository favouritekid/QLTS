# -*- coding: utf-8 -*-
"""GĐ1b S5 — luật in v1.2 (đặc tả bản 3.6 §4.6, PH-1 cách (a)). DỮ LIỆU GIẢ (``tests/fixtures/hoi_dong_seed.py``).

* giấy ĐÃ duyệt in theo hình thức ĐÃ XÁC NHẬN (``verified_format``) — khác bộ xuất v1.1 (chỉ có hình thức lúc nhận): phép
  so N1 không kiểm được v1.2, nên có ca riêng này (đặc tả §4.6 "Thay bằng ca kiểm dữ liệu giả");
* giấy đã duyệt mà ``verified_format`` trống ⇒ bước dựng DỪNG, mã ``verified_format_invalid`` — không âm thầm in "C";
* giấy CHƯA duyệt in như v1.1 (hình thức lúc nhận).
"""
import pytest
import pytest_asyncio
from sqlalchemy import text

import app.database as csdl
from app.services import council_candidate_service as doc
from app.services import council_document_render_service as bo_dung
from tests.fixtures.hoi_dong_seed import seed_hoi_dong

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
CA = "nhieu_nv_khoang_trang"  # ca mang đủ bộ giấy DU_GIAY: học bạ THPT ĐÃ duyệt, lúc nhận = certified_copy


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        return await seed_hoi_dong(conn)


async def _dat_hinh_thuc_da_duyet(pid: int, code: str, verified_format):
    async with csdl.engine.begin() as c:
        n = (
            await c.execute(
                text(
                    "UPDATE profile_document pd SET verified_format = :f FROM config_document_type dt "
                    "WHERE dt.id = pd.document_type_id AND pd.profile_id = :p AND dt.code = :c AND pd.status = 'verified'"
                ),
                {"f": verified_format, "p": pid, "c": code},
            )
        ).rowcount
    assert n == 1


async def _dong(cccd: str):
    return (await doc.read_profiles_by_code(csdl.engine, [cccd], academic_year=2026)).rows[0]


async def test_giay_da_duyet_in_theo_hinh_thuc_da_xac_nhan_khong_theo_luc_nhan(hs):
    cccd, pid = hs[CA]
    await _dat_hinh_thuc_da_duyet(pid, "hoc_ba_thpt", "original")
    r = await _dong(cccd)
    assert (r.s_hocba, r.f_hocba) == ("verified", "original")
    assert bo_dung.row_data_error(r) is None
    assert bo_dung._symbol(r.s_hocba, r.f_hocba) == "C"


async def test_giay_da_duyet_thieu_hinh_thuc_da_xac_nhan_thi_dung_dung(hs):
    cccd, pid = hs[CA]
    await _dat_hinh_thuc_da_duyet(pid, "hoc_ba_thpt", None)
    r = await _dong(cccd)
    assert (r.s_hocba, r.f_hocba) == ("verified", "")
    assert bo_dung.row_data_error(r) == ("verified_format_invalid", "f_hocba")
    with pytest.raises(Exception) as e:
        bo_dung._prepare([r])
    assert "luật in v1.2" in str(e.value)


async def test_ma_verified_format_invalid_co_cau_tieng_viet_cho_ban_xem_truoc():
    """Bản xem trước lấy câu từ ``ROW_DATA_ERROR_REASONS.get(mã, mã)`` — thiếu câu thì người dùng thấy MÃ thô."""
    cau = bo_dung.ROW_DATA_ERROR_REASONS.get(bo_dung.ERROR_VERIFIED_FORMAT_INVALID)
    assert cau and cau != bo_dung.ERROR_VERIFIED_FORMAT_INVALID and "đã duyệt" in cau


async def test_giay_chua_duyet_van_in_theo_hinh_thuc_luc_nhan(hs):
    cccd, _ = hs[CA]
    r = await _dong(cccd)
    # Bằng tốt nghiệp ở DU_GIAY: paper_submitted, lúc nhận = photo ⇒ in "Pt" như v1.1.
    assert (r.s_bang, r.f_bang) == ("paper_submitted", "photo")
    assert bo_dung._symbol(r.s_bang, r.f_bang) == "Pt"


def test_nhan_luat_render_la_v12():
    assert bo_dung.RENDER_RULE == "v1.2"
