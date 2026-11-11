# -*- coding: utf-8 -*-
"""F260 (Codex lần 15) — mỗi hàm đếm chỗ chỉ tiêu tính Phần A + Phần B trong MỘT ảnh chụp.

READ COMMITTED chụp ảnh theo TỪNG CÂU. Nếu Phần A và Phần B là hai câu, một thao tác chuyển hồ sơ A ↔ B commit
CHEN GIỮA hai câu ⇒ cùng một em bị đếm 0 lần (huỷ hiệu lực: B → A) hoặc 2 lần (ghi nhận: A → B). Huỷ hiệu lực
KHÔNG giữ khoá dòng chỉ tiêu nên khoá của bên duyệt không ngăn lịch ấy ⇒ Phê duyệt cũ duyệt vượt 2 / 1.

Điểm đồng bộ (chính xác ở ranh giới A | B): bọc bốn hàm đếm + ``AsyncSession.execute`` — ngay SAU câu SQL ĐẦU
TIÊN của hàm đếm có Phần A (dấu hiệu ``NOT (EXISTS`` của điều kiện "không có dòng hiệu lực"), PHIÊN KHÁC chạy
thao tác chuyển A ↔ B THẬT (service, commit) rồi hàm đếm mới đi tiếp. Mã một câu: thao tác chen SAU câu duy nhất ⇒
không ảnh hưởng; mã hai câu: câu B thấy trạng thái mới ⇒ 0 hoặc 2.

* ``test_moi_ham_dem_mot_anh_chup[<hàm>-<chiều>]`` — bốn hàm × hai chiều, kỳ vọng ĐÚNG 1;
* ``test_phe_duyet_cu_khong_duyet_vuot_khi_huy_hieu_luc_chen_giua`` — đối chứng qua REQUEST THẬT (Phê duyệt cũ).
"""
import contextvars

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.services import council_decision_service as qd_vb
from app.services import quota_occupancy_service as qos
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_hai_phien_api import (  # noqa: F401 — fixture
    _ban,
    _dam_bao_sts09,
    _nop,
    _o_chi_tieu,
)
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    A,
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

HAM_DEM = (
    "dem_theo_nganh_nam",
    "dem_theo_thong_tin_hoc_vu",
    "dem_theo_duong_xet",
    "dem_da_trung_tuyen_theo_duong_xet",
)
_DANG_DEM = contextvars.ContextVar("f260_dang_dem", default=False)
#: Câu có Phần A — điều kiện "hồ sơ KHÔNG có dòng hiệu lực" (``khong_co_dong_hieu_luc``) biên dịch thành
#: ``NOT (EXISTS (SELECT …))``; câu Phần B và câu cảnh báo thiếu khoá không có.
DAU_PHAN_A = "NOT (EXISTS"


def _chen_sau_phan_a(monkeypatch, chen):
    """Sau câu SQL ĐẦU TIÊN có Phần A mà một hàm đếm chạy, chạy ``chen()`` (phiên khác, commit) MỘT lần."""
    trang = {"da_chen": False, "cau": []}
    goc_exec = AsyncSession.execute

    async def exec_boc(self, cau, *a, **kw):
        kq = await goc_exec(self, cau, *a, **kw)
        if _DANG_DEM.get() and not trang["da_chen"]:
            try:
                sql = str(cau.compile(dialect=postgresql.dialect()))
            except Exception:  # noqa: BLE001 — câu chữ thô
                sql = str(cau)
            trang["cau"].append(DAU_PHAN_A in sql)
            if DAU_PHAN_A in sql:
                trang["da_chen"] = True
                tok = _DANG_DEM.set(False)
                try:
                    await chen()
                finally:
                    _DANG_DEM.reset(tok)
        return kq

    monkeypatch.setattr(AsyncSession, "execute", exec_boc)
    for ten in HAM_DEM:
        goc = getattr(qos, ten)

        async def boc(*a, _goc=goc, **kw):
            tok = _DANG_DEM.set(True)
            try:
                return await _goc(*a, **kw)
            finally:
                _DANG_DEM.reset(tok)

        monkeypatch.setattr(qos, ten, boc)
    return trang


