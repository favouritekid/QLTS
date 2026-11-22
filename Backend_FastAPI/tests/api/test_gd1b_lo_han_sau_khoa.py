"""GĐ1b PR-B lượt 4 — hạn tính bằng đồng hồ CSDL SAU khi có khoá (Codex lượt 3 PR-B, điểm chặn 4 + rà cùng khuôn).

Hạn đặt TRONG câu ``SELECT … FOR SHARE / FOR UPDATE`` có thể được PostgreSQL tính TRƯỚC lúc chờ khoá và trả lại nguyên giá
trị ấy khi giao dịch giữ khoá nhả mà KHÔNG sửa dòng. Hai ca, mỗi ca một phiên A giữ khoá dòng (``KhoaHo``), phiên thứ ba xác
nhận yêu cầu B bị A chặn (``pg_blocking_pids``), hạn trôi qua trong lúc chờ, A rollback (không sửa dòng):

- chốt lô CHÉO chờ khoá dòng quyền đang cho phép chốt ⇒ quyền hết hạn trong lúc chờ ⇒ 404 cùng thân, lô giữ nguyên;
- chạy lô (THƯỜNG) chờ khoá dòng lô ⇒ bản xem trước hết hạn trong lúc chờ ⇒ 409 ``PREVIEW_EXPIRED``, lô vẫn ``previewed``;
- Codex lượt 4 C1b: chạy lô CHÉO đã khoá dòng lô (bản xem trước còn hạn), rồi chờ khoá dòng QUYỀN ⇒ bản xem trước hết hạn
  trong lúc chờ (quyền vẫn hợp lệ) ⇒ 409 ``PREVIEW_EXPIRED``, lô KHÔNG sang ``processing``.

CSDL đọc từ phiên riêng.
"""
from __future__ import annotations

import asyncio

import pytest

from tests.api.gd1b_cheo_tro_giup import THAN_404, KhoaHo, bi_chan_boi_pid, can_bo_cheo, cap, hang, ho_so, mot  # noqa: F401
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    CROSS,
    PidTheoNhan,
    dang_nhap,
    dn,
    goi,
    lo_config,
    lo_routers,
    sql,
    xac_nhan,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _cho_het_han(bang: str, cot_khoa: str, gia_tri):
    for _ in range(150):
        if (await hang(f"SELECT clock_timestamp() > expires_at AS het FROM {bang} WHERE {cot_khoa} = :v", v=gia_tri))[0]["het"]:
            return
        await asyncio.sleep(0.1)
    raise AssertionError("hạn không trôi qua")


async def test_chot_lo_cheo_quyen_het_han_trong_luc_cho_khoa_dong_quyen_thi_404_lo_giu_nguyen(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="l4hq"))[0]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"]], "grant_id": gid})
    assert r.status_code == 201, r.text
    ma = r.json()["batch_id"]
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    cb, hb = await dang_nhap(can_bo_cheo)
    await sql(
        "UPDATE document_cross_review_grant SET expires_at = clock_timestamp() + interval '5 seconds' WHERE id = :g", g=gid
    )
    a = await KhoaHo("SELECT id FROM document_cross_review_grant WHERE id = :g FOR UPDATE", g=gid).giu()
    try:
        with PidTheoNhan() as ghi:
            viec = asyncio.create_task(goi("B", lambda: cb.post(f"{CROSS}/bulk-verify/{ma}/finalize", headers=hb, json={})))
            assert await bi_chan_boi_pid(viec, ghi, "B", [a.pid]) == "chan", "chốt lô phải chờ khoá dòng quyền (A giữ)"
            await _cho_het_han("document_cross_review_grant", "id", gid)
            assert not viec.done(), "lệnh chốt phải còn chờ khoá tới lúc quyền đã hết hạn"
            await a.tha()  # nhả mà KHÔNG sửa dòng
            r = await asyncio.wait_for(viec, 30)
    finally:
        await a.tha()
        await cb.aclose()
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    assert await mot("SELECT status FROM document_bulk_batch WHERE batch_id = :b", b=ma) == "processing"
    assert await mot("SELECT finalized_at FROM document_bulk_batch WHERE batch_id = :b", b=ma) is None


