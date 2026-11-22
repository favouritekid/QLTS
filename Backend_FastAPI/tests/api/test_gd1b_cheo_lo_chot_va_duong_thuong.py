"""GĐ1b PR-B lượt 3 — lô CHÉO: đường lô thường + chốt lô chéo (Codex lượt 2 PR-B, điểm chặn 1 và 2; owner câu 10, X3).

Điểm chặn 1: Cán bộ tạo lô chéo rồi đổi vai sang Quản lý (quyền chéo đã tự thu hồi đúng). Đường lô THƯỜNG nhận Quản lý và
từng cho qua "người tạo" ở mọi chế độ lô ⇒ lộ mã hồ sơ / mã giấy của lô chéo cũ và chốt được lô gián đoạn. Nay đường thường
xét ``review_mode`` LƯU trong CSDL: chi tiết / chốt ⇒ 404 cùng thân lô không tồn tại (so byte), lô không đổi; danh sách không
liệt kê lô ấy. Ngoại lệ X3: Admin vẫn xem lô chéo qua đường thường.

Điểm chặn 2: chốt lô chéo khi quyền tạo lô đã thu hồi mà còn quyền THỨ HAI cùng đơn vị — dòng được khoá phải là CHÍNH quyền
đang cho phép chốt. Hai phiên: thu hồi quyền thứ hai thắng (commit trước lúc chốt khoá nó) ⇒ 404, lô còn nguyên; chốt thắng
(đã khoá + kiểm xong) ⇒ lệnh thu hồi quyền thứ hai CHỜ tới khi chốt commit (phiên thứ ba, ``pg_blocking_pids``).

CSDL đọc từ phiên riêng.
"""
from __future__ import annotations

import asyncio

import pytest

from app.repositories import document_bulk_repository as bulk_repo
from tests.api.gd1b_cheo_tro_giup import (  # noqa: F401
    LO_KHONG_TON_TAI,
    THAN_404,
    bi_chan_boi_pid,
    can_bo_cheo,
    cap,
    ho_so,
    mot,
)
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    CROSS,
    Diem,
    PidTheoNhan,
    boc,
    dang_nhap,
    dn,
    goi,
    lo_config,
    lo_routers,
    sql,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _thu_hoi(client, admin, gid, ly_do="Đổi phân công"):
    h = await dn(client, admin)
    r = await client.post(f"{CROSS}/grants/{gid}/revoke", headers=h, json={"reason": ly_do})
    assert r.status_code == 200, r.text


async def _lo(ma):
    return (await mot("SELECT status FROM document_bulk_batch WHERE batch_id = :b", b=ma),
            await mot("SELECT finalized_at FROM document_bulk_batch WHERE batch_id = :b", b=ma))


