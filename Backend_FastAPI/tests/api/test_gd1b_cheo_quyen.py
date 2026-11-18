"""GĐ1b — duyệt chéo tạm thời (đặc tả bản 3.6 §6, §9 "Duyệt chéo", "Trần 6a"; hợp đồng bản 4 §2.2 + ca kiểm thử BẮT BUỘC
Codex 69: quyền chồng lấn ⇒ ``grant_id`` riêng cho TỪNG thao tác).

Cán bộ chéo thuộc đơn vị khác (``seed_other_unit``); hồ sơ thuộc đơn vị mặc định, lead do cán bộ phụ trách
(``officer_user_in_db``) — người nhận giấy là cán bộ phụ trách, KHÁC cán bộ chéo.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from app import models
from app.database import AsyncSessionLocal
from tests.api.test_gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    CROSS,
    Diem,
    boc,
    dang_nhap,
    dn,
    dong_lo,
    dong_muc,
    giay,
    lo_config,
    lo_routers,
    sql,
    tao_ho_so_cho_xet,
    xac_nhan,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def can_bo_cheo(setup_test_database, seed_other_unit):
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule

    from app.main import fastapi_app
    from app.security import get_password_hash
    from tests.fixtures.users import create_user_with_role

    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": "gd1b_cheo_canbo",
            "email": "gd1b_cheo_canbo@example.com",
            "password": "CheoTest@2026x",
            "role": "officer",
            "status": "active",
        },
        casbin_role="role:officer",
        unit_id=seed_other_unit["unit_id"],
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )


def _han(ngay: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=ngay)).isoformat()


async def _cap(client, admin, grantee_id, unit_id, *, verify=False, reject=False, ngay=3.0, ly_do="Thiếu người duyệt"):
    h = await dn(client, admin)
    return await client.post(
        f"{CROSS}/grants",
        headers=h,
        json={
            "grantee_user_id": grantee_id, "unit_id": unit_id, "allow_verify": verify, "allow_reject": reject,
            "expires_at": _han(ngay), "reason": ly_do,
        },
    )


async def _ho_so(client, admin_h, officer, cfg, n=1, tien_to="cq"):
    return [await tao_ho_so_cho_xet(client, admin_h, officer, cfg, f"{tien_to}{i}", giay_nhan="AB") for i in range(n)]


# ---------------------------------------------------------------------------------------------------- Admin cấp / thu hồi
async def test_cap_quyen_qua_14_ngay_422_khong_tao_dong(
    client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    r = await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True, ngay=15)
    assert r.status_code == 422 and r.json()["error_code"] == "GRANT_TOO_LONG" and r.json()["max_days"] == 14, r.text
    r = await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True, ngay=13.9)
    assert r.status_code == 201, r.text
    async with AsyncSessionLocal() as s:
        assert (await s.execute(text("SELECT count(*) FROM document_cross_review_grant"))).scalar_one() == 1


async def test_cap_quyen_khong_ly_do_422(client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers):
    r = await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True, ly_do="   ")
    assert r.status_code == 422, r.text


async def test_nguoi_duoc_cap_phai_la_can_bo_dang_hoat_dong(
    client, admin_user_in_db, manager_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    r = await _cap(client, admin_user_in_db, manager_user_in_db["id"], lo_config["unit_id"], verify=True)
    assert r.status_code == 422 and r.json()["error_code"] == "GRANTEE_NOT_ELIGIBLE", r.text
    await sql("UPDATE \"user\" SET status = 'inactive' WHERE id = :u", u=can_bo_cheo["id"])
    r = await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    assert r.status_code == 422 and r.json()["error_code"] == "GRANTEE_NOT_ELIGIBLE", r.text


async def test_chi_admin_cap_quyen(client, manager_user_in_db, can_bo_cheo, lo_config, lo_routers):
    r = await _cap(client, manager_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    assert r.status_code == 403, r.text


async def test_cap_va_thu_hoi_ghi_su_kien_chi_thu_hoi_khong_xoa(
    client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    r = await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    gid = r.json()["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.post(f"{CROSS}/grants/{gid}/revoke", headers=h, json={"reason": "Đã đủ người"})
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["revoked_by_user_id"] == admin_user_in_db["id"]
    r = await client.post(f"{CROSS}/grants/{gid}/revoke", headers=h, json={"reason": "lần hai"})
    assert r.status_code == 409 and r.json()["error_code"] == "GRANT_ALREADY_REVOKED", r.text
    async with AsyncSessionLocal() as s:
        su_kien = (
            await s.execute(
                text(
                    "SELECT action, reason FROM entity_audit_log WHERE entity_type = 'document_cross_review_grant'"
                    " AND entity_id = :g ORDER BY id"
                ),
                {"g": gid},
            )
        ).all()
        con = (await s.execute(text("SELECT count(*) FROM document_cross_review_grant WHERE id = :g"), {"g": gid})).scalar()
    assert [(a, r_) for a, r_ in su_kien] == [("granted", "Thiếu người duyệt"), ("revoked", "Đã đủ người")]
    assert con == 1
    r = await client.get(f"{CROSS}/grants?active=true", headers=h)
    assert r.status_code == 200 and r.json() == []


# ---------------------------------------------------------------------------------------------------- eligibility
async def test_eligibility_chi_tra_quyen_con_hieu_luc_cua_chinh_nguoi_goi(
    client, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    g = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)).json()
    h = await dn(client, can_bo_cheo)
    r = await client.get(f"{CROSS}/eligibility", headers=h)
    assert r.status_code == 200 and r.json()["eligible"] is True
    assert [x["grant_id"] for x in r.json()["grants"]] == [g["id"]]
    h = await dn(client, officer_user_in_db)
    r = await client.get(f"{CROSS}/eligibility", headers=h)
    assert r.status_code == 200 and r.json() == {"eligible": False, "grants": []}


async def test_can_bo_khong_co_quyen_hang_doi_va_duyet_404(
    client, admin_token_headers, officer_user_in_db, manager_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p = (await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config))[0]
    d = p["docs"]["A"]
    for u in (can_bo_cheo, manager_user_in_db):
        h = await dn(client, u)
        assert (await client.get(f"{CROSS}/queue", headers=h)).status_code == 404
        r = await client.post(
            f"{CROSS}/verify", headers=h,
            json={"grant_id": 1, "profile_id": p["id"], "document_row_id": d.id, "expected_row_version": d.row_version},
        )
        assert r.status_code == 404, r.text
    assert (await giay(p["id"], lo_config["codes"]["A"])).status == "paper_submitted"


async def test_ho_so_ngoai_don_vi_duoc_cap_404(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    p = (await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config))[0]
    g = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], seed_other_unit["unit_id"], verify=True)).json()
    d = p["docs"]["A"]
    h = await dn(client, can_bo_cheo)
    r = await client.post(
        f"{CROSS}/verify", headers=h,
        json={"grant_id": g["id"], "profile_id": p["id"], "document_row_id": d.id, "expected_row_version": d.row_version},
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------------------------------- Codex 69 — BẮT BUỘC
async def test_quyen_chong_lan_moi_thao_tac_mot_grant_id_dung(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Cùng cán bộ, cùng đơn vị, hai quyền còn hiệu lực — G1 chỉ ``reject`` hạn XA hơn, G2 chỉ ``verify`` hạn gần hơn ⇒ hàng
    đợi trả ``{verify: G2, reject: G1}``; duyệt bằng G1 ⇒ 409 ``actor_not_authorized``, không ghi; duyệt bằng G2 ⇒ ghi."""
    p = (await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config))[0]
    unit = lo_config["unit_id"]
    g1 = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], unit, reject=True, ngay=10)).json()["id"]
    g2 = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], unit, verify=True, ngay=3)).json()["id"]
    d = p["docs"]["A"]
    h = await dn(client, can_bo_cheo)
    r = await client.get(f"{CROSS}/queue", headers=h)
    assert r.status_code == 200, r.text
    muc = {x["document_row_id"]: x for x in r.json()["items"]}
    assert muc[d.id]["grant_id_by_action"] == {"verify": g2, "reject": g1}
    assert set(muc[d.id]) == {
        "profile_id", "document_row_id", "document_type_code", "row_version", "actual_submission_format",
        "profile_status", "grant_id_by_action",
    }
    than = {"profile_id": p["id"], "document_row_id": d.id, "expected_row_version": d.row_version}
    r = await client.post(f"{CROSS}/verify", headers=h, json={"grant_id": g1, **than})
    assert r.status_code == 409 and r.json()["error_code"] == "ACTOR_NOT_AUTHORIZED", r.text
    assert (await giay(p["id"], lo_config["codes"]["A"])).status == "paper_submitted"
    r = await client.post(f"{CROSS}/verify", headers=h, json={"grant_id": g2, **than})
    assert r.status_code == 200 and r.json()["new_status"] == "verified", r.text
    sau = await giay(p["id"], lo_config["codes"]["A"])
    assert sau.status == "verified" and sau.verified_by == can_bo_cheo["id"]


