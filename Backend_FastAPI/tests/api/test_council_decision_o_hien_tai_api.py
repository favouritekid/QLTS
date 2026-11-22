# -*- coding: utf-8 -*-
"""PR-1 GĐ1 — C2 (Codex phần B, owner 21-11 — CHẶN F230): văn bản điều chỉnh BỎ tên / văn bản huỷ / huỷ ghi nhận làm em
(vẫn chiếm chỗ — "Đã duyệt") mất dòng Quyết định hiệu lực ⇒ em quay về được đếm theo ô HIỆN TẠI (Phần A: ngành theo
``lead.offering_id`` + năm, nguyện vọng trúng, đường xét kiểu cũ) — ô ấy có thể KHÁC ô chụp của dòng. Owner: áp K-1 —
CHỈ CẢNH BÁO, vẫn ghi văn bản đã ký; cảnh báo chỉ ĐÚNG ô tăng số chỗ đã dùng; câu theo mẫu owner. Ô hiện tại được khoá
(MỘT lần ``lock_quota_cells`` cùng ô chụp, thứ tự chuẩn) và đếm lại DƯỚI khoá.

Qua REQUEST THẬT; số chỗ đo bằng chính các hàm đếm ở phiên khác. Dữ liệu: em P = ``SACH[0]`` (nguyện vọng in ở ô X = Ô tô
CĐ chính quy), ``lead.offering_id`` của P = ngành của ô Y (Dược CĐ chính quy) ⇒ X ≠ Y. Ô Y có sẵn 1 chỗ (em đơn vị khác,
"Đã duyệt", không Quyết định). Owner ví dụ 30 / 30 → 31 / 30 (báo vượt 1) và 29 / 30 → 30 / 30 (không báo); ở đây chỉ tiêu
1 ⇒ 1 / 1 → 2 / 1 (báo vượt 1) và chỉ tiêu 2 ⇒ 1 / 2 → 2 / 2 (không báo) — cùng hai ranh giới "đầy" / "vượt".

* C2-a — một văn bản, một người: bốn đường (điều chỉnh bỏ tên, huỷ hiệu lực, huỷ ghi nhận, huỷ ghi nhận văn bản điều chỉnh
  có dòng THÊM) × (đầy ⇒ vẫn ghi + cảnh báo vượt 1 đúng ô Y, câu owner, lưu vào sự kiện; thiếu một ⇒ không cảnh báo).
* C2-đường xét — em kiểu cũ (``applied_rules``) ⇒ ô ĐƯỜNG XÉT hiện tại tăng (chiều "công bố" của Phần A): đầy ⇒ câu owner
  "Đường xét Z (ngành Y): … vượt 1."; thiếu một ⇒ không báo.
* C2-b — hai phiên: thao tác (dừng ở câu ghi dòng bởi phiên CSDL thứ ba, đã giữ ô Y) ↔ Phê duyệt cũ ở ô Y ⇒ Phê duyệt CHỜ
  đúng phiên thao tác (``pg_blocking_pids``) rồi bị chặn "Vượt chỉ tiêu"; ô Y không vượt.
* C2-một-lần-khoá — điều chỉnh vừa THÊM (ô id cao) vừa BỎ (ô hiện tại id thấp) chen với Phê duyệt hàng loạt khoá [thấp,
  cao]: không vòng chờ (không câu "thử lại").

Codex PR-1 lượt 2 (21-11):

* C2-1 — hai văn bản KHÁC chuỗi cùng chạm ô Y (hai phiên): A (điều chỉnh bỏ tên P ⇒ P về Y, đã đọc số trước 2 / 1 dưới khoá)
  ↔ B trả 1 chỗ ở Y — năm đường: dòng chụp Y TẮT (huỷ hiệu lực, huỷ ghi nhận, điều chỉnh bỏ tên) hoặc em đang được đếm ở Y
  (Phần A) được THÊM dòng chụp ô khác (ghi nhận, khôi phục bằng huỷ ghi nhận văn bản huỷ). B phải khoá Y (ô MẤT chỗ) ⇒ CHỜ A
  ⇒ A cảnh báo "2 → 3" (đã lưu trong sự kiện), Y cuối 2. Mã cũ: B không khoá Y ⇒ trả chỗ giữa chừng ⇒ A so 2 với 2, mất cảnh báo.
* C2-2 — MỘT văn bản vừa bỏ P (về Y) vừa thêm Q vào Y (ô hai vai): MỘT cảnh báo đủ ``o_hien_tai`` / ``da_dung_truoc`` / câu
  owner "1 → 3" (khuôn "30 → 32").
* P2 — tạo học vụ Y (ngành mới, có chỉ tiêu) chen GIỮA lúc văn bản dò ô và lúc ghi (hai phiên): lệnh tạo phải CHỜ văn bản
  (khoá năm chia sẻ ↔ độc quyền) ⇒ văn bản ghi khi Y chưa có ⇒ không cảnh báo (nhất quán). Mã cũ: Y commit trước khi văn bản
  ghi mà vắng khỏi tập khoá + cảnh báo ⇒ văn bản làm Y 1 → 2 / 1 im lặng.
"""
import asyncio