async def _lo_cheo_gian_doan(client, admin_h, admin, officer, can_bo, cfg, tien_to):
    """Lô chéo của ``can_bo`` ở ``processing`` mà không ai giữ khoá (người chạy đã chết) ⇒ chốt được. Trả (mã lô, mã quyền)."""
    p = (await ho_so(client, admin_h, officer, cfg, tien_to=tien_to))[0]
    g = await cap(client, admin, can_bo["id"], cfg["unit_id"], verify=True)
    h = await dn(client, can_bo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"]], "grant_id": g})
    assert r.status_code == 201, r.text
    ma = r.json()["batch_id"]
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    return ma, g


async def _thanh_quan_ly(client, admin, can_bo, g):
    """Admin đổi vai Cán bộ → Quản lý (PUT thật) — quyền chéo tự thu hồi (Q4). Trả header đăng nhập của người ấy."""
    h = await dn(client, admin)
    r = await client.put(f"/api/admin/users/{can_bo['id']}", headers=h, data={"role": "manager"})
    assert r.status_code == 200, r.text
    assert await mot("SELECT revoked_at IS NOT NULL FROM document_cross_review_grant WHERE id = :g", g=g), "tiền đề Q4"
    hq = await dn(client, can_bo)
    # Tiền đề: đường lô thường MỞ với người này (Quản lý có đơn vị) — nếu không, 404 bên dưới chẳng chứng minh gì.
    r = await client.get(BULK, headers=hq)
    assert r.status_code == 200, r.text
    moc = await client.get(f"{BULK}/{LO_KHONG_TON_TAI}", headers=hq)
    assert moc.status_code == 404, moc.text
    return hq, moc


# ---------------------------------------------------------------------------------------------------- điểm chặn 1
async def test_quan_ly_von_la_can_bo_khong_chot_duoc_lo_cheo_cu_qua_duong_lo_thuong(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    ma, g = await _lo_cheo_gian_doan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, "l3chot"
    )
    hq, moc = await _thanh_quan_ly(client, admin_user_in_db, can_bo_cheo, g)
    r = await client.post(f"{BULK}/{ma}/finalize", headers=hq, json={})
    assert r.status_code == 404 and r.content == moc.content, (r.status_code, r.text)
    assert await _lo(ma) == ("processing", None)


async def test_quan_ly_von_la_can_bo_khong_xem_duoc_lo_cheo_cu_qua_duong_lo_thuong_admin_van_xem_duoc(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    ma, g = await _lo_cheo_gian_doan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, "l3xem"
    )
    hq, moc = await _thanh_quan_ly(client, admin_user_in_db, can_bo_cheo, g)
    r = await client.get(f"{BULK}/{ma}", headers=hq)
    assert r.status_code == 404 and r.content == moc.content, (r.status_code, r.text)
    # Ngoại lệ X3 giữ nguyên: Admin xem lô chéo qua đường thường.
    h = await dn(client, admin_user_in_db)
    r = await client.get(f"{BULK}/{ma}", headers=h)
    assert r.status_code == 200 and r.json()["items"], r.text


async def test_quan_ly_von_la_can_bo_khong_thay_lo_cheo_cu_trong_danh_sach_lo_thuong(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    ma, g = await _lo_cheo_gian_doan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, "l3ds"
    )
    hq, _moc = await _thanh_quan_ly(client, admin_user_in_db, can_bo_cheo, g)
    r = await client.get(BULK, headers=hq)
    assert r.status_code == 200, r.text
    assert ma not in {x["batch_id"] for x in r.json()["items"]}, r.json()
    # Admin (X3, ``scope=all``) vẫn thấy lô ấy.
    h = await dn(client, admin_user_in_db)
    r = await client.get(BULK, headers=h, params={"scope": "all"})
    assert r.status_code == 200 and ma in {x["batch_id"] for x in r.json()["items"]}, r.text


# ---------------------------------------------------------------------------------------------------- điểm chặn 2
async def _lo_cheo_con_quyen_thu_hai(client, admin_h, admin, officer, can_bo, cfg, tien_to):
    """Lô chéo gián đoạn; quyền TẠO lô đã thu hồi; còn quyền duyệt THỨ HAI cùng đơn vị. Trả (mã lô, quyền thứ hai)."""
    ma, g1 = await _lo_cheo_gian_doan(client, admin_h, admin, officer, can_bo, cfg, tien_to)
    g2 = await cap(client, admin, can_bo["id"], cfg["unit_id"], verify=True, ly_do="Quyền thứ hai")
    await _thu_hoi(client, admin, g1)
    return ma, g2


async def test_chot_lo_cheo_thu_hoi_quyen_thu_hai_thang_thi_404_lo_con_nguyen(
    client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Lệnh chốt đã qua cổng vào (còn quyền thứ hai), dừng NGAY TRƯỚC lần khoá dòng quyền đầu tiên; Admin thu hồi quyền thứ
    hai + commit; thả ⇒ khoá rồi kiểm lại CHÍNH dòng ấy ⇒ không còn cho phép ⇒ 404 cùng thân, lô vẫn ``processing``."""
    ma, g2 = await _lo_cheo_con_quyen_thu_hai(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, "l3th"
    )
    diem = Diem()
    boc(monkeypatch, bulk_repo, "lock_grant_share", diem, truoc=True)
    cb, hb = await dang_nhap(can_bo_cheo)
    try:
        viec = asyncio.create_task(cb.post(f"{CROSS}/bulk-verify/{ma}/finalize", headers=hb, json={}))
        await asyncio.wait_for(diem.toi.wait(), 30)
        await _thu_hoi(client, admin_user_in_db, g2)
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await cb.aclose()
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    assert await _lo(ma) == ("processing", None)


async def test_chot_lo_cheo_thang_thi_thu_hoi_quyen_dang_cho_phep_chot_phai_cho(
    client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Lệnh chốt (X) đã khoá + kiểm quyền, dừng TRƯỚC khi ghi. Admin thu hồi quyền thứ hai (Y) — quyền ĐANG cho phép chốt —
    phải bị CHÍNH X chặn (phiên thứ ba, ``pg_blocking_pids``). Thả X ⇒ chốt xong; Y xong SAU đó."""
    ma, g2 = await _lo_cheo_con_quyen_thu_hai(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, "l3ct"
    )
    diem = Diem()
    boc(monkeypatch, bulk_repo, "mark_remaining_not_processed", diem, truoc=True)
    cb, hb = await dang_nhap(can_bo_cheo)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        with PidTheoNhan() as ghi:
            viec_x = asyncio.create_task(goi("X", lambda: cb.post(f"{CROSS}/bulk-verify/{ma}/finalize", headers=hb, json={})))
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_x = set(ghi.pid.get("X", ()))
            assert pid_x
            viec_y = asyncio.create_task(goi("Y", lambda: ca.post(
                f"{CROSS}/grants/{g2}/revoke", headers=ha, json={"reason": "Đổi phân công"})))
            assert await bi_chan_boi_pid(viec_y, ghi, "Y", pid_x) == "chan", (
                "thu hồi quyền đang cho phép chốt phải CHỜ lệnh chốt commit"
            )
            diem.di.set()
            r_x = await asyncio.wait_for(viec_x, 30)
            r_y = await asyncio.wait_for(viec_y, 30)
    finally:
        diem.di.set()
        await cb.aclose()
        await ca.aclose()
    assert r_x.status_code == 200 and r_x.json()["finalized_now"] is True, r_x.text
    assert r_y.status_code == 200, r_y.text
    trang_thai, luc_chot = await _lo(ma)
    assert trang_thai == "interrupted" and luc_chot is not None
