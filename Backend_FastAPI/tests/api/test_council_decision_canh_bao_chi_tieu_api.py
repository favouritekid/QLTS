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
    # Dữ liệu giả không đặt tên hiển thị cho đường xét ⇒ đặt để đo được ``nhan`` của ô đường xét (đặc tả 3.8).
    await qd._sql("UPDATE admission_path SET display_name = 'Đường xét giả K' WHERE id = :p", p=o["path"])
    await qd._sql(
        "UPDATE offering_academic_info SET annual_admission_quota = :n WHERE id = :a", n=nam, a=o["ai"]
    )
    await qd._sql("UPDATE admission_path SET admit_quota = :n WHERE id = :p", n=duong, p=o["path"])
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    r = await qd._ghi(client, ad, bo["id"], so="501", so_hs=1)
    return r, o


async def _nhan(o):
    """Nhãn hiển thị mong đợi của hai ô (vòng giao diện, đặc tả 3.8) — đọc bằng SQL từ kết nối khác."""
    nganh = await qd._q1(
        "SELECT mp.name FROM offering_academic_info a JOIN program_offering po ON po.id = a.offering_id "
        "JOIN major_program mp ON mp.id = po.program_id WHERE a.id = :a",
        a=o["ai"],
    )
    duong = await qd._q1("SELECT display_name FROM admission_path WHERE id = :p", p=o["path"])
    return nganh, duong