async def _em_chiem_cho_ca_bon_noi(hs):
    """Em P1 (``SACH[0]``, "Đã duyệt") chiếm ĐÚNG một chỗ ở ô K qua Phần A của CẢ bốn nơi đếm: lead → ngành của
    ô K (Phê duyệt cũ), nguyện vọng in "trúng" trên đường xét K (công bố hai mức + ma trận). Trả (P1, ô K)."""
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=5)
    p1 = hs[SACH[0]][1]
    await qd._sql(
        "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
        o=o["off"],
        p=p1,
    )
    await qd._sql(
        "UPDATE admission_profile_choice SET decision = 'admitted' WHERE admission_profile_id = :p "
        "AND admission_path_id = :a",
        p=p1,
        a=o["path"],
    )
    return p1, o


async def _dem_bon_noi(db, ten, o):
    if ten == "dem_theo_nganh_nam":
        return await qos.dem_theo_nganh_nam(db, offering_id=o["off"], academic_year=2026)
    if ten == "dem_theo_thong_tin_hoc_vu":
        return await qos.dem_theo_thong_tin_hoc_vu(db, academic_info_id=o["ai"])
    if ten == "dem_theo_duong_xet":
        return await qos.dem_theo_duong_xet(db, admission_path_id=o["path"])
    return (await qos.dem_da_trung_tuyen_theo_duong_xet(db, [o["path"]]))[o["path"]]


async def _huy_hieu_luc_phien_khac(qd_id, nguoi):
    async with AsyncSessionLocal() as db2:
        h, _ = await qd_vb.huy_hieu_luc(
            db2, qd_id, so_quyet_dinh="701", ngay_ky=qd._ngay(), scan=qd.PDF, nguoi_id=nguoi
        )
        await db2.commit()
        return h.id


async def _ghi_nhan_phien_khac(set_id, nguoi):
    # Vòng giao diện (lượt gửi — đặc tả bản 2 mục 3.7): xin mã lượt ở phiên RIÊNG và commit trước (như route mở lượt),
    # rồi mới ghi nhận bằng mã ấy.
    from app.services import council_decision_submission_service as luot_gui

    async with AsyncSessionLocal() as db1:
        ma = str((await luot_gui.mo_luot(db1, set_id=set_id, nguoi_id=nguoi)).ma)
        await db1.commit()
    async with AsyncSessionLocal() as db2:
        x, _, _ = await qd_vb.ghi_nhan_quyet_dinh(
            db2,
            set_id=set_id,
            loai="trung_tuyen",
            goc_id=None,
            so_quyet_dinh="501",
            ngay_ky=qd._ngay(),
            tham_so_giay={},
            xac_nhan_so_ho_so=1,
            xac_nhan_khop_ban_in=True,
            xac_nhan_trang_thai=None,
            ghi_chu_mau=None,
            scan=qd.PDF,
            nguoi_id=nguoi,
            ma_luot_gui=ma,
        )
        await db2.commit()
        return x.id


async def _dong_hieu_luc(pid):
    return await qd._q1(
        "SELECT count(*) FROM council_decision_row WHERE profile_id = :p AND trang_thai_cha = 'hieu_luc' "
        "AND bi_bo_boi_id IS NULL",
        p=pid,
    )


