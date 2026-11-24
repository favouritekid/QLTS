"""GĐ1b chốt lô ‖ hạ vai người chốt — HTTP thật, hai phiên PostgreSQL + phiên thứ ba đo (đặc tả bản 3.6 §5.7; điểm chặn
Codex 20-11 cho PR-A).

Lỗi: ``finalize_batch`` khi Admin chốt lô của NGƯỜI KHÁC xét quyền bằng ``viewer_role`` đọc từ ĐẦU yêu cầu, còn bước ngay
trước khi ghi chỉ khoá dòng người ``FOR KEY SHARE`` và đọc lại ``(id, status)``. ``FOR KEY SHARE`` chặn xoá tài khoản nhưng
KHÔNG chặn ``UPDATE`` vai / trạng thái ⇒ Admin vừa bị hạ vai (tài khoản vẫn hoạt động) vẫn chốt được lô bằng quyền cũ.

Sau sửa: bước 3 khoá dòng người chốt ``FOR SHARE`` (``repo.lock_user_role_share``; vẫn NGƯỜI → LÔ như K4), đọc
``(id, status, role)`` DƯỚI khoá và xét quyền bằng VAI HIỆN HÀNH: người tạo, hoặc vai hiện hành là Admin. Không còn quyền
⇒ 404 cùng thân với cổng bước 0; tài khoản không còn / không hoạt động ⇒ 409 ``actor_not_authorized`` (như PR-A). Lô giữ
nguyên, không ghi nhật ký.

Mỗi ca kiểm MỘT bất biến; đổi vai bằng route Admin THẬT (``PUT /api/admin/users/{id}``, form ``role``):

- ca a — hạ vai đã COMMIT trước khi chốt khoá dòng người ⇒ chốt đọc ra vai MỚI ⇒ 404, lô giữ nguyên, không nhật ký chốt
  (bất biến: quyền chốt xét bằng vai hiện hành, không bằng vai đầu yêu cầu);
- ca b — chốt ĐANG giữ khoá dòng người ⇒ lệnh hạ vai phải CHỜ (phiên thứ ba thấy qua ``pg_blocking_pids``) ⇒ thả ⇒ chốt
  200 + nhật ký chốt ⇒ hạ vai hoàn tất sau (bất biến: vai đọc dưới khoá giữ nguyên tới lúc ghi).

Điểm dừng chỉ dùng hàm có ở CẢ mã cũ lẫn mã mới — ``try_xact_lock_batch`` (ngay TRƯỚC câu khoá dòng người) và
``lock_batch_row`` (ngay SAU câu khoá dòng người) — nên hai ca chạy được trên mã cũ và đỏ đúng lý do.

Kiểm ngược (bản chép ngoài kho): (i) ``lock_user_role_share`` quay lại ``FOR KEY SHARE`` ⇒ ca b đỏ (hạ vai không chờ);
(ii) xét quyền bằng ``viewer_role`` đầu yêu cầu ⇒ ca a đỏ (chốt thành công).
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text

from app import models
from app.database import AsyncSessionLocal
from app.security import get_password_hash
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    Diem,
    PidTheoNhan,
    bi_chan_boi,
    boc,
    dang_nhap,
    dn,
    dong_lo,
    dong_muc,
    goi,
    lo_config,
    lo_routers,
    sql,
    tao_ho_so_cho_xet,
)
from tests.fixtures.constants import AdminURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

LY_DO = "Người chạy lô đã nghỉ, lô treo"
#: Vai sau khi hạ — Quản lý vẫn qua cổng Casbin của route lô nhưng KHÔNG phải Admin ⇒ chỉ chốt được lô của chính mình.
VAI_MOI = "manager"


async def _lo_gian_doan(client, admin_headers, officer, manager, cfg, hau_to: str) -> str:
    """Lô của Quản lý ở ``processing`` mà không ai giữ khoá (người chạy đã chết) ⇒ ``interrupted_unfinalized``, chốt được."""
    ps = await tao_ho_so_cho_xet(client, admin_headers, officer, cfg, hau_to, giay_nhan="AB")
    h = await dn(client, manager)
    r = await client.post(f"{BULK}/preview", headers=h, json={"profile_ids": [ps["id"]]})
    assert r.status_code == 201, r.text
    ma = r.json()["batch_id"]
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    return ma


async def _admin_chot(ten: str) -> dict:
    """Admin thứ hai — người chốt, KHÁC người tạo lô; sẽ bị Admin gốc hạ vai."""
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule

    from app.main import fastapi_app
    from tests.fixtures.users import create_user_with_role

    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": ten, "email": f"{ten}@example.com", "password": "AdminChotLo!123",
            "role": "admin", "status": "active",
        },
        casbin_role="role:admin",
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )


def _ha_vai(c, h, user_id: int):
    """Route Admin THẬT: hạ vai Admin → Quản lý; tài khoản vẫn ``active``."""
    return c.put(AdminURLs.USER_DETAIL(user_id), headers=h, data={"role": VAI_MOI})


async def _vai(uid: int) -> str:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(models.User.role).where(models.User.id == uid))).scalar_one()


async def _nhat_ky_chot(ma: str) -> list:
    async with AsyncSessionLocal() as s:
        return [
            dict(r)
            for r in (
                await s.execute(
                    text(
                        "SELECT actor_user_id, reason FROM entity_audit_log WHERE entity_type = 'document_bulk_batch'"
                        " AND action = 'finalize_by_admin' AND new_value->>'batch_id' = :b"
                    ),
                    {"b": str(ma)},
                )
            ).mappings().all()
        ]


async def _hai_luot(dau, sau, *, diem: Diem):
    """``dau`` = ``(nhãn, hàm)`` chạy tới điểm dừng rồi CHỜ; ``sau`` = ``(nhãn, hàm)`` chạy trong lúc ``dau`` còn dừng; phiên
    thứ ba đo ``sau`` có bị ``dau`` chặn không (``pg_blocking_pids``) — đo XONG rồi mới thả ``dau``.

    Trả ``(kết quả dau, kết quả sau, trạng thái đo, câu cuối của sau lúc đo)``: ``chan`` = ``sau`` đang chờ khoá ``dau`` giữ;
    ``xong`` = ``sau`` đã xong trong lúc ``dau`` còn dừng."""
    cau_cuoi = None
    with PidTheoNhan() as ghi:
        t1 = asyncio.create_task(goi(*dau))
        t2 = None
        tt = None
        try:
            await asyncio.wait_for(diem.toi.wait(), 30)
            t2 = asyncio.create_task(goi(*sau))
            tt = await bi_chan_boi(t2, ghi, bi=sau[0], boi=dau[0])
            cau_cuoi = (ghi.cau.get(sau[0]) or [None])[-1]
        finally:
            diem.di.set()
            if t2 is None:
                await asyncio.gather(t1, return_exceptions=True)
        r1, r2 = await asyncio.gather(t1, t2)
    return r1, r2, tt, cau_cuoi


# --------------------------------------------------------------------------------------------------------------------
# Ca a — hạ vai COMMIT trước khi chốt khoá dòng người ⇒ chốt lô của người khác bị từ chối (404), lô giữ nguyên.
# --------------------------------------------------------------------------------------------------------------------
async def test_ha_vai_admin_xong_truoc_khi_chot_khoa_nguoi_thi_chot_lo_nguoi_khac_404_lo_giu_nguyen(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    from app.repositories import document_bulk_repository as repo
    from app.services.document_bulk_verify_service import BATCH_NOT_FOUND_DETAIL

    ma = await _lo_gian_doan(client, admin_token_headers, officer_user_in_db, manager_user_in_db, lo_config, "chotvai_a")
    admin_chot = await _admin_chot("chotvai_admin_a")
    cf, hf = await dang_nhap(admin_chot)  # xác thực khi CÒN là Admin ⇒ qua cổng bước 0 bằng vai Admin
    cr, hr = await dang_nhap(admin_user_in_db)
    diem = Diem()
    # Chốt dừng ngay SAU khi giữ khoá giao dịch của lô = ngay TRƯỚC câu khoá dòng người (mã cũ lẫn mã mới).
    boc(monkeypatch, repo, "try_xact_lock_batch", diem)
    try:
        rf, rr, tt, _ = await _hai_luot(
            ("F", lambda: cf.post(f"{BULK}/{ma}/finalize", headers=hf, json={"reason": LY_DO})),
            ("R", lambda: _ha_vai(cr, hr, admin_chot["id"])),
            diem=diem,
        )
    finally:
        await cf.aclose()
        await cr.aclose()
    # Tiền đề của ca (không phải bất biến đang kiểm): hạ vai đã COMMIT xong trong lúc chốt còn dừng trước khoá dòng người.
    assert tt == "xong" and rr.status_code == 200, f"tiền đề: hạ vai (R) phải xong khi chốt (F) còn dừng ({tt}; {rr.text})"
    assert await _vai(admin_chot["id"]) == VAI_MOI
    # Bất biến: quyền chốt xét bằng VAI HIỆN HÀNH đọc dưới khoá ⇒ không còn Admin, không phải người tạo ⇒ 404 cùng thân.
    assert rf.status_code == 404 and rf.json() == {"detail": BATCH_NOT_FOUND_DETAIL, "error_code": "RESOURCE_NOT_FOUND"}, (
        f"Admin đã bị hạ vai TRƯỚC khi chốt khoá dòng người vẫn chốt được lô của người khác: {rf.status_code} {rf.text}"
    )
    lo = await dong_lo(ma)
    assert (lo["status"], lo["finalized_by_user_id"], lo["finalized_at"], lo["finalize_reason"]) == (
        "processing", None, None, None
    ), lo
    muc = await dong_muc(ma)
    assert muc and all(m["result"] is None for m in muc), muc
    assert await _nhat_ky_chot(ma) == []


# --------------------------------------------------------------------------------------------------------------------
# Ca b — chốt ĐANG giữ khoá dòng người ⇒ hạ vai CHỜ ⇒ thả ⇒ chốt 200 + nhật ký ⇒ hạ vai hoàn tất sau.
# --------------------------------------------------------------------------------------------------------------------
async def test_chot_dang_giu_khoa_nguoi_thi_ha_vai_cho_roi_chot_200_co_nhat_ky(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    from app.repositories import document_bulk_repository as repo

    ma = await _lo_gian_doan(client, admin_token_headers, officer_user_in_db, manager_user_in_db, lo_config, "chotvai_b")
    admin_chot = await _admin_chot("chotvai_admin_b")
    cf, hf = await dang_nhap(admin_chot)
    cr, hr = await dang_nhap(admin_user_in_db)
    diem = Diem()
    # Chốt dừng ngay SAU câu khoá dòng lô — tức ĐÃ khoá dòng người và đọc vai dưới khoá (người → lô); chưa xét quyền, chưa
    # ghi gì, chưa commit.
    boc(monkeypatch, repo, "lock_batch_row", diem)
    try:
        rf, rr, tt, cau = await _hai_luot(
            ("F", lambda: cf.post(f"{BULK}/{ma}/finalize", headers=hf, json={"reason": LY_DO})),
            ("R", lambda: _ha_vai(cr, hr, admin_chot["id"])),
            diem=diem,
        )
    finally:
        await cf.aclose()
        await cr.aclose()
    # Bất biến: khoá dòng người của lượt chốt giữ VAI ổn định ⇒ lệnh hạ vai phải CHỜ ở câu GHI-KHOÁ dòng ``user``. Từ PR-B
    # (Q4 tự thu hồi), đường đổi vai khoá dòng người ``FOR NO KEY UPDATE`` (``repo.lock_user_no_key_update``) TRƯỚC câu
    # ``UPDATE "user"`` — cùng loại khoá dòng mà ``UPDATE`` lấy, nên cả hai câu đều là "chờ đúng lý do".
    cau_r = " ".join((cau or "").split()).upper()
    cho_dung_cau = cau_r.startswith('UPDATE "USER"') or (
        cau_r.startswith("SELECT") and 'FROM "USER"' in cau_r and cau_r.endswith("FOR NO KEY UPDATE")
    )
    assert tt == "chan" and cho_dung_cau, (
        f"hạ vai (R) phải CHỜ khoá dòng người mà lượt chốt (F) đang giữ — đo: {tt}; câu cuối của R: {cau!r}"
    )
    assert rf.status_code == 200 and rf.json()["finalized_now"] is True, (rf.status_code, rf.text)
    lo = await dong_lo(ma)
    assert lo["status"] == "interrupted" and lo["finalized_by_user_id"] == admin_chot["id"], lo
    nk = await _nhat_ky_chot(ma)
    assert len(nk) == 1 and nk[0]["actor_user_id"] == admin_chot["id"] and nk[0]["reason"] == LY_DO, nk
    assert rr.status_code == 200 and await _vai(admin_chot["id"]) == VAI_MOI, (rr.status_code, rr.text)