async def test_tu_choi_cheo_bat_buoc_ly_do_va_dung_quyen_tu_choi(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p = (await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config))[0]
    g1 = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], reject=True)).json()["id"]
    d = p["docs"]["B"]
    h = await dn(client, can_bo_cheo)
    than = {"grant_id": g1, "profile_id": p["id"], "document_row_id": d.id, "expected_row_version": d.row_version}
    r = await client.post(f"{CROSS}/reject", headers=h, json=than)
    assert r.status_code == 422 and r.json()["error_code"] == "REASON_REQUIRED", r.text
    r = await client.post(f"{CROSS}/reject", headers=h, json={**than, "reason": "Bản sao mờ"})
    assert r.status_code == 200 and r.json()["new_status"] == "rejected", r.text


# ---------------------------------------------------------------------------------------------------- lô chéo
async def test_lo_cheo_xem_truoc_va_chay_ghi_via_cross_va_grant_id(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    g2 = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)).json()["id"]
    g1 = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], reject=True)).json()["id"]
    h = await dn(client, can_bo_cheo)
    ids = [p["id"] for p in ps]
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": ids, "grant_id": g1})
    assert r.status_code == 409 and r.json()["error_code"] == "ACTOR_NOT_AUTHORIZED", r.text
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": ids, "grant_id": g2})
    assert r.status_code == 201 and r.json()["counts"]["documents"] == 4, r.text
    ma = r.json()["batch_id"]
    lo = await dong_lo(ma)
    assert lo["review_mode"] == "cross" and lo["grant_id"] == g2
    r = await client.post(f"{CROSS}/bulk-verify/{ma}/execute", headers=h, json=await xac_nhan(ma))
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    async with AsyncSessionLocal() as s:
        ex = (
            await s.execute(
                text("SELECT extra_data FROM document_audit_log WHERE action = 'verified' AND profile_document_id = :d"),
                {"d": ps[0]["docs"]["A"].id},
            )
        ).scalar_one()
    assert ex["via"] == "cross" and ex["grant_id"] == g2 and ex["batch_id"] == ma