import pytest

from app.database import AsyncSessionLocal
from app.services import quota_occupancy_service as qos
from tests.api import test_council_decisions_api as qd
from tests.api.test_tao_hoc_vu_api import _tao_loai_hinh
from tests.api.test_council_decision_hai_phien_api import (
    _ban,
    _boc,
    _cho_bi_chan_hoac_xong,
    _dam_bao_sts09,
    _Diem,
    _nop,
)
from tests.api.test_council_decision_khoa_cheo_api import (
    _chuyen_sang_duoc_cd,
    _duyet_hang_loat,
    _gan_nganh,
)
from tests.api.test_council_decision_khoa_goc_chuoi_api import PhienBa, chan_cua, cho_bi_chan_boi
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    A,
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

TEN_NGANH_Y = "Dược"  # ``major_program.name`` của ngành duoc_cd trong seed Hội đồng


async def _o_y(hs):  # noqa: F811
    """Ô Y = học vụ Dược CĐ chính quy (+ ngành, đường xét của nó)."""
    py, _ = hs["_danh_muc"]["psg"][("duoc_cd", "cq", "g1")]
    ai = await qd._q1("SELECT academic_info_id FROM admission_path WHERE id = :p", p=py)
    off = await qd._q1("SELECT offering_id FROM offering_academic_info WHERE id = :a", a=ai)
    return {"ai": ai, "off": off, "path": py}


async def _dem_nganh(o):
    """Số chính của ô ngành (mức lớn nhất trong hai cách đếm — K-4) + hai số, đọc ở phiên khác."""
    async with AsyncSessionLocal() as db:
        cong_bo = await qos.count_by_academic_info(db, academic_info_id=o["ai"])
        phe_duyet_cu = await qos.count_by_offering_year(db, offering_id=o["off"], academic_year=2026)
    return max(cong_bo, phe_duyet_cu), cong_bo, phe_duyet_cu


async def _dat_o_y(hs, chi_tieu, *em):  # noqa: F811
    """Lead của các em ``em`` trỏ ngành của ô Y; đặt chỉ tiêu năm của Y."""
    y = await _o_y(hs)
    for nhan in em:
        await _gan_nganh(hs[nhan][1], y["off"])
    await qd._sql("UPDATE offering_academic_info SET annual_admission_quota = :n WHERE id = :a", n=chi_tieu, a=y["ai"])
    return y


def _canh_bao_y(y, chi_tieu, truoc, sau, cong_bo, phe_duyet_cu):
    """Bản cảnh báo mong đợi của ô Y (DTO máy chủ điền None cho khoá không thuộc loại ô)."""
    return {
        "loai": "nganh",
        "chi_tieu": chi_tieu,
        "academic_info_id": y["ai"],
        "da_dung_cong_bo": cong_bo,
        "da_dung_phe_duyet_cu": phe_duyet_cu,
        "admission_path_id": None,
        "da_dung": None,
        "nhan": TEN_NGANH_Y,
        "o_hien_tai": True,
        "da_dung_truoc": truoc,
        "cau": "Ngành %s, đường xét hiện tại: %d → %d chỗ đã dùng, chỉ tiêu %d, vượt %d."
        % (TEN_NGANH_Y, truoc, sau, chi_tieu, sau - chi_tieu),
    }


def _bo_none(ds):
    return [{k: v for k, v in c.items() if v is not None} for c in ds]


async def _canh_bao_da_luu(decision_id, loai_su_kien):
    return await qd._q1(
        "SELECT so_lieu -> 'canh_bao_vuot_chi_tieu' FROM council_document_event WHERE decision_id = :d AND loai = :l",
        d=decision_id,
        l=loai_su_kien,
    )


# ═══════════════════════════════ bốn đường đưa em về ô hiện tại ═══════════════════════════════
#: đường → (mã HTTP, loại sự kiện ghi cảnh báo, trạng thái mong đợi của văn bản đích sau thao tác)
DUONG = {
    "dieu_chinh_bo_ten": (201, "ghi_nhan_dieu_chinh"),
    "huy_hieu_luc": (201, "huy_hieu_luc"),
    "huy_ghi_nhan": (200, "huy_ghi_nhan"),
    "huy_ghi_nhan_dieu_chinh_co_dong_them": (200, "huy_ghi_nhan"),
}


