# -*- coding: utf-8 -*-
"""PR-1 GĐ1 — C1 (Codex phần B, owner 21-11 — CHẶN F230): mọi thao tác đổi chuỗi Quyết định khoá GỐC chuỗi TRƯỚC, rồi
mới đọc lại chuỗi DƯỚI khoá ấy. Qua REQUEST THẬT, HAI phiên Admin + phiên CSDL THỨ BA (giữ khoá hồ sơ để dừng một phiên ở
giữa) — đo bằng ``pg_blocking_pids``; kết cục đo bằng SQL từ kết nối khác (CLAUDE.md §10).

Bất biến cuối (owner): **văn bản bổ sung / điều chỉnh còn hiệu lực ⇒ Quyết định gốc còn hiệu lực** — CSDL không có lớp
đỡ (chỉ CHECK từng hàng), tầng chủ sở hữu là service.

* C1-a — khôi phục văn bản con (huỷ ghi nhận văn bản huỷ của con) giữ gốc TRƯỚC; huỷ hiệu lực gốc tới SAU ⇒ chờ khoá gốc ⇒
  thấy con đã hiệu lực lại ⇒ 409 "còn văn bản bổ sung / điều chỉnh".
* C1-b — thứ tự ngược: huỷ hiệu lực gốc giữ gốc TRƯỚC (đã đọc "không có con hiệu lực"); khôi phục con tới SAU ⇒ chờ khoá
  gốc ⇒ thấy văn bản huỷ gốc ghi SAU ⇒ 409 "có văn bản ghi nhận SAU". (Biến thể "giữ khoá gốc nhưng đọc chuỗi TRƯỚC khoá"
  chỉ đỏ ở ca này — vì vậy phải đo cả hai thứ tự.)
* Cả hai ca lặp với con là văn bản BỔ SUNG và văn bản ĐIỀU CHỈNH.
* Anh em (xác minh C1 (6b)) — huỷ hiệu lực văn bản CON chen với điều chỉnh gốc bỏ dòng của con: em đã bị điều chỉnh bỏ tên
  KHÔNG được đưa vào nhóm chờ (kết cục tuần tự).

Mỗi ca: phép đo hợp lệ (phiên nào chờ phiên nào) được khẳng định SAU kết cục nghiệp vụ — để biến thể phá đỏ vì kết cục sai,
không đỏ vì phép đo.
"""
import asyncio
import time

import pytest
from sqlalchemy import text

import app.database as csdl
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

#: Văn bản con hiệu lực mà gốc KHÔNG hiệu lực — phải luôn 0.
SQL_CON_HIEU_LUC_GOC_KHONG = (
    "SELECT count(*) FROM council_decision c JOIN council_decision g ON g.id = c.goc_id "
    "WHERE c.trang_thai = 'hieu_luc' AND g.trang_thai <> 'hieu_luc'"
)


