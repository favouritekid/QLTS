"""GĐ1b lô — VÒNG ĐỜI lô, hai phiên thật (đặc tả bản 3.6 §5.2 bước 0–2, §5.3, §5.6, §5.7; §9 "[MỚI 3.3] Vòng đời lô",
"[MỚI 3.5] Chốt lô theo trạng thái + xem trước đồng thời", "[MỚI 3.6]", "[MỚI 3.4] Kiểm lại quyền dưới khoá", "Dọn không đụng
lô đang chạy"; ma trận T1–T6, T13 của báo cáo agent luồng lô).

Mỗi người thao tác một ``AsyncClient`` riêng; điểm dừng bọc hàm của kho / dịch vụ; "bị chặn" đo bằng ``pg_blocking_pids``
từ kết nối khác, đúng PID của từng yêu cầu (nhãn A / B qua ``ContextVar``).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal
from tests.api.test_gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    Diem,
    PidTheoNhan,
    bi_chan_boi,
    boc,
    cho_khoa_vang,
    dang_nhap,
    dn,
    dong_lo,
    dong_muc,
    goi,
    lo_config,
    lo_routers,
    sql,
    tao_ho_so_cho_xet,
    xac_nhan,
)
from app.core.advisory_lock_keys import batch_lock_key

pytestmark = pytest.mark.asyncio


async def _ho_so(client, admin_h, officer, cfg, n, tien_to="vd"):
    return [await tao_ho_so_cho_xet(client, admin_h, officer, cfg, f"{tien_to}{i}", giay_nhan="AB") for i in range(n)]


async def _xem_truoc(client, user, ids):
    h = await dn(client, user)
    r = await client.post(f"{BULK}/preview", headers=h, json={"profile_ids": ids})
    assert r.status_code == 201, r.text
    return r.json()["batch_id"]


def _bam(muc) -> str:
    return hashlib.sha256(json.dumps(sorted((m["document_row_id"], m["result"], m["reason_code"]) for m in muc),
                                     default=str).encode()).hexdigest()


async def _so_previewed(uid: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                text("SELECT count(*) FROM document_bulk_batch WHERE actor_user_id = :u AND status = 'previewed'"), {"u": uid}
            )
        ).scalar_one()


# ---------------------------------------------------------------------------------------------------- starting / not_started
async def test_execute_giu_khoa_chua_commit_processing_thi_tra_starting_va_chot_409_batch_running(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """[MỚI 3.6]: pha ``starting`` (execute đã giữ khoá, dòng vẫn ``previewed``) ⇒ GET ``starting``; finalize ⇒ 409
    ``BATCH_RUNNING`` (không phải ``BATCH_NOT_STARTED``), không ghi gì; thả ⇒ ``completed``."""
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    diem = Diem()
    boc(monkeypatch, repo, "lock_batch_row", diem, truoc=True)  # ĐÃ giữ khoá lô, CHƯA khoá dòng / commit ``processing``
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        rg = await cb.get(f"{BULK}/{ma}", headers=hb)
        rf = await cb.post(f"{BULK}/{ma}/finalize", headers=hb, json={})
        trong_khi = await dong_lo(ma)
        diem.di.set()
        ra = await a
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert rg.status_code == 200 and rg.json()["status"] == "starting" and rg.json()["can_finalize"] is False, rg.text
    assert rf.status_code == 409 and rf.json()["error_code"] == "BATCH_RUNNING", rf.text
    assert trong_khi["status"] == "previewed" and trong_khi["finalized_at"] is None
    assert ra.status_code == 200 and ra.json()["status"] == "completed", ra.text


async def test_huy_execute_o_pha_starting_thi_not_started_roi_chay_lai_cung_ma(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    diem = Diem()
    boc(monkeypatch, repo, "lock_batch_row", diem, truoc=True)  # ĐÃ giữ khoá lô, CHƯA khoá dòng / commit ``processing``
    ca, ha = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        while not a.done():
            a.cancel()
            await asyncio.sleep(0.01)
    finally:
        diem.di.set()
        await ca.aclose()
    assert await cho_khoa_vang(batch_lock_key(uuid.UUID(ma)), 2.0)
    h = await dn(client, manager_user_in_db)
    r = await client.get(f"{BULK}/{ma}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "not_started" and r.json()["can_execute"] is True, r.text
    r = await client.post(f"{BULK}/{ma}/execute", headers=h, json=await xac_nhan(ma))
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text


# ---------------------------------------------------------------------------------------------------- F372 — GET đọc lại
async def test_tra_lo_thay_processing_roi_nguoi_chay_xong_va_nha_thi_tra_completed(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.repositories import document_bulk_repository as repo
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    diem_a = Diem()
    boc(monkeypatch, svc, "_commit_profile", diem_a)
    diem_b = Diem()
    boc(monkeypatch, repo, "batch_lock_held", diem_b, truoc=True)  # GET đã đọc ``processing``, dừng TRƯỚC khi hỏi khoá
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem_a.toi.wait(), 30)
        b = asyncio.create_task(cb.get(f"{BULK}/{ma}", headers=hb))
        await asyncio.wait_for(diem_b.toi.wait(), 30)
        diem_a.di.set()
        ra = await a  # người chạy commit ``completed`` RỒI nhả khoá
        diem_b.di.set()
        rb = await b
    finally:
        diem_a.di.set()
        diem_b.di.set()
        await ca.aclose()
        await cb.aclose()
    assert ra.status_code == 200 and ra.json()["status"] == "completed", ra.text
    assert rb.status_code == 200 and rb.json()["status"] == "completed", rb.text


async def test_loi_truy_van_pg_locks_thi_unknown_va_khong_cho_chot(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)

    async def hong(*a, **kw):
        raise RuntimeError("pg_locks lỗi")

    monkeypatch.setattr(repo, "batch_lock_held", hong)
    h = await dn(client, manager_user_in_db)
    r = await client.get(f"{BULK}/{ma}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unknown" and r.json()["can_finalize"] is False


# ---------------------------------------------------------------------------------------------------- finalize ba trạng thái
async def test_chot_lo_previewed_khong_ai_giu_khoa_409_batch_not_started(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    truoc = _bam(await dong_muc(ma))
    h = await dn(client, manager_user_in_db)
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
    assert r.status_code == 409 and r.json()["error_code"] == "BATCH_NOT_STARTED", r.text
    assert (await dong_lo(ma))["status"] == "previewed" and _bam(await dong_muc(ma)) == truoc


async def test_chot_lo_da_xong_tra_finalized_now_false_khong_doi_dong_ket_qua(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    h = await dn(client, manager_user_in_db)
    assert (await client.post(f"{BULK}/{ma}/execute", headers=h, json=await xac_nhan(ma))).status_code == 200
    truoc = _bam(await dong_muc(ma))
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
    assert r.status_code == 200 and r.json()["finalized_now"] is False and r.json()["batch"]["status"] == "completed"
    assert _bam(await dong_muc(ma)) == truoc and (await dong_lo(ma))["finalized_at"] is None


async def test_chot_lo_processing_mat_khoa_thi_interrupted_luu_ben_nguoi_va_luc_chot(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """T18: người chạy chết sau hồ sơ 1 (dòng ``processing``, không ai giữ khoá)."""
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    await sql(
        "UPDATE document_bulk_batch_item SET result = 'recorded', updated_at = now() WHERE batch_id = :b AND profile_id = :p",
        b=ma, p=ps[0]["id"],
    )
    h = await dn(client, manager_user_in_db)
    r = await client.get(f"{BULK}/{ma}", headers=h)
    assert r.json()["status"] == "interrupted_unfinalized" and r.json()["can_finalize"] is True, r.text
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
    assert r.status_code == 200 and r.json()["finalized_now"] is True, r.text
    lo = await dong_lo(ma)
    assert lo["status"] == "interrupted" and lo["finalized_by_user_id"] == manager_user_in_db["id"] and lo["finalized_at"]
    muc = {(m["profile_id"], m["result"]) for m in await dong_muc(ma)}
    assert muc == {(ps[0]["id"], "recorded"), (ps[1]["id"], "not_processed")}


async def test_admin_chot_lo_nguoi_khac_phai_co_ly_do_va_ghi_nhat_ky(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    h = await dn(client, admin_user_in_db)
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
    assert r.status_code == 422 and r.json()["error_code"] == "REASON_REQUIRED", r.text
    assert (await dong_lo(ma))["status"] == "processing"
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={"reason": "Quản lý nghỉ phép, lô treo"})
    assert r.status_code == 200 and r.json()["finalized_now"] is True, r.text
    lo = await dong_lo(ma)
    assert lo["finalized_by_user_id"] == admin_user_in_db["id"] and lo["finalize_reason"] == "Quản lý nghỉ phép, lô treo"
    async with AsyncSessionLocal() as s:
        nk = (
            await s.execute(
                text(
                    "SELECT actor_user_id, reason, new_value FROM entity_audit_log"
                    " WHERE entity_type = 'document_bulk_batch' AND action = 'finalize_by_admin'"
                )
            )
        ).mappings().all()
    assert len(nk) == 1 and nk[0]["actor_user_id"] == admin_user_in_db["id"] and nk[0]["new_value"]["batch_id"] == ma


# ---------------------------------------------------------------------------------------------------- execute đồng thời
async def test_hai_execute_dong_thoi_dung_mot_chay_mot_409_batch_running(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    diem = Diem()
    boc(monkeypatch, svc, "_commit_profile", diem)
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        t0 = time.monotonic()
        rb = await cb.post(f"{BULK}/{ma}/execute", headers=hb, json=await xac_nhan(ma))
        tg = time.monotonic() - t0
        diem.di.set()
        ra = await a
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert rb.status_code == 409 and rb.json()["error_code"] == "BATCH_RUNNING" and tg < 1.0, (rb.text, tg)
    assert ra.status_code == 200 and ra.json()["status"] == "completed", ra.text
    async with AsyncSessionLocal() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM document_audit_log WHERE action = 'verified' AND profile_document_id = :d"),
                {"d": ps[0]["docs"]["A"].id},
            )
        ).scalar_one()
    assert n == 1


@pytest.mark.parametrize("bien", ["xoa_dong", "doi_nguoi_tao"])
async def test_doi_dong_lo_giua_buoc_0_va_buoc_2_thi_404_preview_gone(
    bien, client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    diem = Diem()
    boc(monkeypatch, repo, "lock_batch_row", diem, truoc=True)  # ĐÃ giữ khoá lô, CHƯA khoá dòng / commit ``processing``
    ca, ha = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        if bien == "xoa_dong":
            await sql("DELETE FROM document_bulk_batch WHERE batch_id = :b", b=ma)
        else:
            await sql("UPDATE document_bulk_batch SET actor_user_id = :u WHERE batch_id = :b", u=admin_user_in_db["id"], b=ma)
        diem.di.set()
        r = await a
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 404 and r.json()["error_code"] == "PREVIEW_GONE", r.text
    lo = await dong_lo(ma)
    assert lo is None or lo["status"] == "previewed"
    assert await cho_khoa_vang(batch_lock_key(uuid.UUID(ma)), 2.0)


# ---------------------------------------------------------------------------------------------------- xem trước đồng thời
async def test_hai_xem_truoc_dong_thoi_cung_nguoi_chay_lan_luot_toi_da_ba_ban(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """[MỚI 3.6] kịch bản chạy được: đã có 2 bản ``previewed``; A dừng NGAY SAU bước dọn (đang giữ khoá theo người) ⇒ B
    cùng người BỊ A CHẶN (``pg_blocking_pids``); thả ⇒ cả hai xong, ≤ 3 bản."""
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    for _ in range(2):
        await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    diem = Diem()
    boc(monkeypatch, repo, "cleanup_previews", diem)
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(manager_user_in_db)
    than = {"profile_ids": [ps[0]["id"]]}
    try:
        with PidTheoNhan() as ghi:
            a = asyncio.create_task(goi("A", lambda: ca.post(f"{BULK}/preview", headers=ha, json=than)))
            await asyncio.wait_for(diem.toi.wait(), 30)
            b = asyncio.create_task(goi("B", lambda: cb.post(f"{BULK}/preview", headers=hb, json=than)))
            tt = await bi_chan_boi(b, ghi)
            diem.di.set()
            ra, rb = await asyncio.gather(a, b)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"B phải CHỜ khoá theo người mà A giữ ({tt})"
    assert ra.status_code == 201 and rb.status_code == 201, (ra.text, rb.text)
    assert await _so_previewed(manager_user_in_db["id"]) <= 3


async def test_hai_nguoi_khac_nhau_xem_truoc_khong_chan_nhau(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config,
    lo_routers,
):
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    diem = Diem()
    boc(monkeypatch, repo, "cleanup_previews", diem)
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(admin_user_in_db)
    than = {"profile_ids": [ps[0]["id"]]}
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/preview", headers=ha, json=than))
        await asyncio.wait_for(diem.toi.wait(), 30)
        rb = await asyncio.wait_for(cb.post(f"{BULK}/preview", headers=hb, json=than), 10)
        diem.di.set()
        ra = await a
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert rb.status_code == 201 and ra.status_code == 201, (ra.text, rb.text)


async def test_don_ban_xem_truoc_khong_dung_lo_dang_bi_execute_giu(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """[MỚI 3.4]: X (cũ nhất) đang bị ``execute`` giữ khoá lô (chưa khoá dòng) ⇒ xem trước lần thứ 4 của CÙNG người không xoá
    X (``pg_try_advisory_xact_lock`` = false) mà xoá bản cũ kế tiếp; A chạy X bình thường."""
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    x = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    await sql("UPDATE document_bulk_batch SET created_at = now() - interval '1 hour' WHERE batch_id = :b", b=x)
    y = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    z = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    diem = Diem()
    boc(monkeypatch, repo, "lock_batch_row", diem, truoc=True)  # ĐÃ giữ khoá lô, CHƯA khoá dòng / commit ``processing``
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{x}/execute", headers=ha, json=await xac_nhan(x)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        rb = await cb.post(f"{BULK}/preview", headers=hb, json={"profile_ids": [ps[0]["id"]]})
        diem.di.set()
        ra = await a
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert rb.status_code == 201, rb.text
    assert await dong_lo(y) is None and await dong_lo(z) is not None
    assert ra.status_code == 200 and ra.json()["status"] == "completed", ra.text


# ---------------------------------------------------------------------------------------------------- cờ máy chủ B4 (hợp đồng bản 5)
async def _lo_mat_khoa(client, user, profile_id) -> str:
    """Lô ``processing`` không ai giữ khoá (người chạy đã chết) ⇒ ``interrupted_unfinalized``, chốt được."""
    ma = await _xem_truoc(client, user, [profile_id])
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    return ma


async def test_co_chot_can_ly_do_true_khi_admin_khac_nguoi_tao_va_chot_khong_ly_do_that_su_422(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """``finalize_requires_reason`` = true ⇔ máy chủ THẬT SỰ đòi lý do (422 ``REASON_REQUIRED``, không ghi gì)."""
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _lo_mat_khoa(client, manager_user_in_db, ps[0]["id"])
    h = await dn(client, admin_user_in_db)
    v = (await client.get(f"{BULK}/{ma}", headers=h)).json()
    assert (v["status"], v["can_finalize"], v["finalize_requires_reason"]) == ("interrupted_unfinalized", True, True), v
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
    assert r.status_code == 422 and r.json()["error_code"] == "REASON_REQUIRED", r.text
    assert (await dong_lo(ma))["status"] == "processing"


async def test_co_chot_can_ly_do_false_voi_nguoi_tao_ke_ca_admin_va_chot_khong_ly_do_200(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """Người tạo (Quản lý, hoặc Admin tự tạo) ⇒ ``finalize_requires_reason`` = false ⇔ chốt KHÔNG lý do được 200."""
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    for nguoi, p in ((manager_user_in_db, ps[0]), (admin_user_in_db, ps[1])):
        ma = await _lo_mat_khoa(client, nguoi, p["id"])
        h = await dn(client, nguoi)
        v = (await client.get(f"{BULK}/{ma}", headers=h)).json()
        assert (v["can_finalize"], v["finalize_requires_reason"]) == (True, False), (nguoi["username"], v)
        r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
        assert r.status_code == 200 and r.json()["finalized_now"] is True, (nguoi["username"], r.text)
        assert r.json()["batch"]["finalize_requires_reason"] is False


async def test_co_chot_can_ly_do_false_khi_lo_khong_chot_duoc_ke_ca_voi_admin_khac_nguoi_tao(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """Vế "VÀ ``can_finalize``": lô chưa chạy / đã xong ⇒ không chốt được ⇒ cờ false, kể cả với Admin khác người tạo."""
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    chua_chay = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    da_xong = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    h = await dn(client, manager_user_in_db)
    assert (await client.post(f"{BULK}/{da_xong}/execute", headers=h, json=await xac_nhan(da_xong))).status_code == 200
    h = await dn(client, admin_user_in_db)
    for ma, st in ((chua_chay, "not_started"), (da_xong, "completed")):
        v = (await client.get(f"{BULK}/{ma}", headers=h)).json()
        assert (v["status"], v["can_finalize"], v["finalize_requires_reason"]) == (st, False, False), v
