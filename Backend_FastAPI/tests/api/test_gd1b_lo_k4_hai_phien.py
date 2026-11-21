"""GĐ1b K4 ‖ lô duyệt giấy — HTTP thật, hai phiên PostgreSQL + phiên thứ ba đo (đặc tả bản 3.6 §4.3, §5.2, §5.3 bước 2,
§5.7; xác minh Codex F7, 20-11).

K4 (``user_deletion_policy.assert_user_deletable``) khoá NGƯỜI ``FOR UPDATE``, kiểm (chỉ đọc), rồi xoá lô ``previewed`` của
người ấy và xoá người. Bản cũ của các đường lô chạm DÒNG LÔ trước rồi mới chạm dòng người (khoá ngoại
``document_bulk_batch.actor_user_id`` / ``finalized_by_user_id`` RESTRICT ⇒ khoá ``FOR KEY SHARE`` dòng người lúc ghi) —
ngược chiều K4:

- ca a — xem trước đang giữ dòng lô cũ (bước dọn ``FOR UPDATE SKIP LOCKED``) ‖ xoá người bấm ⇒ xoá chờ dòng lô, xem trước
  chèn lô mới chờ dòng người ⇒ bế tắc ⇒ 500;
- ca b — chạy lô đã đổi ``processing`` CHƯA commit ‖ xoá người tạo ⇒ K4 kiểm thấy ``previewed`` (không chặn), bỏ qua lô
  vừa đổi rồi xoá người ⇒ ``23503`` ⇒ 500 thay vì 409;
- ca c / f / e — xoá tài khoản đã khoá người + kiểm xong, CHƯA xoá lô ‖ xem trước / chạy lô / chốt lô của chính người ấy
  ⇒ bế tắc hoặc ``23503`` ⇒ 500;
- ca d — người tạo bị khoá tài khoản giữa bước 1 và bước 2 của chạy lô ⇒ §5.3 "kiểm lại người tạo dưới khoá".

Sau sửa: mọi đường lô khoá NGƯỜI TRƯỚC dòng lô (cùng chiều K4) — ``FOR KEY SHARE`` ở xem trước / chạy lô, ``FOR SHARE`` ở
chốt lô (giữ vai ổn định, ``test_gd1b_lo_chot_ha_vai_hai_phien.py``) — rồi kiểm người còn + đang hoạt động; không đạt ⇒ 409
``actor_not_authorized`` (mã có sẵn). Thứ tự khoá toàn cục: người → dòng lô → quyền chéo → hồ sơ → lead → giấy → người thao
tác ``FOR SHARE`` (cuối; không xung đột với khoá người đầu).

Kiểm ngược (bản chép ngoài kho): bỏ khoá người ở xem trước ⇒ a, c đỏ; ở chạy lô ⇒ b, d, f đỏ; khoá người SAU dòng lô ở
chạy lô ⇒ f đỏ (bế tắc); bỏ khoá người ở chốt lô ⇒ e đỏ.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as csdl
from app import models
from app.database import AsyncSessionLocal
from app.repositories.council_decision_repository import db_error_codes
from app.security import get_password_hash
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    NHAN,
    Diem,
    PidTheoNhan,
    bi_chan_boi,
    boc,
    dang_nhap,
    dn,
    dong_lo,
    goi,
    lo_config,
    lo_routers,
    sql,
    tao_ho_so_cho_xet,
    xac_nhan,
)
from tests.fixtures.constants import AdminURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Câu đầu tiên K4 ghi sau khi khoá + kiểm xong (``_EXPLICIT_DELETES`` xếp theo bảng — lô đứng trước thông báo).
K4_XOA_LO = 'DELETE FROM "document_bulk_batch"'


class _LoiCsdl:
    """Lỗi CSDL (lớp lỗi asyncpg / SQLSTATE) theo nhãn yêu cầu — để ca đỏ nói ĐÚNG lý do."""

    def __init__(self):
        self.loi = {}

    def __enter__(self):
        event.listen(csdl.engine.sync_engine, "handle_error", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(csdl.engine.sync_engine, "handle_error", self._ghi)

    def _ghi(self, ctx):
        goc = ctx.original_exception
        lop = type(getattr(goc, "__cause__", None) or goc).__name__
        sqlstate, _ = db_error_codes(ctx.sqlalchemy_exception or goc)
        self.loi.setdefault(NHAN.get() or "?", []).append(f"{lop}/{sqlstate}")


def _dung_k4_truoc_khi_xoa_lo(monkeypatch, diem: Diem, nhan: str = "D"):
    """Yêu cầu mang nhãn ``nhan`` (lệnh xoá tài khoản) dừng NGAY TRƯỚC câu xoá lô ``previewed`` của K4: đã khoá người
    ``FOR UPDATE`` + kiểm đạt, CHƯA xoá dòng nào — điểm hẹp nhất giữa khoá người và xoá lô."""
    goc = AsyncSession.execute

    async def execute(self, statement, *a, **kw):
        cau = getattr(statement, "text", None)  # chỉ câu ``text(...)`` — K4 ghi bằng câu thô
        if NHAN.get() == nhan and isinstance(cau, str) and cau.startswith(K4_XOA_LO):
            await diem.cho()
        return await goc(self, statement, *a, **kw)

    monkeypatch.setattr(AsyncSession, "execute", execute)


async def _xem_truoc(client, user, ids) -> str:
    h = await dn(client, user)
    r = await client.post(f"{BULK}/preview", headers=h, json={"profile_ids": ids})
    assert r.status_code == 201, r.text
    return r.json()["batch_id"]


async def _con(uid: int) -> bool:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(models.User).where(models.User.id == uid))).scalar() == 1


async def _so_lo(uid: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(func.count()).select_from(models.DocumentBulkBatch)
                .where(models.DocumentBulkBatch.actor_user_id == uid)
            )
        ).scalar_one()


async def _song_song(truoc, sau, *, diem: Diem, bi: str, boi: str):
    """``truoc`` = ``(nhãn, hàm)`` chạy tới điểm dừng rồi CHỜ; ``sau`` = ``(nhãn, hàm)`` chạy; đo ``sau`` có bị ``truoc``
    chặn (``pg_blocking_pids``); thả. Trả ``(kết quả truoc, kết quả sau, trạng thái đo, lỗi CSDL)``."""
    with PidTheoNhan() as ghi, _LoiCsdl() as loi:
        t1 = asyncio.create_task(goi(*truoc))
        t2 = None
        try:
            await asyncio.wait_for(diem.toi.wait(), 30)
            t2 = asyncio.create_task(goi(*sau))
            tt = await bi_chan_boi(t2, ghi, bi=bi, boi=boi)
        finally:
            diem.di.set()
            if t2 is None:
                await asyncio.gather(t1, return_exceptions=True)
        r1, r2 = await asyncio.gather(t1, t2)
    return r1, r2, tt, loi.loi


# --------------------------------------------------------------------------------------------------------------------
# Ca a — xem trước (đang giữ bản cũ sau bước dọn) ‖ xoá người bấm ⇒ xoá CHỜ, rồi xoá cả hai bản xem trước cùng người.
# --------------------------------------------------------------------------------------------------------------------
async def test_xem_truoc_dang_giu_ban_cu_thi_xoa_nguoi_bam_cho_roi_xoa_ca_ban_xem_truoc(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    from app.repositories import document_bulk_repository as repo

    ps = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "k4lo_a", giay_nhan="AB")
    await _xem_truoc(client, manager_user_in_db, [ps["id"]])  # bản cũ — bước dọn của lượt sau GIỮ dòng này FOR UPDATE
    diem = Diem()
    boc(monkeypatch, repo, "cleanup_previews", diem)
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(admin_user_in_db)
    try:
        rp, rd, tt, loi = await _song_song(
            ("P", lambda: ca.post(f"{BULK}/preview", headers=ha, json={"profile_ids": [ps["id"]]})),
            ("D", lambda: cb.delete(AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb)),
            diem=diem, bi="D", boi="P",
        )
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"xoá tài khoản (D) phải CHỜ khoá mà lượt xem trước (P) đang giữ ({tt})"
    assert (rp.status_code, rd.status_code) == (201, 200), (rp.status_code, rd.status_code, rp.text, rd.text, loi)
    assert not await _con(manager_user_in_db["id"])
    assert await _so_lo(manager_user_in_db["id"]) == 0


# --------------------------------------------------------------------------------------------------------------------
# Ca b — chạy lô đã đổi ``processing`` CHƯA commit ‖ xoá người tạo ⇒ xoá CHỜ, rồi thấy lô đã chạy ⇒ 409, không 500.
# --------------------------------------------------------------------------------------------------------------------
async def test_chay_lo_da_doi_processing_chua_commit_thi_xoa_nguoi_tao_cho_roi_409(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    from app.repositories import document_bulk_repository as repo

    ps = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "k4lo_b", giay_nhan="AB")
    ma = await _xem_truoc(client, manager_user_in_db, [ps["id"]])
    than = await xac_nhan(ma)
    diem = Diem()
    boc(monkeypatch, repo, "set_batch_status", diem)  # lần gọi ĐẦU = bước 2 đổi ``processing``, CHƯA commit
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(admin_user_in_db)
    try:
        re, rd, tt, loi = await _song_song(
            ("E", lambda: ca.post(f"{BULK}/{ma}/execute", headers=ha, json=than)),
            ("D", lambda: cb.delete(AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb)),
            diem=diem, bi="D", boi="E",
        )
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"xoá tài khoản (D) phải CHỜ khoá mà lượt chạy lô (E) đang giữ ({tt})"
    assert re.status_code == 200 and re.json()["status"] == "completed", (re.status_code, re.text, loi)
    assert rd.status_code == 409 and rd.json()["error_code"] == "USER_HAS_ACTIVITY", (rd.status_code, rd.text, loi)
    assert await _con(manager_user_in_db["id"])


# --------------------------------------------------------------------------------------------------------------------
# Ca c — xoá tài khoản ĐÃ khoá người + kiểm, CHƯA xoá lô ‖ xem trước của chính người ấy ⇒ xem trước CHỜ, rồi 409.
# --------------------------------------------------------------------------------------------------------------------
async def test_xoa_nguoi_bam_dang_giu_khoa_thi_xem_truoc_cho_roi_409_khong_chen_lo(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    ps = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "k4lo_c", giay_nhan="AB")
    await _xem_truoc(client, manager_user_in_db, [ps["id"]])  # bản cũ — thứ tự cũ: bước dọn giữ dòng này ⇒ bế tắc
    diem = Diem()
    _dung_k4_truoc_khi_xoa_lo(monkeypatch, diem)
    ca, ha = await dang_nhap(manager_user_in_db)  # xác thực TRƯỚC khi bị xoá
    cb, hb = await dang_nhap(admin_user_in_db)
    try:
        rd, rp, tt, loi = await _song_song(
            ("D", lambda: cb.delete(AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb)),
            ("P", lambda: ca.post(f"{BULK}/preview", headers=ha, json={"profile_ids": [ps["id"]]})),
            diem=diem, bi="P", boi="D",
        )
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"xem trước (P) phải CHỜ khoá người mà lệnh xoá (D) đang giữ ({tt})"
    assert rd.status_code == 200, (rd.status_code, rd.text, loi)
    assert rp.status_code == 409 and rp.json()["error_code"] == "ACTOR_NOT_AUTHORIZED", (rp.status_code, rp.text, loi)
    assert await _so_lo(manager_user_in_db["id"]) == 0


# --------------------------------------------------------------------------------------------------------------------
# Ca d — người tạo bị khoá tài khoản giữa bước 1 (khoá lô) và bước 2 ⇒ §5.3 kiểm lại người tạo DƯỚI khoá ⇒ 409, lô KHÔNG chạy.
# --------------------------------------------------------------------------------------------------------------------
async def test_nguoi_tao_bi_khoa_tai_khoan_truoc_buoc_2_thi_409_lo_khong_chay(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.repositories import document_bulk_repository as repo

    ps = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "k4lo_d", giay_nhan="AB")
    ma = await _xem_truoc(client, manager_user_in_db, [ps["id"]])
    than = await xac_nhan(ma)
    diem = Diem()
    boc(monkeypatch, repo, "try_lock_batch", diem)  # ĐÃ giữ khoá lô trên L, CHƯA vào giao dịch bước 2
    ca, ha = await dang_nhap(manager_user_in_db)
    try:
        t = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=than))
        try:
            await asyncio.wait_for(diem.toi.wait(), 30)
            await sql("UPDATE \"user\" SET status = 'inactive' WHERE id = :u", u=manager_user_in_db["id"])
        finally:
            diem.di.set()
        r = await t
    finally:
        await ca.aclose()
    assert r.status_code == 409 and r.json()["error_code"] == "ACTOR_NOT_AUTHORIZED", (r.status_code, r.text)
    lo = await dong_lo(ma)
    assert lo["status"] == "previewed" and lo["started_at"] is None, lo


# --------------------------------------------------------------------------------------------------------------------
# Ca e — xoá Admin ĐÃ khoá người + kiểm, CHƯA xoá lô ‖ Admin ấy chốt lô gián đoạn của người khác ⇒ chốt CHỜ, rồi 409.
# --------------------------------------------------------------------------------------------------------------------
async def test_xoa_admin_dang_giu_khoa_thi_admin_ay_chot_lo_cho_roi_409_khong_ghi(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule

    from app.main import fastapi_app
    from tests.fixtures.users import create_user_with_role

    ps = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "k4lo_e", giay_nhan="AB")
    ma = await _xem_truoc(client, manager_user_in_db, [ps["id"]])
    # Lô ``processing`` không ai giữ khoá (người chạy đã chết) ⇒ ``interrupted_unfinalized``, chốt được.
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    admin_chot = await create_user_with_role(  # Admin CHƯA từng thao tác gì ⇒ K4 cho xoá
        session_factory=AsyncSessionLocal,
        user_data={
            "username": "k4lo_admin_chot", "email": "k4lo_admin_chot@example.com", "password": "AdminChotLo!123",
            "role": "admin", "status": "active",
        },
        casbin_role="role:admin",
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )
    diem = Diem()
    _dung_k4_truoc_khi_xoa_lo(monkeypatch, diem)
    cf, hf = await dang_nhap(admin_chot)  # xác thực TRƯỚC khi bị xoá
    cd, hd = await dang_nhap(admin_user_in_db)
    try:
        rd, rf, tt, loi = await _song_song(
            ("D", lambda: cd.delete(AdminURLs.USER_DETAIL(admin_chot["id"]), headers=hd)),
            ("F", lambda: cf.post(f"{BULK}/{ma}/finalize", headers=hf, json={"reason": "Người chạy lô đã nghỉ"})),
            diem=diem, bi="F", boi="D",
        )
    finally:
        await cf.aclose()
        await cd.aclose()
    assert tt == "chan", f"chốt lô (F) phải CHỜ khoá người mà lệnh xoá (D) đang giữ ({tt})"
    assert rd.status_code == 200, (rd.status_code, rd.text, loi)
    assert rf.status_code == 409 and rf.json()["error_code"] == "ACTOR_NOT_AUTHORIZED", (rf.status_code, rf.text, loi)
    lo = await dong_lo(ma)
    assert lo["status"] == "processing" and lo["finalized_by_user_id"] is None, lo


# --------------------------------------------------------------------------------------------------------------------
# Ca f — xoá người tạo ĐÃ khoá người + kiểm, CHƯA xoá lô ‖ chạy lô ⇒ chạy CHỜ; xoá xong (lô ``previewed`` đi cùng) ⇒ 404.
# --------------------------------------------------------------------------------------------------------------------
async def test_xoa_nguoi_tao_dang_giu_khoa_thi_chay_lo_cho_roi_404_preview_gone(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    ps = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "k4lo_f", giay_nhan="AB")
    ma = await _xem_truoc(client, manager_user_in_db, [ps["id"]])
    than = await xac_nhan(ma)
    diem = Diem()
    _dung_k4_truoc_khi_xoa_lo(monkeypatch, diem)
    ca, ha = await dang_nhap(manager_user_in_db)  # xác thực TRƯỚC khi bị xoá
    cb, hb = await dang_nhap(admin_user_in_db)
    try:
        rd, re, tt, loi = await _song_song(
            ("D", lambda: cb.delete(AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb)),
            ("E", lambda: ca.post(f"{BULK}/{ma}/execute", headers=ha, json=than)),
            diem=diem, bi="E", boi="D",
        )
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"chạy lô (E) phải CHỜ khoá người mà lệnh xoá (D) đang giữ ({tt})"
    assert rd.status_code == 200, (rd.status_code, rd.text, loi)
    assert re.status_code == 404 and re.json()["error_code"] == "PREVIEW_GONE", (re.status_code, re.text, loi)
    assert await dong_lo(ma) is None
