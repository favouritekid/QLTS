"""GĐ1b lô — danh sách lô của tôi (X3; đặc tả bản 3.6 §5.8, §9 "X3"): cửa sổ hiển thị 30 ngày, thứ tự ổn định
``created_at DESC, batch_id DESC``, con trỏ 20 / trang, không id hồ sơ / giấy / tên; người khác không thấy; ``scope=all`` chỉ
Admin.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal
from tests.api.test_gd1b_lo_tro_giup import BULK, dn, lo_routers  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _chen_lo(actor_id: int, phut_truoc: float, *, status: str = "completed") -> str:
    """Dòng lô ĐÃ KẾT THÚC chèn thẳng (không cần hồ sơ thật) + một dòng mục."""
    ma = uuid.uuid4()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO document_bulk_batch (batch_id, actor_user_id, review_mode, filter_json, payload_sha256,"
                    " created_at, expires_at, started_at, finished_at, status)"
                    " VALUES (:b, :u, 'batch', '{}'::jsonb, :h, now() - make_interval(secs => :s),"
                    " now() - make_interval(secs => :s) + interval '30 minutes', now() - make_interval(secs => :s),"
                    " now() - make_interval(secs => :s), :st)"
                ),
                {"b": str(ma), "u": actor_id, "h": "0" * 64, "s": float(phut_truoc * 60), "st": status},
            )
            await s.execute(
                text(
                    "INSERT INTO document_bulk_batch_item (batch_id, document_row_id, profile_id, expected_row_version,"
                    " result) VALUES (:b, 1, 1, 1, 'recorded')"
                ),
                {"b": str(ma)},
            )
    return str(ma)


async def test_danh_sach_lo_cua_toi_on_dinh_qua_hai_trang_trong_cua_so_30_ngay(
    client, admin_user_in_db, manager_user_in_db, lo_routers
):
    mgr = manager_user_in_db["id"]
    cua_toi = [await _chen_lo(mgr, phut) for phut in range(25)]  # phút 0 = mới nhất
    cu = await _chen_lo(mgr, 31 * 24 * 60)  # ngoài cửa sổ hiển thị
    cua_admin = await _chen_lo(admin_user_in_db["id"], 1)
    h = await dn(client, manager_user_in_db)
    r1 = await client.get(BULK, headers=h)
    assert r1.status_code == 200, r1.text
    t1 = r1.json()
    assert len(t1["items"]) == 20 and t1["next_cursor"]
    r2 = await client.get(BULK, headers=h, params={"cursor": t1["next_cursor"]})
    t2 = r2.json()
    assert len(t2["items"]) == 5 and t2["next_cursor"] is None
    thay = [x["batch_id"] for x in t1["items"] + t2["items"]]
    assert thay == cua_toi, "thứ tự created_at DESC, không trùng, không sót qua hai trang"
    assert cu not in thay and cua_admin not in thay
    for x in t1["items"]:
        assert set(x) == {"batch_id", "status", "created_at", "started_at", "finished_at", "profile_count", "counts"}
        assert x["status"] == "completed" and x["profile_count"] == 1 and x["counts"]["recorded"] == 1
    assert "document_row_id" not in r1.text and "profile_id" not in r1.text


async def test_cua_so_hien_thi_khong_phai_han_luu_lo_cu_van_tra_bang_ma(
    client, manager_user_in_db, lo_routers
):
    cu = await _chen_lo(manager_user_in_db["id"], 31 * 24 * 60)
    h = await dn(client, manager_user_in_db)
    r = await client.get(f"{BULK}/{cu}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text


async def test_xem_tat_ca_chi_admin(client, admin_user_in_db, manager_user_in_db, lo_routers):
    cua_mgr = await _chen_lo(manager_user_in_db["id"], 2)
    h = await dn(client, manager_user_in_db)
    r = await client.get(BULK, headers=h, params={"scope": "all"})
    assert r.status_code == 403, r.text
    h = await dn(client, admin_user_in_db)
    r = await client.get(BULK, headers=h, params={"scope": "all"})
    assert r.status_code == 200 and cua_mgr in [x["batch_id"] for x in r.json()["items"]], r.text
    r = await client.get(BULK, headers=h)
    assert cua_mgr not in [x["batch_id"] for x in r.json()["items"]]


async def test_con_tro_hong_thi_400(client, manager_user_in_db, lo_routers):
    h = await dn(client, manager_user_in_db)
    r = await client.get(BULK, headers=h, params={"cursor": "khong-phai-con-tro"})
    assert r.status_code == 400, r.text