async def _chuan_bi(client, ad, hs, duong):  # noqa: F811
    """Dựng chuỗi để thao tác ``duong`` làm em P mất dòng hiệu lực. Trả hàm gửi thao tác."""
    p = hs[SACH[0]][1]
    if duong == "huy_ghi_nhan_dieu_chinh_co_dong_them":
        _, r = await qd._qd_cua_bo(client, ad, hs, [SACH[1]], "501")
        bd = await qd._bo_ok(client, ad, hs, [SACH[0]], duong="/decisions/%d/bo-dieu-chinh" % r["id"])
        rr = await qd._dieu_chinh(client, ad, r["id"], "801", set_id=bd["id"], so_hs=1)  # THÊM P
        assert rr.status_code == 201, rr.text
        d = rr.json()
        return lambda: qd._huy_ghi_nhan(client, ad, d["id"], "801")
    _, r = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    if duong == "dieu_chinh_bo_ten":
        dong = await qd._dong_cua(r["id"], p)
        return lambda: qd._dieu_chinh(client, ad, r["id"], "802", bo_dong=[dong])
    if duong == "huy_hieu_luc":
        return lambda: qd._huy_hieu_luc(client, ad, r["id"], "701")
    return lambda: qd._huy_ghi_nhan(client, ad, r["id"], "501")


# ═══════════════════════════════ C2-a: một văn bản, một người ═════════════════════════════════
@pytest.mark.parametrize("duong", list(DUONG))
async def test_c2_o_hien_tai_day_van_ghi_va_canh_bao_vuot_mot_dung_o(client, hs, ad, duong):  # noqa: F811
    lam = await _chuan_bi(client, ad, hs, duong)
    y = await _dat_o_y(hs, 1, SACH[0], "don_vi_khac")
    assert await _dem_nganh(y) == (1, 0, 1), "tiền điều kiện: ô Y đầy (1 / 1) trước thao tác"
    r = await lam()
    ma, loai_su_kien = DUONG[duong]
    assert r.status_code == ma, r.text  # K-1: không chặn — văn bản đã ký vẫn được ghi
    assert await _dem_nganh(y) == (2, 0, 2), "em về ô Y: 2 / 1"
    cb = r.json()["canh_bao_vuot_chi_tieu"]
    assert cb == [_canh_bao_y(y, 1, 1, 2, 0, 2)], r.text
    assert await _canh_bao_da_luu(r.json()["id"], loai_su_kien) == _bo_none(cb)  # lưu cùng giao dịch


@pytest.mark.parametrize("duong", list(DUONG))
async def test_c2_o_hien_tai_thieu_mot_thanh_vua_du_khong_canh_bao(client, hs, ad, duong):  # noqa: F811
    lam = await _chuan_bi(client, ad, hs, duong)
    y = await _dat_o_y(hs, 2, SACH[0], "don_vi_khac")
    assert await _dem_nganh(y) == (1, 0, 1), "tiền điều kiện: ô Y 1 / 2 trước thao tác"
    r = await lam()
    assert r.status_code == DUONG[duong][0], r.text
    assert await _dem_nganh(y) == (2, 0, 2), "em về ô Y: 2 / 2 — vừa đủ"
    assert r.json()["canh_bao_vuot_chi_tieu"] == [], r.text


