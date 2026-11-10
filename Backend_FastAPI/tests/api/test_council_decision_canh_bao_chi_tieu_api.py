# -*- coding: utf-8 -*-
"""N9 (đặc tả 5.3) — ghi nhận VẪN thành công (201) nhưng phản hồi kèm ``canh_bao_vuot_chi_tieu`` khi ô ngành /
đường xét bị VƯỢT sau khi ghi; đúng bằng chỉ tiêu / không đặt chỉ tiêu ⇒ không cảnh báo. Qua REQUEST THẬT."""
import pytest

from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_hai_phien_api import _o_chi_tieu
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration


async def _ghi_voi_chi_tieu(client, ad, hs, nam, duong):
    """Ghi nhận em ``SACH[0]`` vào ô K (chỉ tiêu năm ``nam``, chỉ tiêu đường xét ``duong``; None = không đặt).
    Sau khi ghi, ô K có ĐÚNG 1 chỗ đã dùng (dòng vừa ghi) ở mọi cách đếm."""
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=1)
    await qd._sql(
        "UPDATE offering_academic_info SET annual_admission_quota = :n WHERE id = :a", n=nam, a=o["ai"]
    )
    await qd._sql("UPDATE admission_path SET admit_quota = :n WHERE id = :p", n=duong, p=o["path"])
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    r = await qd._ghi(client, ad, bo["id"], so="501", so_hs=1)
    return r, o


async def test_n9_vuot_chi_tieu_nganh_va_duong_xet_van_ghi_kem_canh_bao(client, hs, ad):  # noqa: F811
    r, o = await _ghi_voi_chi_tieu(client, ad, hs, 0, 0)
    assert r.status_code == 201, r.text  # N9: không chặn
    assert await qd._q1("SELECT count(*) FROM council_decision WHERE trang_thai = 'hieu_luc'") == 1
    assert r.json()["canh_bao_vuot_chi_tieu"] == [
        {
            "loai": "nganh",
            "chi_tieu": 0,
            "academic_info_id": o["ai"],
            "da_dung_cong_bo": 1,
            "da_dung_phe_duyet_cu": 1,
            "admission_path_id": None,
            "da_dung": None,
        },
        {
            "loai": "duong_xet",
            "chi_tieu": 0,
            "academic_info_id": None,
            "da_dung_cong_bo": None,
            "da_dung_phe_duyet_cu": None,
            "admission_path_id": o["path"],
            "da_dung": 1,
        },
    ], r.text


@pytest.mark.parametrize("nam, duong", [(1, 1), (None, None), (5, None)])
async def test_n9_bang_hoac_duoi_chi_tieu_khong_canh_bao(client, hs, ad, nam, duong):  # noqa: F811
    r, _ = await _ghi_voi_chi_tieu(client, ad, hs, nam, duong)
    assert r.status_code == 201, r.text
    assert r.json()["canh_bao_vuot_chi_tieu"] == [], r.text


async def test_n9_chi_vuot_duong_xet(client, hs, ad):  # noqa: F811
    r, o = await _ghi_voi_chi_tieu(client, ad, hs, 1, 0)
    assert r.status_code == 201, r.text
    assert [(c["loai"], c["admission_path_id"]) for c in r.json()["canh_bao_vuot_chi_tieu"]] == [
        ("duong_xet", o["path"])
    ], r.text