@pytest.mark.parametrize("chieu", ["huy_hieu_luc_B_sang_A", "ghi_nhan_A_sang_B"])
@pytest.mark.parametrize("ten", HAM_DEM)
async def test_moi_ham_dem_mot_anh_chup(client, hs, ad, monkeypatch, ten, chieu):  # noqa: F811
    p1, o = await _em_chiem_cho_ca_bon_noi(hs)
    nguoi = hs["_danh_muc"]["nguoi"]
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    if chieu.startswith("huy_hieu_luc"):
        x = await qd._ghi_ok(client, ad, bo["id"], so="501", so_hs=1)

        async def chen():
            await _huy_hieu_luc_phien_khac(x["id"], nguoi)

        truoc_sau = (1, 0)  # dòng hiệu lực của P1: trước / sau thao tác chen
    else:

        async def chen():
            await _ghi_nhan_phien_khac(bo["id"], nguoi)

        truoc_sau = (0, 1)
    async with AsyncSessionLocal() as db:
        # Đối chứng KHÔNG chen: đúng 1 ở trạng thái trước.
        assert await _dem_bon_noi(db, ten, o) == 1
        assert await _dong_hieu_luc(p1) == truoc_sau[0]
        trang = _chen_sau_phan_a(monkeypatch, chen)
        n = await _dem_bon_noi(db, ten, o)
    monkeypatch.undo()
    assert trang["da_chen"], "phép đo không hợp lệ: không có câu Phần A nào để chen sau (%s)" % trang
    assert await _dong_hieu_luc(p1) == truoc_sau[1], "phép đo không hợp lệ: thao tác chen không đổi A↔B"
    async with AsyncSessionLocal() as db:
        assert await _dem_bon_noi(db, ten, o) == 1  # đối chứng sau: đúng 1 ở trạng thái mới
    assert n == 1, "em P1 bị đếm %d lần khi %s commit giữa Phần A và Phần B (%s)" % (n, chieu, ten)


async def test_phe_duyet_cu_khong_duyet_vuot_khi_huy_hieu_luc_chen_giua(  # noqa: F811
    client, hs, ad, monkeypatch
):
    """Chỉ tiêu 1. P1 chiếm chỗ qua Quyết định X (Phần B). Phê duyệt cũ em P2 (cùng ô): đếm Phần A (P1 đang ở B ⇒
    0) — phiên khác huỷ hiệu lực X rồi commit (P1 về Phần A) — đếm Phần B (0) ⇒ mã hai câu cho 0 / 1 ⇒ duyệt P2
    ⇒ 2 / 1. Mã một câu ⇒ 1 / 1 ⇒ 400 "Vượt chỉ tiêu", P2 giữ "Đã nộp"."""
    await _dam_bao_sts09()
    p1, o = await _em_chiem_cho_ca_bon_noi(hs)
    await qd._sql(
        "UPDATE offering_academic_info SET annual_admission_quota = 1 WHERE id = :a", a=o["ai"]
    )
    nguoi = hs["_danh_muc"]["nguoi"]
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    x = await qd._ghi_ok(client, ad, bo["id"], so="501", so_hs=1)
    p2 = hs[SACH[2]][1]
    await _nop(p2)
    await qd._sql(
        "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
        o=o["off"],
        p=p2,
    )
    async with AsyncSessionLocal() as db:
        assert await _dem_bon_noi(db, "dem_theo_nganh_nam", o) == 1

    async def chen():
        await _huy_hieu_luc_phien_khac(x["id"], nguoi)

    trang = _chen_sau_phan_a(monkeypatch, chen)
    ver = (await _ban(p2))[1]
    r = await client.post(A + "/%d/approve" % p2, json={"version": ver}, headers=ad)
    monkeypatch.undo()
    assert trang["da_chen"], "phép đo không hợp lệ: Phê duyệt cũ không chạy câu Phần A nào"
    assert await _dong_hieu_luc(p1) == 0, "phép đo không hợp lệ: huỷ hiệu lực không commit"
    async with AsyncSessionLocal() as db:
        da_dung = await _dem_bon_noi(db, "dem_theo_nganh_nam", o)
    assert r.status_code == 400 and "Vượt chỉ tiêu" in str(r.json()), (r.status_code, r.text, da_dung)
    assert (await _ban(p2))[0] == "submitted" and da_dung == 1, ((await _ban(p2))[0], da_dung)
