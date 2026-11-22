"""GĐ1b PR-B lượt 2 — cổng lô CHÉO phải kiểm ĐÚNG ĐƠN VỊ của lô + đúng thao tác (Codex lượt 1 PR-B, điểm chặn 1; owner câu
10 và câu 9, 21-11).

Cán bộ chéo còn quyền ở đơn vị B nhưng hết quyền ở đơn vị A (đơn vị của lô) ⇒ tra / chạy / chốt lô của A trả CÙNG THÂN 404
như lô không tồn tại (so byte), lô chưa chạy vẫn ``previewed``, lô ``processing`` không bị chốt; danh sách lô chéo không liệt
kê lô của A. Còn quyền KHÁC đúng đơn vị A mà quyền của chính lô đã mất ⇒ chạy lô 409 ``actor_not_authorized`` (câu 9 — làm
mới / xem trước lại), lô vẫn ``previewed``. Quyền bị thu hồi SAU cổng vào, TRƯỚC bước khoá của lệnh chạy ⇒ 404, lô vẫn
``previewed`` (kiểm DƯỚI khoá, trước khi đổi ``processing``). CSDL đọc từ phiên riêng.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import document_bulk_verify_service as bulk_service
from tests.api.gd1b_cheo_tro_giup import (  # noqa: F401
    LO_KHONG_TON_TAI,
    THAN_404,
    can_bo_cheo,
    cap,
    ho_so,
    mot,
)
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    CROSS,
    Diem,
    boc,
    dang_nhap,
    dn,
    lo_config,
    lo_routers,
    sql,
    xac_nhan,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _thu_hoi(client, admin, gid, ly_do="Đổi phân công"):
    h = await dn(client, admin)
    r = await client.post(f"{CROSS}/grants/{gid}/revoke", headers=h, json={"reason": ly_do})
    assert r.status_code == 200, r.text


async def _trang_thai_lo(ma):
    return await mot("SELECT status FROM document_bulk_batch WHERE batch_id = :b", b=ma)


async def _xem_truoc(client, can_bo, ids, gid):
    h = await dn(client, can_bo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": ids, "grant_id": gid})
    assert r.status_code == 201, r.text
    return r.json()["batch_id"]


async def test_con_quyen_don_vi_khac_khong_tra_chay_chot_duoc_lo_cua_don_vi_da_het_quyen(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, seed_other_unit, lo_config,
    lo_routers,
):
    ps = await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2, tien_to="dv1")
    g_a = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    await cap(client, admin_user_in_db, can_bo_cheo["id"], seed_other_unit["unit_id"], verify=True)  # còn quyền ở B
    lo_chua_chay = await _xem_truoc(client, can_bo_cheo, [ps[0]["id"]], g_a)
    lo_dang_chay = await _xem_truoc(client, can_bo_cheo, [ps[1]["id"]], g_a)
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=lo_dang_chay)
    h = await dn(client, can_bo_cheo)
    # Đối chứng: khi còn quyền ở A, tra được lô và lô có trong danh sách.
    r = await client.get(f"{CROSS}/bulk-verify/{lo_chua_chay}", headers=h)
    assert r.status_code == 200 and r.json()["items"], r.text
    assert {x["batch_id"] for x in (await client.get(f"{CROSS}/bulk-verify", headers=h)).json()["items"]} == {
        lo_chua_chay, lo_dang_chay,
    }
    await _thu_hoi(client, admin_user_in_db, g_a)
    h = await dn(client, can_bo_cheo)
    moc = await client.get(f"{CROSS}/bulk-verify/{LO_KHONG_TON_TAI}", headers=h)
    assert moc.status_code == 404 and moc.json() == THAN_404, moc.text
    for pt, duong, than in (
        ("GET", f"{CROSS}/bulk-verify/{lo_chua_chay}", None),
        ("POST", f"{CROSS}/bulk-verify/{lo_chua_chay}/execute", await xac_nhan(lo_chua_chay)),
        ("POST", f"{CROSS}/bulk-verify/{lo_chua_chay}/finalize", {}),
        ("GET", f"{CROSS}/bulk-verify/{lo_dang_chay}", None),
        ("POST", f"{CROSS}/bulk-verify/{lo_dang_chay}/finalize", {}),
    ):
        r = await (client.get(duong, headers=h) if pt == "GET" else client.post(duong, headers=h, json=than))
        assert r.status_code == 404 and r.content == moc.content, (duong, r.status_code, r.text)
    assert await _trang_thai_lo(lo_chua_chay) == "previewed"
    assert await _trang_thai_lo(lo_dang_chay) == "processing"
    assert await mot("SELECT finalized_at FROM document_bulk_batch WHERE batch_id = :b", b=lo_dang_chay) is None
    r = await client.get(f"{CROSS}/bulk-verify", headers=h)
    assert r.status_code == 200 and r.json()["items"] == [], r.text


async def test_quyen_cua_lo_mat_nhung_con_quyen_khac_dung_don_vi_thi_chay_lo_409_lo_van_previewed(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Owner câu 9: còn quyền KHÁC hợp lệ cho đúng thao tác + đúng đơn vị ⇒ 409, máy chủ không tự chọn quyền thay thế."""
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="dv2"))[0]
    g_lo = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True, ly_do="Quyền thứ hai")
    ma = await _xem_truoc(client, can_bo_cheo, [p["id"]], g_lo)
    await _thu_hoi(client, admin_user_in_db, g_lo)
    h = await dn(client, can_bo_cheo)
    assert (await client.get(f"{CROSS}/bulk-verify/{ma}", headers=h)).status_code == 200
    r = await client.post(f"{CROSS}/bulk-verify/{ma}/execute", headers=h, json=await xac_nhan(ma))
    assert r.status_code == 409 and r.json()["error_code"] == "ACTOR_NOT_AUTHORIZED", r.text
    assert await _trang_thai_lo(ma) == "previewed"


async def test_thu_hoi_sau_cong_vao_truoc_buoc_khoa_cua_lenh_chay_thi_404_lo_van_previewed(
    client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, seed_other_unit,
    lo_config, lo_routers,
):
    """Cổng vào đã cho qua (còn quyền ở A); quyền A bị thu hồi + commit TRƯỚC bước 2 của lệnh chạy ⇒ bước 2 kiểm DƯỚI khoá ⇒
    404 cùng thân, lô KHÔNG sang ``processing``."""
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="dv3"))[0]
    g_a = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    await cap(client, admin_user_in_db, can_bo_cheo["id"], seed_other_unit["unit_id"], verify=True)
    ma = await _xem_truoc(client, can_bo_cheo, [p["id"]], g_a)
    than = await xac_nhan(ma)
    diem = Diem()
    boc(monkeypatch, bulk_service, "execute_batch", diem, truoc=True)  # SAU cổng vào (deps), TRƯỚC mọi khoá của lệnh chạy
    cb, hb = await dang_nhap(can_bo_cheo)
    try:
        viec = asyncio.create_task(cb.post(f"{CROSS}/bulk-verify/{ma}/execute", headers=hb, json=than))
        await asyncio.wait_for(diem.toi.wait(), 30)
        await _thu_hoi(client, admin_user_in_db, g_a)
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await cb.aclose()
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    assert await _trang_thai_lo(ma) == "previewed"
    assert await mot("SELECT count(*) FROM document_bulk_batch_item WHERE batch_id = :b AND result IS NOT NULL", b=ma) == 0