@pytest.mark.parametrize("bien", ["thu_hoi", "het_han"])
async def test_lo_cheo_quyen_mat_giua_lo_thi_dung_o_ho_so_ke_tiep(
    bien, client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config,
    lo_routers,
):
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 4)
    g2 = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)).json()["id"]
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"] for p in ps], "grant_id": g2})
    ma = r.json()["batch_id"]
    diem = Diem(lan=2)
    boc(monkeypatch, svc, "_commit_profile", diem)
    ca, ha = await dang_nhap(can_bo_cheo)
    try:
        a = asyncio.create_task(ca.post(f"{CROSS}/bulk-verify/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        if bien == "thu_hoi":
            await sql(
                "UPDATE document_cross_review_grant SET revoked_at = clock_timestamp(), revoked_by_user_id = :a WHERE id = :g",
                a=admin_user_in_db["id"], g=g2,
            )
        else:
            await sql(
                "UPDATE document_cross_review_grant SET granted_at = clock_timestamp() - interval '2 days',"
                " expires_at = clock_timestamp() - interval '1 second' WHERE id = :g",
                g=g2,
            )
        diem.di.set()
        r = await a
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 200 and r.json()["status"] == "stopped", r.text
    kq = {}
    for m in await dong_muc(ma):
        kq.setdefault(m["profile_id"], set()).add((m["result"], m["reason_code"]))
    assert kq[ps[1]["id"]] == {("recorded", None)}
    assert kq[ps[2]["id"]] == {("error", "actor_not_authorized")} and kq[ps[3]["id"]] == {("not_processed", None)}
    assert (await giay(ps[2]["id"], lo_config["codes"]["A"])).status == "paper_submitted"


# ---------------------------------------------------------------------------------------------------- cờ máy chủ B4 trên lô chéo
async def test_lo_cheo_co_chot_can_ly_do_khop_hanh_vi_admin_va_can_bo_tao(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Lô chéo (người tạo = cán bộ chéo). Admin xem / chốt qua đường lô thường (mã hiện tại cho Admin xem + chốt MỌI chế độ
    lô): cờ true ⇔ chốt không lý do 422. Cán bộ tạo xem qua đường chéo: cờ false ⇔ chốt không lý do 200."""
    p = (await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config))[0]
    g = (await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)).json()["id"]
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"]], "grant_id": g})
    ma = r.json()["batch_id"]
    await sql("UPDATE document_bulk_batch SET status = 'processing', started_at = now() WHERE batch_id = :b", b=ma)
    h = await dn(client, admin_user_in_db)
    v = (await client.get(f"{BULK}/{ma}", headers=h)).json()
    assert (v["can_finalize"], v["finalize_requires_reason"]) == (True, True), v
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
    assert r.status_code == 422 and r.json()["error_code"] == "REASON_REQUIRED", r.text
    h = await dn(client, can_bo_cheo)
    v = (await client.get(f"{CROSS}/bulk-verify/{ma}", headers=h)).json()
    assert (v["can_finalize"], v["finalize_requires_reason"]) == (True, False), v
    r = await client.post(f"{CROSS}/bulk-verify/{ma}/finalize", headers=h, json={})
    assert r.status_code == 200 and r.json()["finalized_now"] is True, r.text


async def test_lo_cheo_can_view_all_luon_false_va_scope_all_403(
    client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Đường lô chéo chỉ có "của tôi": ``can_view_all`` = false ⇔ ``scope=all`` 403."""
    await _cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, can_bo_cheo)
    r = await client.get(f"{CROSS}/bulk-verify", headers=h)
    assert r.status_code == 200 and r.json()["can_view_all"] is False, r.text
    r = await client.get(f"{CROSS}/bulk-verify", headers=h, params={"scope": "all"})
    assert r.status_code == 403, r.text
