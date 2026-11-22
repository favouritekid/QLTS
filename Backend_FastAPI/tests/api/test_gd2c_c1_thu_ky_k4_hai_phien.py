"""GĐ2-C C1 — thứ tự khoá người của đường gán / thu hồi quyền Thư ký so với K4 (xoá tài khoản), hai phiên PostgreSQL + phiên thứ
ba (``pg_blocking_pids``). Khuôn ``test_gd1b_xoa_tai_khoan_hai_phien.py`` ca 5 (owner 22-11 "K4 ↔ K4").

Luật (PR-B lượt 5–6): mọi đường ghi dòng có khoá ngoại tới ``user`` khoá (người đích ∪ người được tham chiếu) theo id TĂNG
TRƯỚC câu ghi, qua ``user_deletion_policy.lock_users_in_id_order`` — cùng chiều K4 (``FOR UPDATE ORDER BY id``).

- Gán ‖ K4: Admin A gán Thư ký cho U (id A < U), dừng SAU bước khoá người; Admin B xoá lô {A, U} ⇒ B phải CHỜ đúng lệnh của A;
  thả ⇒ A 201, B 409 (A và U đều đã có vết), 0 lỗi CSDL. Bản "chỉ khoá U ``FOR SHARE`` rồi ghi" (khuôn quyền duyệt chéo cũ):
  B giữ A chờ U, A giữ U chờ A (khoá ngoại ``granted_by_user_id`` lúc ghi) ⇒ bế tắc ``40P01`` ⇒ 500.
- Thu hồi ‖ K4: Admin A thu hồi, dừng SAU khi khoá dòng quyền (đã giữ A ``FOR KEY SHARE``); Admin B xoá A ⇒ B CHỜ đúng lệnh
  của A; thả ⇒ A 200, B 409, 0 lỗi CSDL. Bản không khoá A trước ⇒ B không chờ (``xong``) — ca đỏ vì sai thứ tự đã đo.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event

import app.database as csdl
from app.repositories import review_secretary_repository as sec_repo
from tests.api.gd1b_cheo_tro_giup import mot, tao_nguoi
from tests.api.gd1b_lo_tro_giup import NHAN, Diem, PidTheoNhan, bi_chan_boi, boc, dang_nhap, goi
from tests.api.gd2c_thu_ky_tro_giup import P, dong_quyen, gan
from tests.fixtures.constants import AdminURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _LoiCsdl:
    """Lỗi CSDL (lớp + SQLSTATE) theo nhãn yêu cầu — để ca đỏ nói ĐÚNG lý do (bế tắc / khoá ngoại), không chỉ "500"."""

    def __init__(self):
        self.loi = {}

    def __enter__(self):
        event.listen(csdl.engine.sync_engine, "handle_error", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(csdl.engine.sync_engine, "handle_error", self._ghi)

    def _ghi(self, ctx):
        from app.repositories.council_decision_repository import db_error_codes

        goc = ctx.original_exception
        lop = type(getattr(goc, "__cause__", None) or goc).__name__
        sqlstate, _ = db_error_codes(ctx.sqlalchemy_exception or goc)
        self.loi.setdefault(NHAN.get() or "?", []).append(f"{lop}/{sqlstate}")


async def _con(uid: int) -> bool:
    return await mot("SELECT count(*) FROM \"user\" WHERE id = :u", u=uid) == 1


async def test_gan_thu_ky_trong_luc_admin_khac_xoa_lo_gom_nguoi_gan_va_nguoi_duoc_gan_khong_be_tac(
    client, monkeypatch, admin_user_in_db, seed_lead_dependencies
):
    a = await tao_nguoi("gd2c_k4_admin_a", "admin", None)
    u = await tao_nguoi("gd2c_k4_canbo_u", "officer", seed_lead_dependencies["unit_id"])
    assert a["id"] < u["id"], "tiền đề: người gán A có id NHỎ hơn người được gán U (K4 của B khoá A trước U)"
    ca, ha = await dang_nhap(a)
    cb, hb = await dang_nhap(admin_user_in_db)
    diem = Diem()
    # A dừng SAU bước khoá người (đọc "đã có quyền chưa" là câu ĐẦU sau khoá), TRƯỚC mọi câu ghi.
    boc(monkeypatch, sec_repo, "active_grant_for_user", diem)
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            ta = asyncio.create_task(goi("A", lambda: ca.post(P, headers=ha, json={"user_id": u["id"], "reason": "Đợt 1"})))
            tb = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                xoa_lo = {"action": "delete", "user_ids": [a["id"], u["id"]]}
                tb = asyncio.create_task(goi("B", lambda: cb.post(AdminURLs.BULK_ACTION, headers=hb, json=xoa_lo)))
                tt = await bi_chan_boi(tb, ghi, bi="B", boi="A")
            finally:
                diem.di.set()
                if tb is None:
                    await asyncio.gather(ta, return_exceptions=True)
            ra, rb = await asyncio.gather(ta, tb)
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"lệnh xoá lô (B) phải CHỜ lệnh gán của A đang giữ khoá người ({tt})"
    assert (ra.status_code, rb.status_code, loi.loi) == (201, 409, {}), (ra.text, rb.text)
    assert rb.json()["error_code"] == "USER_HAS_ACTIVITY", rb.text
    assert await _con(a["id"]) and await _con(u["id"])
    assert (await dong_quyen(ra.json()["id"]))["granted_by_user_id"] == a["id"]


async def test_thu_hoi_thu_ky_trong_luc_admin_khac_xoa_nguoi_thu_hoi_khong_be_tac(
    client, monkeypatch, admin_user_in_db, seed_lead_dependencies
):
    a = await tao_nguoi("gd2c_k4_admin_thu_hoi", "admin", None)
    u = await tao_nguoi("gd2c_k4_canbo_thu_hoi", "officer", seed_lead_dependencies["unit_id"])
    g = (await gan(client, admin_user_in_db, u["id"]))["id"]
    ca, ha = await dang_nhap(a)
    cb, hb = await dang_nhap(admin_user_in_db)
    diem = Diem()
    boc(monkeypatch, sec_repo, "lock_grant_for_update", diem)  # A dừng SAU khi giữ A (KEY SHARE) + dòng quyền (UPDATE)
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            ta = asyncio.create_task(goi("A", lambda: ca.post(f"{P}/{g}/revoke", headers=ha, json={"reason": "Hết nhiệm vụ"})))
            tb = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                tb = asyncio.create_task(goi("B", lambda: cb.delete(AdminURLs.USER_DETAIL(a["id"]), headers=hb)))
                tt = await bi_chan_boi(tb, ghi, bi="B", boi="A")
            finally:
                diem.di.set()
                if tb is None:
                    await asyncio.gather(ta, return_exceptions=True)
            ra, rb = await asyncio.gather(ta, tb)
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"lệnh xoá A (B) phải CHỜ lệnh thu hồi của A đang giữ dòng người A ({tt})"
    assert (ra.status_code, rb.status_code, loi.loi) == (200, 409, {}), (ra.text, rb.text)
    assert rb.json()["error_code"] == "USER_HAS_ACTIVITY", rb.text
    assert await _con(a["id"])
    assert (await dong_quyen(g))["revoked_by_user_id"] == a["id"]