async def test_chay_lo_ban_xem_truoc_het_han_trong_luc_cho_khoa_dong_lo_thi_409_lo_van_previewed(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="l4hl"))[0]
    h = await dn(client, manager_user_in_db)
    r = await client.post(f"{BULK}/preview", headers=h, json={"profile_ids": [p["id"]]})
    assert r.status_code == 201, r.text
    ma = r.json()["batch_id"]
    than = await xac_nhan(ma)
    cm, hm = await dang_nhap(manager_user_in_db)
    await sql(
        "UPDATE document_bulk_batch SET expires_at = clock_timestamp() + interval '5 seconds' WHERE batch_id = :b", b=ma
    )
    a = await KhoaHo("SELECT batch_id FROM document_bulk_batch WHERE batch_id = :b FOR UPDATE", b=ma).giu()
    try:
        with PidTheoNhan() as ghi:
            viec = asyncio.create_task(goi("B", lambda: cm.post(f"{BULK}/{ma}/execute", headers=hm, json=than)))
            assert await bi_chan_boi_pid(viec, ghi, "B", [a.pid]) == "chan", "chạy lô phải chờ khoá dòng lô (A giữ)"
            await _cho_het_han("document_bulk_batch", "batch_id", ma)
            assert not viec.done(), "lệnh chạy phải còn chờ khoá tới lúc bản xem trước đã hết hạn"
            await a.tha()  # nhả mà KHÔNG sửa dòng
            r = await asyncio.wait_for(viec, 30)
    finally:
        await a.tha()
        await cm.aclose()
    assert r.status_code == 409 and r.json()["error_code"] == "PREVIEW_EXPIRED", r.text
    assert await mot("SELECT status FROM document_bulk_batch WHERE batch_id = :b", b=ma) == "previewed"
    assert await mot("SELECT count(*) FROM document_bulk_batch_item WHERE batch_id = :b AND result IS NOT NULL", b=ma) == 0


async def test_chay_lo_cheo_ban_xem_truoc_het_han_trong_luc_cho_khoa_dong_quyen_thi_409_khong_sang_processing(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="l4hg"))[0]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"]], "grant_id": gid})
    assert r.status_code == 201, r.text
    ma = r.json()["batch_id"]
    than = await xac_nhan(ma)
    cb, hb = await dang_nhap(can_bo_cheo)
    await sql(
        "UPDATE document_bulk_batch SET expires_at = clock_timestamp() + interval '5 seconds' WHERE batch_id = :b", b=ma
    )
    a = await KhoaHo("SELECT id FROM document_cross_review_grant WHERE id = :g FOR UPDATE", g=gid).giu()
    try:
        with PidTheoNhan() as ghi:
            viec = asyncio.create_task(goi("B", lambda: cb.post(f"{CROSS}/bulk-verify/{ma}/execute", headers=hb, json=than)))
            assert await bi_chan_boi_pid(viec, ghi, "B", [a.pid]) == "chan", "chạy lô phải chờ khoá dòng quyền (A giữ)"
            await _cho_het_han("document_bulk_batch", "batch_id", ma)
            assert not viec.done(), "lệnh chạy phải còn chờ khoá quyền tới lúc bản xem trước đã hết hạn"
            await a.tha()  # nhả mà KHÔNG sửa dòng (quyền vẫn còn hạn)
            r = await asyncio.wait_for(viec, 30)
    finally:
        await a.tha()
        await cb.aclose()
    assert r.status_code == 409 and r.json()["error_code"] == "PREVIEW_EXPIRED", r.text
    assert await mot("SELECT status FROM document_bulk_batch WHERE batch_id = :b", b=ma) == "previewed"
    assert await mot("SELECT count(*) FROM document_bulk_batch_item WHERE batch_id = :b AND result IS NOT NULL", b=ma) == 0