# ═══════════════════════════════ phiên thứ ba + pg_blocking_pids ═════════════════════════════
class PhienBa:
    """Kết nối CSDL riêng, MỘT giao dịch: giữ khoá ``FOR UPDATE`` trên hàng chọn trước để dừng một phiên ở đúng chỗ."""

    async def __aenter__(self):
        self.ket_noi = await csdl.engine.connect()
        self.giao_dich = await self.ket_noi.begin()
        self.pid = (await self.ket_noi.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        return self

    async def khoa(self, bang, ids):
        await self.ket_noi.execute(
            text("SELECT id FROM %s WHERE id = ANY(CAST(:i AS integer[])) ORDER BY id FOR UPDATE" % bang),
            {"i": sorted(ids)},
        )

    async def tha(self):
        if self.giao_dich.is_active:
            await self.giao_dich.rollback()

    async def __aexit__(self, *exc):
        await self.tha()
        await self.ket_noi.close()


async def pid_bi_chan_boi(pid):
    """Các phiên CSDL đang chờ khoá mà ``pid`` giữ (hoặc đứng trước trong hàng chờ)."""
    return [
        r[0]
        for r in await qd._q(
            "SELECT pid FROM pg_stat_activity WHERE datname = current_database() "
            "AND CAST(:p AS integer) = ANY(pg_blocking_pids(pid)) ORDER BY pid",
            p=pid,
        )
    ]


async def cho_bi_chan_boi(pid, viec, giay=30.0):
    """pid của phiên bị ``pid`` chặn; None nếu ``viec`` xong trước (không chờ ai) hoặc hết giờ."""
    het = time.monotonic() + giay
    while time.monotonic() < het:
        ds = await pid_bi_chan_boi(pid)
        if ds:
            return ds[0]
        if viec.done():
            return None
        await asyncio.sleep(0.1)
    return None


async def chan_cua(pid):
    """``pg_blocking_pids(pid)`` (tăng dần); None khi không đo được."""
    if pid is None:
        return None
    return sorted(await qd._q1("SELECT pg_blocking_pids(CAST(:p AS integer))", p=pid))


async def _trang_thai(*ids):
    return tuple(
        [await qd._q1("SELECT trang_thai FROM council_decision WHERE id = :d", d=i) for i in ids]
    )


# ═══════════════════════════════ dữ liệu: gốc + con đã bị huỷ hiệu lực ═══════════════════════
async def _chuoi_co_con_da_huy(client, ad, hs, con):  # noqa: F811
    """R (em ``SACH[0]``) + văn bản CON S của R (em ``SACH[1]``: bổ sung, hoặc điều chỉnh THÊM em) + văn bản huỷ H_S ⇒ S hết
    hiệu lực, em của S ở nhóm chờ. Trả (R, S, H_S) — DTO máy chủ."""
    _, r = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    if con == "bo_sung":
        b = await qd._bo_ok(client, ad, hs, [SACH[1]])
        s = await qd._ghi_ok(client, ad, b["id"], so="502", so_hs=1, loai="bo_sung", goc_id=r["id"])
    else:
        bd = await qd._bo_ok(client, ad, hs, [SACH[1]], duong="/decisions/%d/bo-dieu-chinh" % r["id"])
        rr = await qd._dieu_chinh(client, ad, r["id"], "502", set_id=bd["id"], so_hs=1)
        assert rr.status_code == 201, rr.text
        s = rr.json()
    rh = await qd._huy_hieu_luc(client, ad, s["id"], "701")
    assert rh.status_code == 201, rh.text
    assert await _trang_thai(r["id"], s["id"]) == ("hieu_luc", "het_hieu_luc")
    return r, s, rh.json()


# ═══════════════════════════════ C1-a: khôi phục con TRƯỚC, huỷ gốc SAU ═══════════════════════
@pytest.mark.parametrize("con", ["bo_sung", "dieu_chinh"])
async def test_c1_khoi_phuc_con_giu_goc_truoc_thi_huy_hieu_luc_goc_bi_409(client, hs, ad, con):  # noqa: F811
    # Thứ tự khoá mong đợi: A = huỷ ghi nhận H_S: gốc R → H_S → S → (đọc chuỗi) → mục chờ → hồ sơ em S [CHỜ phiên ba];
    # B = huỷ hiệu lực R: gốc R [CHỜ A]. Thả phiên ba ⇒ A khôi phục S, commit; B đọc lại DƯỚI khoá R ⇒ S hiệu lực ⇒ 409.
    # Mã cũ: B không chờ (A không giữ R) ⇒ đọc S còn hết hiệu lực ⇒ huỷ R; A khôi phục S ⇒ S hiệu lực dưới R hết hiệu lực.
    r, s, h_s = await _chuoi_co_con_da_huy(client, ad, hs, con)
    async with PhienBa() as ba:
        await ba.khoa("admission_profile", [hs[SACH[1]][1]])
        t_a = asyncio.create_task(qd._huy_ghi_nhan(client, ad, h_s["id"], "701"))
        pid_a = await cho_bi_chan_boi(ba.pid, t_a)
        assert pid_a is not None, "phép đo không hợp lệ: khôi phục con không tới bước khoá hồ sơ (chưa qua đọc chuỗi)"
        t_b = asyncio.create_task(qd._huy_hieu_luc(client, ad, r["id"], "702"))
        pid_b = await cho_bi_chan_boi(pid_a, t_b)
        chan_b = await chan_cua(pid_b)
        await ba.tha()
        r_a, r_b = await asyncio.gather(t_a, t_b)
    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 409 and r_b.json().get("van_ban_con_hieu_luc") == [s["id"]], r_b.text
    assert await qd._q1(SQL_CON_HIEU_LUC_GOC_KHONG) == 0
    assert await _trang_thai(r["id"], s["id"]) == ("hieu_luc", "hieu_luc")
    assert chan_b == [pid_a], "phép đo: huỷ hiệu lực gốc phải chờ ĐÚNG phiên khôi phục (khoá gốc) — %r" % (chan_b,)


# ═══════════════════════════════ C1-b: huỷ gốc TRƯỚC, khôi phục con SAU ═══════════════════════
@pytest.mark.parametrize("con", ["bo_sung", "dieu_chinh"])
async def test_c1_huy_hieu_luc_goc_giu_goc_truoc_thi_khoi_phuc_con_bi_409(client, hs, ad, con):  # noqa: F811
    # Thứ tự khoá mong đợi: B = huỷ hiệu lực R: gốc R → (đọc con: không con hiệu lực) → hồ sơ em R [CHỜ phiên ba];
    # A = huỷ ghi nhận H_S: gốc R [CHỜ B]. Thả ⇒ B ghi H_R, R hết hiệu lực, commit; A đọc chuỗi DƯỚI khoá R ⇒ thấy H_R ghi
    # SAU H_S ⇒ 409. Mã cũ (và biến thể "đọc chuỗi trước khoá gốc"): A không thấy H_R ⇒ khôi phục S dưới R đã hết hiệu lực.
    r, s, h_s = await _chuoi_co_con_da_huy(client, ad, hs, con)
    async with PhienBa() as ba:
        await ba.khoa("admission_profile", [hs[SACH[0]][1]])
        t_b = asyncio.create_task(qd._huy_hieu_luc(client, ad, r["id"], "702"))
        pid_b = await cho_bi_chan_boi(ba.pid, t_b)
        assert pid_b is not None, "phép đo không hợp lệ: huỷ hiệu lực gốc không tới bước khoá hồ sơ (chưa đọc con)"
        t_a = asyncio.create_task(qd._huy_ghi_nhan(client, ad, h_s["id"], "701"))
        pid_a = await cho_bi_chan_boi(pid_b, t_a)
        chan_a = await chan_cua(pid_a)
        await ba.tha()
        r_b, r_a = await asyncio.gather(t_b, t_a)
    assert r_b.status_code == 201, r_b.text
    assert r_a.status_code == 409 and r_a.json().get("van_ban_sau") == [r_b.json()["id"]], r_a.text
    assert await qd._q1(SQL_CON_HIEU_LUC_GOC_KHONG) == 0
    assert await _trang_thai(r["id"], s["id"], h_s["id"]) == ("het_hieu_luc", "het_hieu_luc", "hieu_luc")
    assert chan_a == [pid_b], "phép đo: khôi phục con phải chờ ĐÚNG phiên huỷ gốc (khoá gốc) — %r" % (chan_a,)


# ═══════════════════════════════ anh em (6b): huỷ hiệu lực CON × điều chỉnh gốc bỏ dòng của con ══════
async def test_c1_huy_hieu_luc_con_sau_dieu_chinh_bo_dong_khong_dua_em_vao_nhom_cho(client, hs, ad):  # noqa: F811
    # A = điều chỉnh R bỏ dòng em ``SACH[1]`` của S: gốc R → (dòng bỏ hợp lệ) → hồ sơ em [CHỜ phiên ba]; B = văn bản huỷ S:
    # gốc R [CHỜ A]. Thả ⇒ A bỏ dòng, commit; B đọc dòng hiệu lực của S DƯỚI khoá ⇒ không còn dòng em ⇒ em KHÔNG vào nhóm
    # chờ (đúng kết cục tuần tự A → B). Mã cũ (B chỉ khoá S): B đọc dòng em TRƯỚC khi A commit ⇒ đưa em vào nhóm chờ dù
    # văn bản điều chỉnh (còn hiệu lực) đã bỏ tên em.
    _, r = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    b = await qd._bo_ok(client, ad, hs, [SACH[1]])
    s = await qd._ghi_ok(client, ad, b["id"], so="502", so_hs=1, loai="bo_sung", goc_id=r["id"])
    em = hs[SACH[1]][1]
    dong = await qd._dong_cua(s["id"], em)
    async with PhienBa() as ba:
        await ba.khoa("admission_profile", [em])
        t_a = asyncio.create_task(qd._dieu_chinh(client, ad, r["id"], "801", bo_dong=[dong]))
        pid_a = await cho_bi_chan_boi(ba.pid, t_a)
        assert pid_a is not None, "phép đo không hợp lệ: điều chỉnh không tới bước khoá hồ sơ"
        t_b = asyncio.create_task(qd._huy_hieu_luc(client, ad, s["id"], "701"))
        pid_b = await cho_bi_chan_boi(pid_a, t_b)
        chan_b = await chan_cua(pid_b)
        await ba.tha()
        r_a, r_b = await asyncio.gather(t_a, t_b)
    assert r_a.status_code == 201, r_a.text
    assert r_b.status_code == 201, r_b.text
    assert r_b.json()["so_lieu"]["so_muc_cho_moi"] == 0, r_b.text
    assert await qd._q1(
        "SELECT count(*) FROM council_decision_hold WHERE profile_id = :p AND trang_thai = 'cho_quyet'", p=em
    ) == 0
    assert await qd._q1("SELECT bi_bo_boi_id FROM council_decision_row WHERE id = :d", d=dong) == r_a.json()["id"]
    assert chan_b == [pid_a], "phép đo: văn bản huỷ của con phải chờ phiên điều chỉnh — %r" % (chan_b,)
