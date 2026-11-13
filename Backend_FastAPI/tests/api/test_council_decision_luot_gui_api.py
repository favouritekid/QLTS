# -*- coding: utf-8 -*-
"""Lượt gửi ghi nhận Quyết định (vòng giao diện GĐ1 — đặc tả bản 2 mục 3.7; bản 3 mục 3.7.2, 3.7.6). Qua REQUEST THẬT.

Bất biến được canh (mỗi ca một điều):

* mở lượt: lần hai ⇒ 409 ``luot_dang_cho`` kèm mã cũ; lượt cũ vừa kết thúc giữa câu chèn và câu đọc ⇒ thử lại mở được;
* gửi thành công ⇒ lượt ``da_ghi`` cùng giao dịch (decision_id, sha, ket_thuc_luc); gửi LẶP đúng nội dung ⇒ 200, văn bản
  cũ, KHÔNG ghi lần hai; nội dung khác ⇒ 409; bị từ chối nghiệp vụ ⇒ lượt vẫn ``cho_gui``, gửi lại cùng mã được;
  gửi đôi SONG SONG cùng mã ⇒ đúng 1 văn bản;
* phân xử: chưa gửi ⇒ ``chua_ghi_da_chan`` (lặp luỹ đẳng) và gửi muộn ⇒ 409; đã ghi ⇒ ``da_ghi`` + văn bản; mã không có
  ⇒ 404 (không suy "chưa ghi"); lúc ghi nhận ĐANG GIỮ lượt: ghi nhận commit ⇒ ``da_ghi``, ghi nhận lỗi ⇒ chặn được;
  giữ quá trần ⇒ ``dang_xu_ly`` và lượt KHÔNG đổi;
* xoá bộ: còn lượt ``cho_gui`` ⇒ 409, CSDL chặn cuối (CHECK) nếu service bị bỏ qua; lượt đã kết thúc ⇒ xoá được, lượt
  còn với ``set_id`` NULL; lịch BA phiên F272 (phân xử ↔ ghi nhận giữ khoá dòng đã kết thúc ↔ xoá) KHÔNG bế tắc.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.database as csdl
from app.config import settings as app_settings
from app.repositories.council_decision_repository import ma_loi_csdl
from app.services import council_decision_submission_service as luot_gui
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_hai_phien_api import _cho_bi_chan_hoac_xong, _Diem  # noqa: F401
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

P = qd.P


async def _mo(client, ad, set_id):  # noqa: F811
    return await client.post(P + "/sets/%d/luot-ghi-nhan" % set_id, headers=ad)


async def _gui(client, ad, set_id, ma, so_hs=1, them=None):  # noqa: F811
    t = {"ma_luot_gui": ma}
    t.update(them or {})
    return await qd._ghi(client, ad, set_id, so="501", so_hs=so_hs, them=t)


async def _phan_xu(client, ad, ma):  # noqa: F811
    return await client.post(P + "/luot-ghi-nhan/%s/chan" % ma, headers=ad)


async def _luot(ma):
    r = await qd._q(
        "SELECT trang_thai, decision_id, noi_dung_sha, ket_thuc_luc, set_id, set_id_luc_tao "
        "FROM council_decision_submission WHERE ma = CAST(:m AS uuid)",
        m=ma,
    )
    return None if not r else dict(zip(("tt", "qd", "sha", "kt", "set", "set_luc_tao"), r[0]))


async def _so_qd():
    return await qd._q1("SELECT count(*) FROM council_decision")


async def _bo_va_ma(client, ad, hs):  # noqa: F811
    bo = await qd._bo_ok(client, ad, hs, SACH[:1])
    r = await _mo(client, ad, bo["id"])
    assert r.status_code == 201, r.text
    return bo, r.json()["ma"]


# ── mở lượt ──────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_mo_luot_lan_hai_tra_ma_cu(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    assert (await _luot(ma))["tt"] == "cho_gui"
    r = await _mo(client, ad, bo["id"])
    assert r.status_code == 409, r.text
    assert (r.json()["ma_loi"], r.json()["ma"]) == ("luot_dang_cho", ma)


async def test_mo_luot_khi_luot_cu_vua_ket_thuc_thi_thu_lai(client, hs, ad, monkeypatch):  # noqa: F811
    # Bản 3 mục 3.7.2: lần chèn đụng UNIQUE (lượt cũ còn cho_gui) nhưng lượt cũ KẾT THÚC trước câu đọc ⇒ không còn mã
    # để trả ⇒ thử lại ⇒ mở được lượt mới.
    bo, ma_cu = await _bo_va_ma(client, ad, hs)
    goc = luot_gui._luot_cho_gui_cua_bo
    da_chen = []

    async def boc(db, set_id):
        if not da_chen:
            da_chen.append(1)
            await qd._sql(  # phiên khác: lượt cũ kết thúc (commit) giữa câu chèn hỏng và câu đọc
                "UPDATE council_decision_submission SET trang_thai = 'da_chan', ket_thuc_luc = now() "
                "WHERE ma = CAST(:m AS uuid)",
                m=ma_cu,
            )
        return await goc(db, set_id)

    monkeypatch.setattr(luot_gui, "_luot_cho_gui_cua_bo", boc)
    r = await _mo(client, ad, bo["id"])
    assert r.status_code == 201, r.text
    assert r.json()["ma"] != ma_cu and da_chen == [1]
    assert await qd._q1(
        "SELECT count(*) FROM council_decision_submission WHERE set_id = :s AND trang_thai = 'cho_gui'", s=bo["id"]
    ) == 1


async def test_mat_phan_hoi_mo_luot_khoi_phuc_qua_id_bo_roi_phan_xu(client, hs, ad):  # noqa: F811
    # Bản 2 mục 3.7.5: mở lượt đã COMMIT nhưng trình duyệt mất phản hồi (không biết mã) ⇒ đọc danh sách lượt của bộ
    # theo id bộ (trong URL) ⇒ thấy lượt cho_gui + mã ⇒ "Chưa xác định" ⇒ phân xử. Không lưu mã ở trình duyệt.
    bo, ma = await _bo_va_ma(client, ad, hs)  # coi như phản hồi này bị mất — chỉ dùng id bộ từ đây
    ds = await client.get(P + "/sets/%d/luot-ghi-nhan" % bo["id"], headers=ad)
    assert ds.status_code == 200, ds.text
    cho = [x for x in ds.json() if x["trang_thai"] == "cho_gui"]
    assert [x["ma"] for x in cho] == [ma]
    r = await _phan_xu(client, ad, cho[0]["ma"])
    assert r.json()["ket_qua"] == "chua_ghi_da_chan", r.text
    ds = await client.get(P + "/sets/%d/luot-ghi-nhan" % bo["id"], headers=ad)
    assert [(x["ma"], x["trang_thai"]) for x in ds.json()] == [(ma, "da_chan")]


async def test_mat_phan_hoi_gui_phan_xu_tra_da_ghi(client, hs, ad):  # noqa: F811
    # Gửi đã COMMIT nhưng trình duyệt mất phản hồi ⇒ "Chưa xác định" ⇒ phân xử bằng mã ⇒ "đã ghi" + văn bản (không
    # bao giờ suy "chưa ghi"); phân xử lặp (mất phản hồi của chính phân xử) ⇒ cùng kết quả.
    bo, ma = await _bo_va_ma(client, ad, hs)
    r = await _gui(client, ad, bo["id"], ma)
    assert r.status_code == 201, r.text
    for _ in range(2):
        p = await _phan_xu(client, ad, ma)
        assert (p.json()["ket_qua"], p.json()["quyet_dinh"]["id"]) == ("da_ghi", r.json()["id"]), p.text


# ── gửi ──────────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_gui_thanh_cong_chot_da_ghi_cung_giao_dich(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    r = await _gui(client, ad, bo["id"], ma)
    assert r.status_code == 201, r.text
    assert (r.json()["ma_luot_gui"], r.json()["lap_lai"]) == (ma, False)
    x = await _luot(ma)
    assert (x["tt"], x["qd"]) == ("da_ghi", r.json()["id"])
    assert len(x["sha"]) == 64 and x["kt"] is not None


async def test_gui_lap_cung_noi_dung_tra_ban_cu_khong_ghi_lai(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    r1 = await _gui(client, ad, bo["id"], ma)
    assert r1.status_code == 201, r1.text
    r2 = await _gui(client, ad, bo["id"], ma)
    assert r2.status_code == 200, r2.text
    assert (r2.json()["id"], r2.json()["lap_lai"]) == (r1.json()["id"], True)
    assert r2.json()["canh_bao_vuot_chi_tieu"] == r1.json()["canh_bao_vuot_chi_tieu"]
    assert await _so_qd() == 1


async def test_gui_lai_cung_ma_noi_dung_khac_409(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    assert (await _gui(client, ad, bo["id"], ma)).status_code == 201
    r = await _gui(client, ad, bo["id"], ma, them={"ghi_chu_mau": "GIA khac noi dung"})
    assert r.status_code == 409 and r.json()["ma_loi"] == "luot_da_dung_noi_dung_khac", r.text
    assert await _so_qd() == 1


async def test_bi_tu_choi_nghiep_vu_luot_van_cho_gui_gui_lai_duoc(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    r = await _gui(client, ad, bo["id"], ma, so_hs=7)  # gõ lại sai số hồ sơ ⇒ từ chối SAU khi đã khoá lượt
    assert r.status_code == 400, r.text
    x = await _luot(ma)
    assert (x["tt"], x["sha"], x["kt"]) == ("cho_gui", None, None)
    r = await _gui(client, ad, bo["id"], ma)  # sửa rồi gửi lại CÙNG mã
    assert r.status_code == 201, r.text
    assert await _so_qd() == 1


async def test_gui_doi_song_song_cung_ma_dung_mot_van_ban(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    r1, r2 = await asyncio.gather(_gui(client, ad, bo["id"], ma), _gui(client, ad, bo["id"], ma))
    assert sorted([r1.status_code, r2.status_code]) == [200, 201], (r1.text, r2.text)
    assert r1.json()["id"] == r2.json()["id"]
    assert await _so_qd() == 1


# ── phân xử ──────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_phan_xu_chua_gui_thi_chan_lap_luy_dang_gui_muon_409(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    for _ in range(2):  # lần hai: luỹ đẳng
        r = await _phan_xu(client, ad, ma)
        assert r.status_code == 200 and r.json()["ket_qua"] == "chua_ghi_da_chan", r.text
    assert (await _luot(ma))["tt"] == "da_chan"
    r = await _gui(client, ad, bo["id"], ma)
    assert r.status_code == 409 and r.json()["ma_loi"] == "luot_da_chan", r.text
    assert await _so_qd() == 0
    assert (await _mo(client, ad, bo["id"])).status_code == 201  # mở lượt MỚI được


async def test_dong_bang_chan_phan_xu_va_mo_luot_luot_giu_nguyen(client, hs, ad, monkeypatch):  # noqa: F811
    # Codex lần 18 câu 2: đóng băng chặn CẢ phân xử — lượt chưa rõ GIỮ NGUYÊN ``cho_gui`` tới khi phân xử được, KHÔNG
    # thành "chưa ghi" (``da_chan``); không văn bản mới. Bỏ đóng băng ⇒ phân xử chạy bình thường trên CHÍNH lượt ấy.
    bo, ma = await _bo_va_ma(client, ad, hs)
    truoc = await _luot(ma)
    assert truoc["tt"] == "cho_gui"
    monkeypatch.setattr(app_settings, "ADMISSION_FROZEN", True)
    for r in (await _phan_xu(client, ad, ma), await _mo(client, ad, bo["id"])):
        assert r.status_code == 503 and r.json()["code"] == "ADMISSION_FROZEN", r.text
    assert await _luot(ma) == truoc
    assert await _so_qd() == 0
    monkeypatch.setattr(app_settings, "ADMISSION_FROZEN", False)
    r = await _phan_xu(client, ad, ma)
    assert r.status_code == 200 and r.json()["ket_qua"] == "chua_ghi_da_chan", r.text


async def test_phan_xu_sau_khi_da_ghi_tra_van_ban(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    r = await _gui(client, ad, bo["id"], ma)
    assert r.status_code == 201, r.text
    p = await _phan_xu(client, ad, ma)
    assert p.status_code == 200 and p.json()["ket_qua"] == "da_ghi", p.text
    assert p.json()["quyet_dinh"]["id"] == r.json()["id"]
    assert (await _luot(ma))["tt"] == "da_ghi"


async def test_phan_xu_ma_khong_co_404(client, hs, ad):  # noqa: F811
    r = await _phan_xu(client, ad, str(uuid.uuid4()))
    assert r.status_code == 404, r.text


def _giu_luot_sau_khi_khoa(monkeypatch, diem):
    """Ghi nhận DỪNG ngay sau câu khoá lượt (đang GIỮ lượt ``cho_gui``)."""
    goc = luot_gui.khoa_luot_cho_gui

    async def boc(*a, **kw):
        kq = await goc(*a, **kw)
        if kq is not None:
            await diem.cho()
        return kq

    monkeypatch.setattr(luot_gui, "khoa_luot_cho_gui", boc)


@pytest.mark.parametrize("ghi_nhan_ket_thuc", ["commit", "loi"])
async def test_phan_xu_khi_ghi_nhan_dang_giu_luot(client, hs, ad, monkeypatch, ghi_nhan_ket_thuc):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    diem = _Diem()
    _giu_luot_sau_khi_khoa(monkeypatch, diem)
    so_hs = 1 if ghi_nhan_ket_thuc == "commit" else 7  # 7 ⇒ bị từ chối SAU khi đã khoá lượt ⇒ rollback
    t_g = asyncio.create_task(_gui(client, ad, bo["id"], ma, so_hs=so_hs))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_p = asyncio.create_task(_phan_xu(client, ad, ma))
    do = await _cho_bi_chan_hoac_xong(t_p)
    diem.di.set()
    r_g, r_p = await asyncio.gather(t_g, t_p)
    assert do == "chan", "phép đo không hợp lệ: phân xử không chờ khoá lượt của ghi nhận"
    if ghi_nhan_ket_thuc == "commit":
        assert r_g.status_code == 201, r_g.text
        assert r_p.json()["ket_qua"] == "da_ghi" and r_p.json()["quyet_dinh"]["id"] == r_g.json()["id"], r_p.text
        assert await _so_qd() == 1
    else:
        assert r_g.status_code == 400, r_g.text
        assert r_p.json()["ket_qua"] == "chua_ghi_da_chan", r_p.text
        r = await _gui(client, ad, bo["id"], ma)  # gửi muộn sau khi đã chặn
        assert r.status_code == 409 and r.json()["ma_loi"] == "luot_da_chan", r.text
        assert await _so_qd() == 0


async def test_phan_xu_qua_tran_dang_xu_ly_khong_doi_luot(client, hs, ad, monkeypatch):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    diem = _Diem()
    _giu_luot_sau_khi_khoa(monkeypatch, diem)
    t_g = asyncio.create_task(_gui(client, ad, bo["id"], ma))
    await asyncio.wait_for(diem.toi.wait(), 30)
    r_p = await _phan_xu(client, ad, ma)  # ghi nhận giữ lượt quá trần 5 s
    assert r_p.status_code == 200 and r_p.json()["ket_qua"] == "dang_xu_ly", r_p.text
    assert (await _luot(ma))["tt"] == "cho_gui"  # phân xử đã rollback, không đổi gì
    diem.di.set()
    r_g = await t_g
    assert r_g.status_code == 201, r_g.text
    r = await _phan_xu(client, ad, ma)
    assert r.json()["ket_qua"] == "da_ghi", r.text


# ── xoá bộ ↔ lượt gửi ────────────────────────────────────────────────────────────────────────────────────────────
async def _xoa(client, ad, set_id):  # noqa: F811
    return await client.request("DELETE", P + "/sets/%d" % set_id, json={"ly_do": "GIA xoa thu luot gui"}, headers=ad)


async def test_xoa_bo_con_luot_cho_gui_409(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    r = await _xoa(client, ad, bo["id"])
    assert r.status_code == 409 and r.json()["ma_loi"] == "bo_co_luot_gui_chua_ro", r.text
    assert await qd._q1("SELECT count(*) FROM council_document_set WHERE id = :s", s=bo["id"]) == 1
    assert (await _luot(ma))["tt"] == "cho_gui"


async def test_xoa_bo_csdl_chan_cuoi_khi_con_cho_gui(client, hs, ad):  # noqa: F811
    # Lớp cuối (không qua service): khoá ngoại ON DELETE SET NULL + CHECK "cho_gui ⇒ có bộ" ⇒ CSDL từ chối.
    bo, ma = await _bo_va_ma(client, ad, hs)
    try:
        await qd._sql("DELETE FROM council_document_set WHERE id = :s", s=bo["id"])
        loi = None
    except DBAPIError as e:
        loi = ma_loi_csdl(e)
    assert loi == ("23514", "ck_council_decision_submission_cho_co_bo"), loi
    assert (await _luot(ma))["tt"] == "cho_gui"


async def test_xoa_bo_luot_da_ket_thuc_thi_giu_vet(client, hs, ad):  # noqa: F811
    bo, ma = await _bo_va_ma(client, ad, hs)
    assert (await _phan_xu(client, ad, ma)).json()["ket_qua"] == "chua_ghi_da_chan"
    r = await _xoa(client, ad, bo["id"])
    assert r.status_code == 200, r.text
    x = await _luot(ma)
    assert (x["tt"], x["set"], x["set_luc_tao"]) == ("da_chan", None, bo["id"])


async def test_xoa_truoc_thi_mo_luot_404(client, hs, ad):  # noqa: F811
    bo = await qd._bo_ok(client, ad, hs, SACH[:1])
    assert (await _xoa(client, ad, bo["id"])).status_code == 200
    r = await _mo(client, ad, bo["id"])
    assert r.status_code == 404, r.text


async def test_xoa_giu_khoa_bo_mo_luot_chen_giua_thi_cho_roi_404(client, hs, ad, monkeypatch):  # noqa: F811
    # Bản 2 mục 3.7.6 bước 1: xoá KHOÁ BỘ trước khi kiểm lượt. Xoá dừng SAU bước kiểm "không có lượt chờ" ⇒ mở lượt
    # chen vào phải CHỜ (INSERT có khoá ngoại cần KEY SHARE trên dòng bộ) ⇒ xoá xong ⇒ mở lượt 404. Thiếu khoá bộ thì
    # lượt mới commit chen giữa ⇒ DELETE vấp CHECK ở CSDL (500) thay vì kết quả rõ ràng.
    bo = await qd._bo_ok(client, ad, hs, SACH[:1])
    diem = _Diem()
    goc = luot_gui.co_luot_cho_gui

    async def boc(*a, **kw):
        kq = await goc(*a, **kw)
        await diem.cho()  # đã kiểm xong "không có lượt chờ", CHƯA DELETE
        return kq

    monkeypatch.setattr(luot_gui, "co_luot_cho_gui", boc)
    t_d = asyncio.create_task(_xoa(client, ad, bo["id"]))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_m = asyncio.create_task(_mo(client, ad, bo["id"]))
    do = await _cho_bi_chan_hoac_xong(t_m)
    diem.di.set()
    r_d, r_m = await asyncio.gather(t_d, t_m)
    assert do == "chan", "mở lượt không chờ khoá bộ của phiên xoá — xoá không khoá bộ trước khi kiểm lượt"
    assert r_d.status_code == 200, r_d.text
    assert r_m.status_code == 404, r_m.text
    assert await qd._q1("SELECT count(*) FROM council_decision_submission WHERE set_id_luc_tao = :s", s=bo["id"]) == 0


async def test_f272_ba_phien_khong_be_tac(client, hs, ad, monkeypatch):  # noqa: F811
    # Bản 3 mục 3.7.6: P phân xử (giữ lượt, chưa commit) → G ghi nhận CHỜ lượt → P commit (da_chan) → G 0 dòng, VẪN GIỮ
    # khoá dòng lượt đã kết thúc, dừng ở nhánh chỉ đọc → D xoá bộ: SET NULL dây chuyền CHỜ G → G kết thúc → D xong.
    bo, ma = await _bo_va_ma(client, ad, hs)
    diem_p, diem_g = _Diem(), _Diem()
    goc_px, goc_doc = luot_gui.phan_xu, luot_gui.doc_luot

    async def px(*a, **kw):
        kq = await goc_px(*a, **kw)
        await diem_p.cho()  # đã UPDATE lượt → da_chan, CHƯA commit
        return kq

    async def doc(*a, **kw):
        kq = await goc_doc(*a, **kw)
        await diem_g.cho()  # G ở nhánh 0 dòng (chỉ đọc), đang giữ khoá dòng lượt
        return kq

    monkeypatch.setattr(luot_gui, "phan_xu", px)
    monkeypatch.setattr(luot_gui, "doc_luot", doc)
    t_p = asyncio.create_task(_phan_xu(client, ad, ma))
    await asyncio.wait_for(diem_p.toi.wait(), 30)
    t_g = asyncio.create_task(_gui(client, ad, bo["id"], ma))
    assert await _cho_bi_chan_hoac_xong(t_g) == "chan", "phép đo không hợp lệ: G không chờ lượt"
    diem_p.di.set()
    r_p = await t_p
    assert r_p.json()["ket_qua"] == "chua_ghi_da_chan", r_p.text
    await asyncio.wait_for(diem_g.toi.wait(), 30)
    t_d = asyncio.create_task(_xoa(client, ad, bo["id"]))
    do_d = await _cho_bi_chan_hoac_xong(t_d)
    diem_g.di.set()
    r_g, r_d = await asyncio.gather(t_g, t_d)
    assert do_d == "chan", "phép đo không hợp lệ: D không chờ khoá dòng lượt mà G giữ"
    assert r_g.status_code == 409 and r_g.json()["ma_loi"] == "luot_da_chan", r_g.text
    assert r_d.status_code == 200, r_d.text  # không ai nhận 40P01
    x = await _luot(ma)
    assert (x["tt"], x["set"], x["set_luc_tao"]) == ("da_chan", None, bo["id"])
    assert await _so_qd() == 0