# ═══════════════════════════════ C2 — ô ĐƯỜNG XÉT hiện tại của em kiểu cũ ═══════════════════════
@pytest.mark.parametrize("chi_tieu", [1, 2], ids=["day_vuot_mot", "thieu_mot_vua_du"])
async def test_c2_o_duong_xet_hien_tai_em_kieu_cu_canh_bao(client, hs, ad, chi_tieu):  # noqa: F811
    # Chiều "công bố" của Phần A: em kiểu cũ (``uses_choice_engine`` = FALSE) đếm theo ``applied_rules->>'admission_path_id'``
    # ở ô đường xét Z. Ô Z có sẵn 1 em kiểu cũ ⇒ bỏ tên P ⇒ Z = 2. Chỉ tiêu 1 (đầy) ⇒ vẫn ghi + câu owner của ô đường xét (tên
    # đường xét TRƯỚC, ngành sau, số của CHÍNH ô Z); chỉ tiêu 2 (thiếu một) ⇒ vừa đủ, không báo. (Ô ngành của P theo lead KHÔNG
    # có — lead không trỏ ngành ⇒ chỉ chiều này đưa P về Z; học vụ của Z không đặt chỉ tiêu.)
    _, r = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    z = (await _o_y(hs))["path"]
    for nhan in (SACH[0], "don_vi_khac"):
        await qd._sql(
            "UPDATE admission_profile SET uses_choice_engine = FALSE, applied_rules = "
            "jsonb_build_object('admission_path_id', CAST(:z AS integer)) WHERE id = :p",
            z=z,
            p=hs[nhan][1],
        )
    await qd._sql(
        "UPDATE admission_path SET admit_quota = :n, display_name = 'Giả Z' WHERE id = :z", n=chi_tieu, z=z
    )
    async with AsyncSessionLocal() as db:
        assert await qos.count_by_path(db, admission_path_id=z) == 1, "tiền điều kiện: ô Z có 1 chỗ"
    dong = await qd._dong_cua(r["id"], hs[SACH[0]][1])
    rr = await qd._dieu_chinh(client, ad, r["id"], "801", bo_dong=[dong])
    assert rr.status_code == 201, rr.text  # K-1: vẫn ghi văn bản đã ký
    async with AsyncSessionLocal() as db:
        assert await qos.count_by_path(db, admission_path_id=z) == 2
    if chi_tieu == 2:
        assert rr.json()["canh_bao_vuot_chi_tieu"] == [], rr.text
        return
    assert rr.json()["canh_bao_vuot_chi_tieu"] == [
        {
            "loai": "duong_xet",
            "chi_tieu": 1,
            "academic_info_id": None,
            "da_dung_cong_bo": None,
            "da_dung_phe_duyet_cu": None,
            "admission_path_id": z,
            "da_dung": 2,
            "nhan": "Giả Z",
            "o_hien_tai": True,
            "da_dung_truoc": 1,
            "cau": "Đường xét Giả Z (ngành %s): 1 → 2 chỗ đã dùng, chỉ tiêu 1, vượt 1." % TEN_NGANH_Y,
        }
    ], rr.text
    assert await _canh_bao_da_luu(rr.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(rr.json()["canh_bao_vuot_chi_tieu"])


# ═══════════════════════════════ C2-b: hai phiên — khoá đúng ô hiện tại ═════════════════════════
@pytest.mark.parametrize("duong", ["dieu_chinh_bo_ten", "huy_hieu_luc", "huy_ghi_nhan"])
async def test_c2_hai_phien_phe_duyet_cu_cho_o_hien_tai_roi_bi_chan(client, hs, ad, duong):  # noqa: F811
    # Ô Y chỉ tiêu 1, đang 0 / 1. Phiên CSDL thứ ba khoá DÒNG Quyết định của P ⇒ thao tác (đã khoá hồ sơ P rồi ô Y — thứ tự
    # chuẩn) dừng ở câu ghi dòng (UPDATE ``bi_bo_boi_id`` / lan trạng thái xuống dòng). Phê duyệt cũ em P2 (lead → Y): khoá
    # hồ sơ P2 → ô Y ⇒ CHỜ đúng phiên thao tác. Thả ⇒ thao tác commit (Y = 1 / 1, không cảnh báo); Phê duyệt đếm DƯỚI khoá
    # thấy P đã về Y ⇒ "Vượt chỉ tiêu". Mã cũ: thao tác không khoá Y ⇒ Phê duyệt đếm 0 (P còn dòng) ⇒ duyệt ⇒ Y = 2 / 1.
    await _dam_bao_sts09()  # nhánh "được duyệt" (mã cũ) đi tới 200 thật, không dừng 404 ở đồng bộ lead
    lam = await _chuan_bi(client, ad, hs, duong)
    p2 = hs[SACH[1]][1]
    await _nop(p2)
    y = await _dat_o_y(hs, 1, SACH[0], SACH[1])
    assert await _dem_nganh(y) == (0, 0, 0), "tiền điều kiện: ô Y 0 / 1"
    dong_p = await qd._q1(
        "SELECT id FROM council_decision_row WHERE profile_id = :p AND trang_thai_cha = 'hieu_luc' "
        "AND bi_bo_boi_id IS NULL",
        p=hs[SACH[0]][1],
    )
    ver = (await _ban(p2))[1]
    async with PhienBa() as ba:
        await ba.khoa("council_decision_row", [dong_p])
        t_1 = asyncio.create_task(lam())
        pid_1 = await cho_bi_chan_boi(ba.pid, t_1)
        assert pid_1 is not None, "phép đo không hợp lệ: thao tác không tới câu ghi dòng"
        t_2 = asyncio.create_task(client.post(A + "/%d/approve" % p2, json={"version": ver}, headers=ad))
        pid_2 = await cho_bi_chan_boi(pid_1, t_2)
        chan_2 = await chan_cua(pid_2)
        await ba.tha()
        r_1, r_2 = await asyncio.gather(t_1, t_2)
    assert r_1.status_code in (200, 201), r_1.text
    assert r_1.json()["canh_bao_vuot_chi_tieu"] == [], r_1.text  # 0 → 1 / 1: vừa đủ
    assert r_2.status_code == 400 and "Vượt chỉ tiêu" in str(r_2.json()), r_2.text
    assert (await _ban(p2))[0] == "submitted"
    assert (await _dem_nganh(y))[0] == 1, "ô Y không vượt"
    assert chan_2 == [pid_1], "phép đo: Phê duyệt cũ phải chờ ĐÚNG phiên thao tác ở ô Y — %r" % (chan_2,)


# ═══════════════════════════════ C2 — MỘT lần khoá ô (thứ tự chuẩn F259) ═══════════════════════
async def test_c2_dieu_chinh_them_o_cao_bo_o_thap_va_duyet_hang_loat_khong_vong_cho(  # noqa: F811
    client, hs, ad, monkeypatch
):
    # Điều chỉnh D: THÊM em Q ở ô chụp CAO (Dược) + BỎ em P mà ô hiện tại là ô THẤP X (lead P → Ô tô). Phê duyệt hàng loạt
    # (A1 ở X, A2 ở Dược) khoá TRƯỚC [X, Dược] theo id tăng dần. D khoá hợp hai ô bằng MỘT câu ⇒ cũng [X, Dược] ⇒ lô chờ D,
    # không vòng. Biến thể khoá hai lần (ô chụp CAO rồi ô hiện tại THẤP) ⇒ D giữ CAO chờ THẤP, lô giữ THẤP chờ CAO ⇒ 40P01.
    # Điểm đồng bộ: lần gọi ĐẦU ``lock_quota_cells`` (của D) xong thì D DỪNG, giữ khoá đã lấy.
    # Codex PR-1 lượt 2 (owner 22-11): nguyện vọng in của P cũng ở ô CAO ⇒ ô MẤT chỗ của P (ô chụp dòng bị bỏ — C2-1) = CAO ≠
    # ô hiện tại X. Nếu ô mất chỗ trùng X (dữ liệu cũ), lần khoá đầu của biến thể hai lần đã lấy X ⇒ ca xanh cả khi khoá hai lần.
    await _dam_bao_sts09()
    x = await qd._q(
        "SELECT ap.academic_info_id, oai.offering_id FROM admission_profile_choice c "
        "JOIN admission_path ap ON ap.id = c.admission_path_id "
        "JOIN offering_academic_info oai ON oai.id = ap.academic_info_id "
        "WHERE c.admission_profile_id = :p ORDER BY c.display_order, c.id LIMIT 1",
        p=hs["don_vi_khac"][1],
    )
    x_ai, x_off = x[0]
    _, cao_ai = await _chuyen_sang_duoc_cd(hs, "loai_hinh_lien_thong")
    _, cao_p = await _chuyen_sang_duoc_cd(hs, SACH[0])
    assert cao_p == cao_ai, "phép đo không hợp lệ: nguyện vọng in của P và Q phải cùng ô cao"
    assert x_ai < cao_ai, "phép đo không hợp lệ: ô hiện tại của P phải có id học vụ THẤP hơn ô chụp của Q"
    cao_off = await qd._q1("SELECT offering_id FROM offering_academic_info WHERE id = :a", a=cao_ai)
    await qd._sql(
        "UPDATE offering_academic_info SET annual_admission_quota = 10 WHERE id = ANY(CAST(:a AS integer[]))",
        a=[x_ai, cao_ai],
    )
    bo_p, r = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    assert await qd._q1(
        "SELECT academic_info_id FROM council_document_set_row WHERE set_id = :s", s=bo_p["id"]
    ) == cao_ai, "phép đo không hợp lệ: ô mất chỗ của P (ô chụp dòng bị bỏ) phải là ô CAO, KHÁC ô hiện tại X"
    await _gan_nganh(hs[SACH[0]][1], x_off)  # ô hiện tại của P = X (thấp)
    bd = await qd._bo_ok(client, ad, hs, ["loai_hinh_lien_thong"], duong="/decisions/%d/bo-dieu-chinh" % r["id"])
    assert await qd._q1(
        "SELECT academic_info_id FROM council_document_set_row WHERE set_id = :s", s=bd["id"]
    ) == cao_ai, "phép đo không hợp lệ: dòng THÊM phải chụp ô cao"
    a1, a2 = hs[SACH[1]][1], hs[SACH[2]][1]
    for p, off in ((a1, x_off), (a2, cao_off)):
        await _nop(p)
        await _gan_nganh(p, off)
    v1, v2 = (await _ban(a1))[1], (await _ban(a2))[1]
    dong = await qd._dong_cua(r["id"], hs[SACH[0]][1])
    diem = _Diem()
    _boc(monkeypatch, qos, "lock_quota_cells", diem)
    t_dc = asyncio.create_task(qd._dieu_chinh(client, ad, r["id"], "801", bo_dong=[dong], set_id=bd["id"], so_hs=1))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_lo = asyncio.create_task(_duyet_hang_loat(client, ad, (a1, v1), (a2, v2)))
    do = await _cho_bi_chan_hoac_xong(t_lo)
    diem.di.set()
    r_dc, r_lo = await asyncio.gather(t_dc, t_lo)
    assert qos.CONFLICT_MESSAGE not in r_dc.text and qos.CONFLICT_MESSAGE not in r_lo.text, (r_dc.text, r_lo.text)
    assert r_dc.status_code == 201, r_dc.text
    assert r_lo.status_code == 200 and (r_lo.json()["success_count"], r_lo.json()["failed_ids"]) == (2, []), r_lo.text
    assert do == "chan", "phép đo không hợp lệ: lô không chờ khoá ô của điều chỉnh"


# ═══════════════════════════════ Codex PR-1 lượt 2 — dữ liệu chung ═══════════════════════════════
#: Em thứ hai của các ca dưới: loại hình liên thông — nguyện vọng in ở ô W (Ô tô CĐ liên thông) ≠ X (ô chụp của P) ≠ Y.
Q = "loai_hinh_lien_thong"


async def _bo_nganh_lead(pid):
    """Lead không trỏ ngành ⇒ em không được đếm ở ô ngành Phần A nào (chỉ còn chiều nguyện vọng — không ``admitted``)."""
    await qd._sql(
        "UPDATE lead SET offering_id = NULL WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)", p=pid
    )


async def _dong_hieu_luc(pid):
    return await qd._q1(
        "SELECT id FROM council_decision_row WHERE profile_id = :p AND trang_thai_cha = 'hieu_luc' "
        "AND bi_bo_boi_id IS NULL",
        p=pid,
    )


# ═══════════════════════════════ C2-1: hai văn bản khác chuỗi cùng chạm ô Y ═══════════════════════
#: đường B trả 1 chỗ ở Y → (mã HTTP mong đợi, loại sự kiện ghi cảnh báo của B)
DUONG_TRA_CHO = {
    "huy_hieu_luc": (201, "huy_hieu_luc"),
    "huy_ghi_nhan": (200, "huy_ghi_nhan"),
    "dieu_chinh_bo_ten": (201, "ghi_nhan_dieu_chinh"),
    "ghi_nhan": (201, "ghi_nhan"),
    "khoi_phuc": (200, "huy_ghi_nhan"),
}


async def _chuan_bi_tra_cho(client, ad, hs, duong):  # noqa: F811
    """Chuỗi THỨ HAI (khác chuỗi của P) sao cho thao tác B trả đúng 1 chỗ ở Y. Trả (hàm gửi B, id văn bản B ghi sự kiện —
    None khi phải đọc từ phản hồi)."""
    q = hs[Q][1]
    if duong in ("huy_hieu_luc", "huy_ghi_nhan", "dieu_chinh_bo_ten"):
        # Q giữ chỗ ở Y bằng dòng CHỤP Y (Phần B); lead Q không trỏ ngành ⇒ dòng tắt thì Q không về Y.
        await _chuyen_sang_duoc_cd(hs, Q)
        _, r2 = await qd._qd_cua_bo(client, ad, hs, [Q], "502")
        await _bo_nganh_lead(q)
        if duong == "huy_hieu_luc":
            return lambda: qd._huy_hieu_luc(client, ad, r2["id"], "702"), None
        if duong == "huy_ghi_nhan":
            return lambda: qd._huy_ghi_nhan(client, ad, r2["id"], "502"), r2["id"]
        dong_q = await qd._dong_cua(r2["id"], q)
        return lambda: qd._dieu_chinh(client, ad, r2["id"], "802", bo_dong=[dong_q]), None
    # Q (Đã duyệt) được đếm ở Y bằng Phần A (lead → ngành Y); B đưa Q sang Phần B ở ô chụp W ⇒ Y mất 1 chỗ.
    y = await _o_y(hs)
    if duong == "ghi_nhan":
        bo2 = await qd._bo_ok(client, ad, hs, [Q])
        await _gan_nganh(q, y["off"])
        return lambda: qd._ghi(client, ad, bo2["id"], so="502", so_hs=1), None
    _, r2 = await qd._qd_cua_bo(client, ad, hs, [Q], "502")
    rh = await qd._huy_hieu_luc(client, ad, r2["id"], "702")
    assert rh.status_code == 201, rh.text
    await _gan_nganh(q, y["off"])
    return lambda: qd._huy_ghi_nhan(client, ad, rh.json()["id"], "702"), rh.json()["id"]


@pytest.mark.parametrize("duong", list(DUONG_TRA_CHO))
async def test_c2_1_hai_van_ban_khac_chuoi_tra_cho_va_dua_ve_cung_o_y_khong_mat_canh_bao(  # noqa: F811
    client, hs, ad, duong
):
    # Ô Y chỉ tiêu 1, đang 2 / 1 (em đơn vị khác ở Phần A + chỗ mà B sẽ trả). A = điều chỉnh bỏ tên P (lead P → Y) — phiên
    # ba giữ DÒNG Quyết định của P ⇒ A dừng ở câu ghi, ĐÃ khoá ô (X — ô chụp của P, Y — ô hiện tại) và đã đếm số trước = 2. B
    # (chuỗi khác) trả 1 chỗ ở Y: phải khoá Y (ô MẤT chỗ) ⇒ CHỜ A. Kết cục tuần tự A → B: A cảnh báo "2 → 3", B không cảnh báo,
    # Y cuối 2 / 1. Mã cũ (B không khoá ô mất chỗ): B commit giữa chừng (Y = 1) ⇒ A ghi (Y = 2) rồi so 2 với 2 ⇒ MẤT cảnh báo.
    lam_b, id_su_kien_b = await _chuan_bi_tra_cho(client, ad, hs, duong)
    _, r1 = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    y = await _dat_o_y(hs, 1, SACH[0], "don_vi_khac")
    truoc = await _dem_nganh(y)
    assert truoc[0] == 2, "tiền điều kiện: ô Y 2 / 1 trước hai văn bản — %r" % (truoc,)
    dong_p = await _dong_hieu_luc(hs[SACH[0]][1])
    async with PhienBa() as ba:
        await ba.khoa("council_decision_row", [dong_p])
        t_a = asyncio.create_task(qd._dieu_chinh(client, ad, r1["id"], "801", bo_dong=[dong_p]))
        pid_a = await cho_bi_chan_boi(ba.pid, t_a)
        assert pid_a is not None, "phép đo không hợp lệ: A không tới câu ghi dòng"
        t_b = asyncio.create_task(lam_b())
        pid_b = await cho_bi_chan_boi(pid_a, t_b)
        chan_b = await chan_cua(pid_b)
        await ba.tha()
        r_a, r_b = await asyncio.gather(t_a, t_b)
    assert r_a.status_code == 201, r_a.text
    ma_b, loai_su_kien_b = DUONG_TRA_CHO[duong]
    assert r_b.status_code == ma_b, r_b.text
    cb_a = r_a.json()["canh_bao_vuot_chi_tieu"]
    assert cb_a == [_canh_bao_y(y, 1, 2, 3, truoc[1], truoc[2] + 1)], (
        "A làm Y tăng 2 → 3 / 1 phải cảnh báo (B trả chỗ TRƯỚC hoặc SAU cả lần so của A, không giữa chừng): %r" % cb_a
    )
    assert await _canh_bao_da_luu(r_a.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb_a)
    assert r_b.json()["canh_bao_vuot_chi_tieu"] == [], r_b.text
    assert await _canh_bao_da_luu(id_su_kien_b or r_b.json()["id"], loai_su_kien_b) == []
    assert (await _dem_nganh(y))[0] == 2, "ô Y cuối: 2 / 1"
    assert chan_b == [pid_a], "phép đo: B phải chờ ĐÚNG phiên A ở ô Y — %r" % (chan_b,)


# ═══════════════════════════════ C2-2: một văn bản, ô Y hai vai ═════════════════════════════════
async def test_c2_2_mot_van_ban_vua_bo_ve_y_vua_them_vao_y_mot_canh_bao_du_thong_tin(client, hs, ad):  # noqa: F811
    # Ô Y chỉ tiêu 1, đang 1 / 1 (em đơn vị khác, Phần A). Điều chỉnh của chuỗi P: BỎ P (lead P → Y ⇒ P về Y, ô HIỆN TẠI) và
    # THÊM Q (nguyện vọng in ở Y ⇒ ô CHỤP Y; lead Q không trỏ ngành). Y vừa là ô chụp vừa là ô hiện tại ⇒ MỘT cảnh báo, đủ
    # ``o_hien_tai`` / ``da_dung_truoc`` / câu owner "1 → 3 … vượt 2" (khuôn "30 → 32"). Mã cũ: loại Y khỏi tập ô hiện tại TRƯỚC
    # khi đếm số trước ⇒ cảnh báo chỉ theo luật ô chụp, thiếu số trước + câu.
    _, r1 = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    await _chuyen_sang_duoc_cd(hs, Q)
    await _bo_nganh_lead(hs[Q][1])
    bd = await qd._bo_ok(client, ad, hs, [Q], duong="/decisions/%d/bo-dieu-chinh" % r1["id"])
    y = await _dat_o_y(hs, 1, SACH[0], "don_vi_khac")
    assert await _dem_nganh(y) == (1, 0, 1), "tiền điều kiện: ô Y 1 / 1"
    dong_p = await _dong_hieu_luc(hs[SACH[0]][1])
    r = await qd._dieu_chinh(client, ad, r1["id"], "801", bo_dong=[dong_p], set_id=bd["id"], so_hs=1)
    assert r.status_code == 201, r.text  # K-1: vẫn ghi văn bản đã ký
    assert await _dem_nganh(y) == (3, 1, 3), "Y: 1 → 3 (P về Phần A + Q chiếm chỗ chụp)"
    cb = r.json()["canh_bao_vuot_chi_tieu"]
    assert cb == [_canh_bao_y(y, 1, 1, 3, 1, 3)], r.text
    assert await _canh_bao_da_luu(r.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)


# ═══════════════════════════════ P2: học vụ Y xuất hiện giữa lúc dò và lúc ghi ══════════════════
async def test_p2_tao_hoc_vu_y_giua_luc_do_va_luc_ghi_phai_cho_van_ban(client, hs, ad):  # noqa: F811
    # Ngành MỚI (loại hình mới, CHƯA có học vụ năm 2026); lead của P và em đơn vị khác trỏ ngành ấy ⇒ khi P về Phần A, ô ngành
    # của P là học vụ (ngành mới, 2026) — lúc A dò thì CHƯA có. A = điều chỉnh bỏ tên P, dừng ở câu ghi (phiên ba) sau khi đã dò +
    # khoá ô. C = tạo học vụ (ngành mới, 2026, chỉ tiêu 1) qua route thật. Đúng: C CHỜ A (khoá năm) ⇒ A ghi khi Y chưa có ⇒ không
    # cảnh báo; C tạo Y sau. Mã cũ (không khoá năm): C commit TRƯỚC khi A ghi ⇒ A làm Y 1 → 2 / 1 mà Y vắng khỏi tập khoá + cảnh
    # báo ⇒ im lặng.
    _, r1 = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    off = await _tao_loai_hinh(client, ad)
    for nhan in (SACH[0], "don_vi_khac"):
        await _gan_nganh(hs[nhan][1], off)
    assert await qd._q1(
        "SELECT count(*) FROM offering_academic_info WHERE offering_id = :o AND academic_year = 2026", o=off
    ) == 0, "tiền điều kiện: ngành mới chưa có học vụ 2026"
    dong_p = await _dong_hieu_luc(hs[SACH[0]][1])
    async with PhienBa() as ba:
        await ba.khoa("council_decision_row", [dong_p])
        t_a = asyncio.create_task(qd._dieu_chinh(client, ad, r1["id"], "801", bo_dong=[dong_p]))
        pid_a = await cho_bi_chan_boi(ba.pid, t_a)
        assert pid_a is not None, "phép đo không hợp lệ: A không tới câu ghi dòng"
        t_c = asyncio.create_task(
            client.post(
                "/api/admin/offerings/%d/academic-info" % off,
                json={"offering_id": off, "academic_year": 2026, "annual_admission_quota": 1, "is_published": False},
                headers=ad,
            )
        )
        pid_c = await cho_bi_chan_boi(pid_a, t_c)
        tao_xong_truoc = t_c.done()  # C đã commit khi A còn chưa ghi
        chan_c = await chan_cua(pid_c)
        await ba.tha()
        r_a, r_c = await asyncio.gather(t_a, t_c)
    assert r_a.status_code == 201, r_a.text
    assert r_c.status_code == 201, r_c.text
    y_moi = r_c.json()["id"]
    cb = r_a.json()["canh_bao_vuot_chi_tieu"]
    assert await _canh_bao_da_luu(r_a.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)
    async with AsyncSessionLocal() as db:
        assert await qos.count_by_offering_year(db, offering_id=off, academic_year=2026) == 2  # P + em đơn vị khác
    assert [c.get("academic_info_id") for c in cb] == ([y_moi] if tao_xong_truoc else []), (
        "học vụ Y (chỉ tiêu 1) commit %s khi A ghi; A làm Y 1 → 2 — cảnh báo của A: %r"
        % ("TRƯỚC" if tao_xong_truoc else "SAU", cb)
    )
    assert not tao_xong_truoc and chan_c == [pid_a], (
        "phép đo: lệnh tạo học vụ phải CHỜ đúng phiên A (khoá năm) — xong trước: %s, bị chặn bởi: %r" % (tao_xong_truoc, chan_c)
    )