async def test_n9_vuot_chi_tieu_nganh_va_duong_xet_van_ghi_kem_canh_bao(client, hs, ad):  # noqa: F811
    r, o = await _ghi_voi_chi_tieu(client, ad, hs, 0, 0)
    assert r.status_code == 201, r.text  # N9: không chặn
    assert await qd._q1("SELECT count(*) FROM council_decision WHERE trang_thai = 'hieu_luc'") == 1
    nganh, duong = await _nhan(o)
    assert nganh and duong, "tiền điều kiện: dữ liệu giả có tên ngành + tên đường xét"
    assert r.json()["canh_bao_vuot_chi_tieu"] == [
        {
            "loai": "nganh",
            "chi_tieu": 0,
            "academic_info_id": o["ai"],
            "da_dung_cong_bo": 1,
            "da_dung_phe_duyet_cu": 1,
            "admission_path_id": None,
            "da_dung": None,
            "nhan": nganh,
        },
        {
            "loai": "duong_xet",
            "chi_tieu": 0,
            "academic_info_id": None,
            "da_dung_cong_bo": None,
            "da_dung_phe_duyet_cu": None,
            "admission_path_id": o["path"],
            "da_dung": 1,
            "nhan": duong,
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


# ── F264 (Codex lần 16): hai cách đếm ô ngành cho số KHÁC nhau ─────────────────────────────────────────────────
# Em thứ hai (``SACH[1]``, KHÔNG nằm trong bộ) được đặt để chiếm chỗ ở ĐÚNG MỘT cách đếm. Tiền điều kiện đo bằng
# chính hai hàm đếm trước khi ghi (dựng dữ liệu sai thì ca đỏ ở tiền điều kiện, không đỏ vì cảnh báo). Chỉ tiêu
# năm = 1, đường xét không đặt ⇒ sau khi ghi em ``SACH[0]``: một cách đếm = 1 (đầy, chưa vượt), cách kia = 2 (vượt)
# ⇒ phải cảnh báo, kèm ĐÚNG hai số. Bỏ một nhánh khỏi ``max(cong_bo, phe_duyet)`` ⇒ đúng một trong hai ca đỏ.


async def _hai_cach_dem(o):
    from app.database import AsyncSessionLocal
    from app.services import quota_occupancy_service as qos

    async with AsyncSessionLocal() as db:
        return (
            await qos.dem_theo_thong_tin_hoc_vu(db, academic_info_id=o["ai"]),
            await qos.dem_theo_nganh_nam(db, offering_id=o["off"], academic_year=2026),
        )


async def _ghi_sau_khi_dat_em_thu_hai(client, ad, hs, dat_em_thu_hai):
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=1)
    await qd._sql("UPDATE admission_path SET admit_quota = NULL WHERE id = :p", p=o["path"])
    p2 = hs[SACH[1]][1]
    await qd._sql("UPDATE admission_profile SET status = 'approved' WHERE id = :p", p=p2)
    await dat_em_thu_hai(p2, o)
    truoc = await _hai_cach_dem(o)
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    r = await qd._ghi(client, ad, bo["id"], so="502", so_hs=1)
    return r, o, truoc


async def test_f264_chi_phe_duyet_cu_vuot(client, hs, ad):  # noqa: F811
    async def dat(p2, o):
        # Phê duyệt cũ đếm theo lead → ngành + năm; công bố đếm nguyện vọng "trúng" ⇒ em 2 không có nguyện vọng
        # trúng nào, chạy bộ máy nguyện vọng (không rơi vào nhánh kiểu cũ), lead trỏ đúng ngành của ô K.
        await qd._sql(
            "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
            o=o["off"],
            p=p2,
        )
        await qd._sql("UPDATE admission_profile SET uses_choice_engine = TRUE WHERE id = :p", p=p2)
        await qd._sql(
            "UPDATE admission_profile_choice SET decision = 'pending' WHERE admission_profile_id = :p", p=p2
        )

    r, o, truoc = await _ghi_sau_khi_dat_em_thu_hai(client, ad, hs, dat)
    assert truoc == (0, 1), "tiền điều kiện: (công bố, Phê duyệt cũ) trước khi ghi = %r" % (truoc,)
    assert r.status_code == 201, r.text
    assert r.json()["canh_bao_vuot_chi_tieu"] == [
        {
            "loai": "nganh",
            "chi_tieu": 1,
            "academic_info_id": o["ai"],
            "da_dung_cong_bo": 1,
            "da_dung_phe_duyet_cu": 2,
            "admission_path_id": None,
            "da_dung": None,
            "nhan": (await _nhan(o))[0],
        }
    ], r.text


async def test_f264_chi_cong_bo_vuot(client, hs, ad):  # noqa: F811
    async def dat(p2, o):
        # Công bố đếm nguyện vọng "trúng" trên đường xét thuộc học vụ của ô K; Phê duyệt cũ đếm theo lead ⇒ lead của
        # em 2 trỏ sang một ngành KHÁC; nguyện vọng đầu của em 2 chuyển sang đường xét K và đánh dấu trúng.
        khac = await qd._q1(
            "SELECT offering_id FROM offering_academic_info WHERE offering_id <> :o ORDER BY id LIMIT 1", o=o["off"]
        )
        assert khac is not None, "seed thiếu ngành thứ hai"
        await qd._sql(
            "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
            o=khac,
            p=p2,
        )
        await qd._sql("UPDATE admission_profile SET uses_choice_engine = TRUE WHERE id = :p", p=p2)
        await qd._sql(
            "UPDATE admission_profile_choice SET decision = 'pending' WHERE admission_profile_id = :p", p=p2
        )
        await qd._sql(
            "UPDATE admission_profile_choice SET admission_path_id = :a, decision = 'admitted' WHERE id = ("
            # ưu tiên nguyện vọng ĐÃ ở đường xét K (tránh trùng cặp hồ sơ – đường xét nếu có ràng buộc duy nhất)
            "SELECT id FROM admission_profile_choice WHERE admission_profile_id = :p "
            "ORDER BY (admission_path_id = :a) DESC, display_order, id LIMIT 1)",
            a=o["path"],
            p=p2,
        )

    r, o, truoc = await _ghi_sau_khi_dat_em_thu_hai(client, ad, hs, dat)
    assert truoc == (1, 0), "tiền điều kiện: (công bố, Phê duyệt cũ) trước khi ghi = %r" % (truoc,)
    assert r.status_code == 201, r.text
    assert r.json()["canh_bao_vuot_chi_tieu"] == [
        {
            "loai": "nganh",
            "chi_tieu": 1,
            "academic_info_id": o["ai"],
            "da_dung_cong_bo": 2,
            "da_dung_phe_duyet_cu": 1,
            "admission_path_id": None,
            "da_dung": None,
            "nhan": (await _nhan(o))[0],
        }
    ], r.text


# ── K-1 (owner 11-11): cảnh báo vượt ở CẢ BA đường sinh / khôi phục Phần B; cảnh báo LƯU vào sự kiện (đặc tả 3.8) ──
async def _canh_bao_da_luu(decision_id, loai_su_kien):
    """Cảnh báo đã lưu trong ``so_lieu`` của sự kiện (bảng sự kiện độc lập) — đọc từ kết nối khác, SAU commit."""
    return await qd._q1(
        "SELECT so_lieu -> 'canh_bao_vuot_chi_tieu' FROM council_document_event WHERE decision_id = :d AND loai = :l",
        d=decision_id,
        l=loai_su_kien,
    )


def _bo_none(ds):
    """DTO trả về điền None cho trường không thuộc loại ô; bản lưu trong sự kiện là dict gốc (không có khoá ấy)
    ⇒ so sau khi bỏ khoá None — mọi khoá CÓ giá trị phải trùng đúng."""
    return [{k: v for k, v in c.items() if v is not None} for c in ds]


def _nganh(ds):
    return [(c["loai"], c["academic_info_id"], c["chi_tieu"]) for c in ds if c["loai"] == "nganh"]


async def test_k1_ghi_nhan_luu_canh_bao_vao_su_kien(client, hs, ad):  # noqa: F811
    r, o = await _ghi_voi_chi_tieu(client, ad, hs, 0, None)
    assert r.status_code == 201, r.text
    cb = r.json()["canh_bao_vuot_chi_tieu"]
    assert _nganh(cb) == [("nganh", o["ai"], 0)], r.text
    assert await _canh_bao_da_luu(r.json()["id"], "ghi_nhan") == _bo_none(cb)  # đúng bản trả về, không tính lại


async def test_k1_dieu_chinh_them_em_vuot_canh_bao(client, hs, ad):  # noqa: F811
    _, a = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    o = await _o_chi_tieu(hs, SACH[1], chi_tieu=0)  # ô của em SẼ THÊM: chỉ tiêu 0 ⇒ thêm 1 là vượt
    await qd._sql("UPDATE admission_path SET admit_quota = NULL WHERE id = :p", p=o["path"])
    bd = await qd._bo_ok(client, ad, hs, SACH[1:2], duong="/decisions/%d/bo-dieu-chinh" % a["id"])
    r = await qd._dieu_chinh(client, ad, a["id"], "801", set_id=bd["id"], so_hs=1)
    assert r.status_code == 201, r.text  # không chặn
    cb = r.json()["canh_bao_vuot_chi_tieu"]
    assert _nganh(cb) == [("nganh", o["ai"], 0)], r.text
    assert await _canh_bao_da_luu(r.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)


async def test_k1_dieu_chinh_chi_bo_dong_khong_canh_bao(client, hs, ad):  # noqa: F811
    # đối chứng: điều chỉnh CHỈ bỏ dòng (không dòng thêm) ⇒ không có gì chiếm thêm ⇒ danh sách rỗng
    _, a = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    await _o_chi_tieu(hs, SACH[0], chi_tieu=0)
    cu = await qd._dong_cua(a["id"], hs[SACH[0]][1])
    r = await qd._dieu_chinh(client, ad, a["id"], "801", bo_dong=[cu])
    assert r.status_code == 201, r.text
    assert r.json()["canh_bao_vuot_chi_tieu"] == [], r.text


async def test_k1_huy_ghi_nhan_bat_lai_vuot_canh_bao(client, hs, ad):  # noqa: F811
    _, a = await qd._qd_cua_bo(client, ad, hs, SACH[:1], "501")
    cu = await qd._dong_cua(a["id"], hs[SACH[0]][1])
    dc = (await qd._dieu_chinh(client, ad, a["id"], "801", bo_dong=[cu])).json()
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=0)  # SAU khi bỏ: ô trống; bật lại dòng ⇒ 1 > 0
    await qd._sql("UPDATE admission_path SET admit_quota = NULL WHERE id = :p", p=o["path"])
    r = await qd._huy_ghi_nhan(client, ad, dc["id"], "801")
    assert r.status_code == 200, r.text  # không chặn
    assert await qd._q1("SELECT bi_bo_boi_id FROM council_decision_row WHERE id = :d", d=cu) is None
    cb = r.json()["canh_bao_vuot_chi_tieu"]
    assert _nganh(cb) == [("nganh", o["ai"], 0)], r.text
    assert await _canh_bao_da_luu(dc["id"], "huy_ghi_nhan") == _bo_none(cb)


async def test_k1_huy_ghi_nhan_khong_bat_lai_khong_canh_bao(client, hs, ad):  # noqa: F811
    # đối chứng: huỷ ghi nhận Quyết định trúng tuyển (dòng của nó TẮT, không dòng nào bật lại) ⇒ rỗng
    r0, _ = await _ghi_voi_chi_tieu(client, ad, hs, 0, None)
    r = await qd._huy_ghi_nhan(client, ad, r0.json()["id"], "501")
    assert r.status_code == 200, r.text
    assert r.json()["canh_bao_vuot_chi_tieu"] == [], r.text
