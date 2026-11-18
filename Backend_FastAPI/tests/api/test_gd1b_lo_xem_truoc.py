"""GĐ1b lô — XEM TRƯỚC tạo lô (đặc tả bản 3.6 §5.2; §9 "Lô", "Vòng đời lô — xem trước tạo lô", "[MỚI 3.4] giới hạn bản
xem trước", "[MỚI 3.5] TOO_MANY_PREVIEWS"). Mỗi ca kiểm MỘT bất biến; biến thể phá ở ``kiem-thu-phien-a/ma/gd1b_lo_*.json``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import text

import app.database as csdl
from app import models
from app.core.advisory_lock_keys import BULK_VERIFY_BATCH_NS, batch_lock_key
from app.database import AsyncSessionLocal
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    dn,
    dong_lo,
    dong_muc,
    lo_config,
    lo_routers,
    sql,
    tao_ho_so_cho_xet,
    xac_nhan,
)

pytestmark = pytest.mark.asyncio


async def _xem_truoc(client, user, **than):
    h = await dn(client, user)
    than.setdefault("include_optional", False)
    return await client.post(f"{BULK}/preview", headers=h, json=than)


async def _so_lo(actor_id: int, status: str = "previewed") -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                text("SELECT count(*) FROM document_bulk_batch WHERE actor_user_id = :u AND status = :st"),
                {"u": actor_id, "st": status},
            )
        ).scalar_one()


# ---------------------------------------------------------------------------------------------------- tạo lô
async def test_xem_truoc_tao_lo_previewed_dung_dong_muc_va_phien_ban(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p1 = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt1", giay_nhan="ABC")
    p2 = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt2", giay_nhan="AB")
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p1["id"], p2["id"]])
    assert r.status_code == 201, r.text
    body = r.json()
    mong = sorted(
        (p["id"], p["docs"][k].id, p["docs"][k].row_version) for p in (p1, p2) for k in "AB"
    )
    assert sorted((i["profile_id"], i["document_row_id"], i["expected_row_version"]) for i in body["items"]) == mong
    assert body["counts"] == {"profiles": 2, "documents": 4, "required": 4, "optional": 0}
    lo = await dong_lo(body["batch_id"])
    assert lo["status"] == "previewed" and lo["actor_user_id"] == manager_user_in_db["id"] and lo["review_mode"] == "batch"
    muc = await dong_muc(body["batch_id"])
    assert sorted((m["profile_id"], m["document_row_id"], m["expected_row_version"]) for m in muc) == mong
    assert all(m["result"] is None for m in muc)
    assert "full_name" not in r.text and "citizen_id" not in r.text


async def test_mac_dinh_chi_giay_bat_buoc_kem_tuy_chon_thi_co_giay_tuy_chon(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_tc", giay_nhan="AC")
    c_id = p["docs"]["C"].id
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
    assert r.status_code == 201, r.text
    assert c_id not in {i["document_row_id"] for i in r.json()["items"]}
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]], include_optional=True)
    assert r.status_code == 201, r.text
    it = {i["document_row_id"]: i for i in r.json()["items"]}
    assert c_id in it and it[c_id]["is_mandatory"] is False
    assert r.json()["counts"]["optional"] == 1


async def test_giay_ngoai_cau_hinh_khong_bao_gio_vao_lo(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_x1", giay_nhan="A")
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            dt = models.ConfigDocumentType(code=f"lox_{ts}", name=f"LOX_{ts}", display_order=99)
            s.add(dt)
            await s.flush()
            pd = models.ProfileDocument(
                profile_id=p["id"], document_type_id=dt.id, category="path", status="paper_submitted",
                paper_submitted_by=officer_user_in_db["id"], paper_submitted_at=datetime.now(timezone.utc),
                actual_submission_format="original",
            )
            s.add(pd)
            await s.flush()
            extra_id = pd.id
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]], include_optional=True)
    assert r.status_code == 201, r.text
    assert extra_id not in {i["document_row_id"] for i in r.json()["items"]}
    assert {"document_row_id": extra_id, "reason_code": "outside_config"}.items() <= next(
        x for x in r.json()["excluded"] if x["document_row_id"] == extra_id
    ).items()


async def test_ho_so_nhap_khong_vao_lo(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(
        client, admin_token_headers, officer_user_in_db, lo_config, "xt_nhap", giay_nhan="A", trang_thai="draft"
    )
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
    assert r.status_code == 201, r.text
    assert r.json()["items"] == []
    assert [x["reason_code"] for x in r.json()["excluded"]] == ["not_pending"]


async def test_nguoi_nhan_khong_dua_giay_minh_nhan_vao_lo(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(
        client, admin_token_headers, officer_user_in_db, lo_config, "xt_nn", giay_nhan="A", nguoi_nhan=manager_user_in_db
    )
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
    assert r.status_code == 201, r.text
    assert r.json()["items"] == [] and [x["reason_code"] for x in r.json()["excluded"]] == ["own_submission"]


async def test_quan_ly_don_vi_khac_khong_thay_ho_so_ngoai_pham_vi(
    client, admin_token_headers, manager_other_unit_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_pv", giay_nhan="AB")
    r = await _xem_truoc(client, manager_other_unit_user_in_db, profile_ids=[p["id"]])
    assert r.status_code == 201, r.text
    assert r.json()["items"] == [] and r.json()["excluded"] == []


async def test_bo_loc_chi_chon_ho_so_cho_xet(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    cho = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_bl1", giay_nhan="A")
    nhap = await tao_ho_so_cho_xet(
        client, admin_token_headers, officer_user_in_db, lo_config, "xt_bl2", giay_nhan="A", trang_thai="draft"
    )
    r = await _xem_truoc(client, manager_user_in_db, filter={"status": "submitted,draft"})
    assert r.status_code == 201, r.text
    ho_so = {i["profile_id"] for i in r.json()["items"]} | {x["profile_id"] for x in r.json()["excluded"]}
    assert cho["id"] in ho_so and nhap["id"] not in ho_so


async def test_can_bo_khong_xem_truoc_lo_duyet_giay(client, officer_user_in_db, lo_config, lo_routers):
    r = await _xem_truoc(client, officer_user_in_db, profile_ids=[1])
    assert r.status_code == 403, r.text


async def test_chua_do_N_thi_503_khong_tao_lo(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.services import document_bulk_verify_service as svc

    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_503", giay_nhan="A")
    monkeypatch.setattr(svc, "BULK_VERIFY_MAX_DOCUMENTS", None)
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
    assert r.status_code == 503 and r.json()["error_code"] == "BULK_VERIFY_NOT_CONFIGURED", r.text
    assert await _so_lo(manager_user_in_db["id"]) == 0


# ---------------------------------------------------------------------------------------------------- giới hạn (422, không tự cắt)
async def test_qua_100_ho_so_thi_422_kem_so_dem_khong_tao_lo(client, manager_user_in_db, lo_config, lo_routers):
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=list(range(1, 102)))
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "TOO_MANY_PROFILES"
    assert (r.json()["profile_count"], r.json()["limit"]) == (101, 100)
    assert await _so_lo(manager_user_in_db["id"]) == 0


async def test_bo_loc_khop_qua_tran_ho_so_thi_422_khong_tao_lo(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.services import document_bulk_verify_service as svc

    for i in range(3):
        await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, f"xt_bq{i}", giay_nhan="A")
    monkeypatch.setattr(svc, "BULK_VERIFY_MAX_PROFILES", 2)
    r = await _xem_truoc(client, manager_user_in_db, filter={})
    assert r.status_code == 422 and r.json()["error_code"] == "TOO_MANY_PROFILES", r.text
    assert (r.json()["profile_count"], r.json()["limit"]) == (3, 2)
    assert await _so_lo(manager_user_in_db["id"]) == 0


async def test_qua_N_giay_thi_422_kem_so_dem_khong_tao_lo(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.services import document_bulk_verify_service as svc

    p1 = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_n1", giay_nhan="AB")
    p2 = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_n2", giay_nhan="AB")
    monkeypatch.setattr(svc, "BULK_VERIFY_MAX_DOCUMENTS", 3)
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p1["id"], p2["id"]])
    assert r.status_code == 422 and r.json()["error_code"] == "TOO_MANY_DOCUMENTS", r.text
    assert (r.json()["document_count"], r.json()["limit"]) == (4, 3)
    assert await _so_lo(manager_user_in_db["id"]) == 0


async def test_ho_so_vuot_N_giay_bi_loai_profile_over_document_cap(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.services import document_bulk_verify_service as svc

    lon = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_cap1", giay_nhan="ABD")
    nho = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_cap2", giay_nhan="AB")
    monkeypatch.setattr(svc, "BULK_VERIFY_MAX_DOCUMENTS", 2)
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[lon["id"], nho["id"]])
    assert r.status_code == 201, r.text
    assert {i["profile_id"] for i in r.json()["items"]} == {nho["id"]}
    loai = [x for x in r.json()["excluded"] if x["profile_id"] == lon["id"]]
    assert len(loai) == 3 and {x["reason_code"] for x in loai} == {"profile_over_document_cap"}


# ---------------------------------------------------------------------------------------------------- dọn bản xem trước
async def test_nam_ban_xem_truoc_lien_tiep_con_toi_da_ba(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_5", giay_nhan="A")
    ma = []
    for _ in range(5):
        r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
        assert r.status_code == 201, r.text
        ma.append(r.json()["batch_id"])
    assert await _so_lo(manager_user_in_db["id"]) == 3
    assert [await dong_lo(m) is not None for m in ma] == [False, False, True, True, True], "dọn bản CŨ NHẤT trước"


async def test_ban_xem_truoc_het_han_bi_don(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_hh", giay_nhan="A")
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
    cu = r.json()["batch_id"]
    await sql("UPDATE document_bulk_batch SET expires_at = clock_timestamp() - interval '1 minute' WHERE batch_id = :b", b=cu)
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
    assert r.status_code == 201, r.text
    assert await dong_lo(cu) is None and await dong_muc(cu) == []


async def test_lo_da_chay_khong_bao_gio_bi_don(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_dc", giay_nhan="AB")
    r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
    da_chay = r.json()["batch_id"]
    h = await dn(client, manager_user_in_db)
    r = await client.post(f"{BULK}/{da_chay}/execute", headers=h, json=await xac_nhan(da_chay))
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    # Lô đã chạy là CŨ NHẤT và đã "hết hạn" theo expires_at — vẫn không được đụng.
    await sql(
        "UPDATE document_bulk_batch SET expires_at = clock_timestamp() - interval '1 minute',"
        " created_at = clock_timestamp() - interval '1 day' WHERE batch_id = :b",
        b=da_chay,
    )
    for _ in range(5):
        assert (await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])).status_code == 201
    lo = await dong_lo(da_chay)
    assert lo is not None and lo["status"] == "completed"
    assert len(await dong_muc(da_chay)) == 2


async def test_ba_ban_deu_dang_bi_giu_khoa_thi_409_too_many_previews_khong_chen(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """§5.2 bước 2: chỉ dòng KHÔNG dọn được (đang bị ``execute`` giữ khoá lô) mới làm đầy chỗ ⇒ đủ 3 dòng như thế ⇒ 409.
    Giữ khoá lô bằng một kết nối riêng (đúng khoá ``execute`` lấy ở §5.3 bước 1)."""
    p = await tao_ho_so_cho_xet(client, admin_token_headers, officer_user_in_db, lo_config, "xt_409", giay_nhan="A")
    ma = []
    for _ in range(3):
        r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
        ma.append(UUID(r.json()["batch_id"]))
    async with csdl.engine.connect() as giu:
        for m in ma:
            assert (
                await giu.execute(text("SELECT pg_try_advisory_lock(:ns, :k)"), {"ns": BULK_VERIFY_BATCH_NS, "k": batch_lock_key(m)})
            ).scalar() is True
        r = await _xem_truoc(client, manager_user_in_db, profile_ids=[p["id"]])
        await giu.execute(text("SELECT pg_advisory_unlock_all()"))
    assert r.status_code == 409 and r.json()["error_code"] == "TOO_MANY_PREVIEWS", r.text
    assert await _so_lo(manager_user_in_db["id"]) == 3
    assert all([await dong_lo(m) is not None for m in ma])
