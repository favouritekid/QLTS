"""GĐ1b PR-B — owner Q4 (20-11): đổi vai / khoá tài khoản ⇒ TỰ THU HỒI mọi quyền duyệt chéo chưa hết hạn của người ấy ở MỌI
đơn vị, CÙNG giao dịch với việc đổi vai / khoá; áp cả thao tác HÀNG LOẠT; lý do ghi vào nhật ký kiểm toán
(``entity_audit_log``, khuôn ``revoke_grant``); mở khoá / trả vai KHÔNG khôi phục quyền cũ.

Mọi phép kiểm đọc CSDL từ phiên RIÊNG. Hai phiên + phiên thứ ba (``pg_blocking_pids``) cho cặp "lô chéo đang xử lý một hồ sơ
‖ đổi vai / khoá tài khoản người chạy lô" (thứ tự khoá — không vòng chờ).
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.services import document_bulk_verify_service as svc
from app.repositories import document_bulk_repository as bulk_repo
from tests.api.gd1b_cheo_tro_giup import (  # noqa: F401
    THAN_404,
    bi_chan_boi_pid,
    can_bo_cheo,
    cap,
    hang,
    ho_so,
    mot,
    tao_nguoi,
)
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    CROSS,
    Diem,
    NHAN,
    PidTheoNhan,
    boc,
    dang_nhap,
    dn,
    dong_muc,
    giay,
    lo_config,
    lo_routers,
    sql,
    xac_nhan,
)
from tests.fixtures.constants import AuthURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

LY_DO_KHOA = "Tự thu hồi: tài khoản bị khoá"
LY_DO_KE_TOAN = "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Kế toán"


async def _bon_quyen(client, admin, x, unit_u, unit_u2):
    """Bốn quyền của ``x``: g1 (đơn vị U, duyệt), g2 (đơn vị U2, từ chối) — CÒN hiệu lực; g_het (đã HẾT hạn), g_tay (đã bị
    Admin thu hồi tay)."""
    g1 = await cap(client, admin, x["id"], unit_u, verify=True)
    g2 = await cap(client, admin, x["id"], unit_u2, reject=True)
    g_het = await cap(client, admin, x["id"], unit_u, verify=True)
    await sql(
        "UPDATE document_cross_review_grant SET granted_at = clock_timestamp() - interval '2 days',"
        " expires_at = clock_timestamp() - interval '1 second' WHERE id = :g",
        g=g_het,
    )
    g_tay = await cap(client, admin, x["id"], unit_u, reject=True)
    h = await dn(client, admin)
    r = await client.post(f"{CROSS}/grants/{g_tay}/revoke", headers=h, json={"reason": "Thu hồi tay"})
    assert r.status_code == 200, r.text
    return {"g1": g1, "g2": g2, "g_het": g_het, "g_tay": g_tay}


async def _thu_hoi_cua(gid):
    return await hang(
        "SELECT g.revoked_at IS NOT NULL AS da_thu_hoi, g.revoked_by_user_id, a.actor_user_id, a.reason,"
        " a.created_at IS NOT NULL AS co_luc"
        " FROM document_cross_review_grant g LEFT JOIN entity_audit_log a ON a.entity_type = 'document_cross_review_grant'"
        " AND a.entity_id = g.id AND a.action = 'revoked' WHERE g.id = :g ORDER BY a.id",
        g=gid,
    )


async def _kiem_tu_thu_hoi(q, admin_id, ly_do):
    """g1, g2 bị TỰ thu hồi đủ ai / lúc / lý do; g_het (hết hạn) không đụng; g_tay giữ đúng một lần thu hồi tay."""
    for k in ("g1", "g2"):
        assert await _thu_hoi_cua(q[k]) == [
            {"da_thu_hoi": True, "revoked_by_user_id": admin_id, "actor_user_id": admin_id, "reason": ly_do, "co_luc": True}
        ], k
    assert await _thu_hoi_cua(q["g_het"]) == [  # không dòng nhật ký nào (LEFT JOIN rỗng)
        {"da_thu_hoi": False, "revoked_by_user_id": None, "actor_user_id": None, "reason": None, "co_luc": False}
    ]
    assert [r["reason"] for r in await _thu_hoi_cua(q["g_tay"])] == ["Thu hồi tay"]


async def _chua_thu_hoi(q):
    for k in ("g1", "g2"):
        assert (await _thu_hoi_cua(q[k]))[0]["da_thu_hoi"] is False, k
    assert await mot(
        "SELECT count(*) FROM entity_audit_log WHERE entity_type = 'document_cross_review_grant' AND action = 'revoked'"
        " AND reason LIKE 'Tự thu hồi%'"
    ) == 0


# ---------------------------------------------------------------------------------------------------- (i) lẻ + hàng loạt
async def test_q4_doi_vai_le_thu_hoi_moi_quyen_con_han_o_moi_don_vi_co_nhat_ky(
    client, admin_token_headers, admin_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    q = await _bon_quyen(client, admin_user_in_db, can_bo_cheo, lo_config["unit_id"], seed_other_unit["unit_id"])
    r = await client.put(f"/api/admin/users/{can_bo_cheo['id']}", headers=admin_token_headers, data={"role": "accountant"})
    assert r.status_code == 200, r.text
    assert await mot("SELECT role FROM \"user\" WHERE id = :u", u=can_bo_cheo["id"]) == "accountant"
    await _kiem_tu_thu_hoi(q, admin_user_in_db["id"], LY_DO_KE_TOAN)


async def test_q4_khoa_tai_khoan_le_thu_hoi_moi_quyen_con_han(
    client, admin_token_headers, admin_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    q = await _bon_quyen(client, admin_user_in_db, can_bo_cheo, lo_config["unit_id"], seed_other_unit["unit_id"])
    r = await client.put(f"/api/admin/users/{can_bo_cheo['id']}", headers=admin_token_headers, data={"status": "inactive"})
    assert r.status_code == 200, r.text
    await _kiem_tu_thu_hoi(q, admin_user_in_db["id"], LY_DO_KHOA)


async def test_q4_khoa_tai_khoan_hang_loat_thu_hoi_cua_tung_nguoi(
    client, admin_token_headers, admin_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    can_bo_2 = await tao_nguoi("prb_q4_canbo2", "officer", lo_config["unit_id"])
    q1 = await _bon_quyen(client, admin_user_in_db, can_bo_cheo, lo_config["unit_id"], seed_other_unit["unit_id"])
    q2 = await _bon_quyen(client, admin_user_in_db, can_bo_2, lo_config["unit_id"], seed_other_unit["unit_id"])
    h = await dn(client, admin_user_in_db)
    r = await client.post(
        "/api/admin/users/bulk", headers=h,
        json={"action": "change_status", "user_ids": [can_bo_2["id"], can_bo_cheo["id"]], "status": "banned"},
    )
    assert r.status_code == 200, r.text
    await _kiem_tu_thu_hoi(q1, admin_user_in_db["id"], LY_DO_KHOA)
    await _kiem_tu_thu_hoi(q2, admin_user_in_db["id"], LY_DO_KHOA)


async def test_q4_dong_bo_vai_tu_casbin_doi_vai_khoi_can_bo_thu_hoi(
    client, admin_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    q = await _bon_quyen(client, admin_user_in_db, can_bo_cheo, lo_config["unit_id"], seed_other_unit["unit_id"])
    h = await dn(client, admin_user_in_db)
    r = await client.post("/api/admin/roles/assign", headers=h, json={"user_id": can_bo_cheo["id"], "role": "role:manager"})
    assert r.status_code == 201, r.text
    r = await client.post("/api/admin/users/sync", headers=h, json={"user_ids": [can_bo_cheo["id"]]})
    assert r.status_code == 200 and r.json()["synced_count"] == 1, r.text
    assert await mot("SELECT role FROM \"user\" WHERE id = :u", u=can_bo_cheo["id"]) == "manager"
    await _kiem_tu_thu_hoi(q, admin_user_in_db["id"], "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Quản lý")


async def test_q4_go_vai_can_bo_khoi_nguoi_dung_thu_hoi(
    client, admin_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    q = await _bon_quyen(client, admin_user_in_db, can_bo_cheo, lo_config["unit_id"], seed_other_unit["unit_id"])
    h = await dn(client, admin_user_in_db)
    r = await client.request(
        "DELETE", "/api/admin/roles/role:officer/users", headers=h,
        json={"user_ids": [can_bo_cheo["id"]], "role_to_remove": "role:officer"},
    )
    assert r.status_code == 200 and r.json()["removed_count"] == 1, r.text
    assert await mot("SELECT role FROM \"user\" WHERE id = :u", u=can_bo_cheo["id"]) == "user"
    await _kiem_tu_thu_hoi(q, admin_user_in_db["id"], "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Người dùng")


# ---------------------------------------------------------------------------------------------------- (ii) nhật ký lỗi
async def _client_500(user):
    """Client KHÔNG ném lại ngoại lệ ứng dụng (``raise_app_exceptions=False``) ⇒ nhận đúng phản hồi 500 của máy chủ."""
    from app.main import fastapi_app

    c = AsyncClient(transport=ASGITransport(app=fastapi_app, raise_app_exceptions=False), base_url="http://test",
                    headers={"User-Agent": "prb-q4-500"})
    r = await c.post(AuthURLs.LOGIN, data={"username": user["username"], "password": user["password"]})
    assert r.status_code == 200, r.text
    return c, {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest.mark.parametrize("duong", ["le_doi_vai", "le_khoa", "hang_loat_khoa", "le_khoa_loi_sau_thu_hoi"])
async def test_q4_ghi_nhat_ky_kiem_toan_loi_thi_rollback_ca_doi_vai_khoa_lan_thu_hoi(
    duong, client, monkeypatch, admin_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    """Ba đường đầu: tiêm lỗi vào lần ghi nhật ký kiểm toán của việc thu hồi. ``le_khoa_loi_sau_thu_hoi``: thu hồi + nhật ký
    ghi XONG, rồi một bước SAU đó của chính lệnh khoá (cắt socket) lỗi ⇒ toàn lệnh rollback ⇒ thu hồi cũng phải mất (bắt
    biến thể "thu hồi ở giao dịch RIÊNG đã commit")."""
    import app.socket_manager as sm
    from app.main import fastapi_app
    from app.services import audit_service

    q = await _bon_quyen(client, admin_user_in_db, can_bo_cheo, lo_config["unit_id"], seed_other_unit["unit_id"])
    goc = audit_service.log_audit
    da_tiem = []

    async def hong(db, entity_type, *a, **kw):
        if entity_type == "document_cross_review_grant":
            da_tiem.append(entity_type)
            raise RuntimeError("tiêm lỗi ghi nhật ký kiểm toán")
        return await goc(db, entity_type, *a, **kw)

    async def ngat_loi(*a, **kw):
        da_tiem.append("ngat_ket_noi")
        raise RuntimeError("tiêm lỗi cắt socket")

    if duong == "le_khoa_loi_sau_thu_hoi":
        monkeypatch.setattr(sm, "force_disconnect_user_strict", ngat_loi)
    else:
        monkeypatch.setattr(audit_service, "log_audit", hong)
    c, h = await _client_500(admin_user_in_db)
    try:
        if duong in ("le_khoa", "le_khoa_loi_sau_thu_hoi"):
            r = await c.put(f"/api/admin/users/{can_bo_cheo['id']}", headers=h, data={"status": "inactive"})
        elif duong == "le_doi_vai":
            r = await c.put(f"/api/admin/users/{can_bo_cheo['id']}", headers=h, data={"role": "accountant"})
        else:
            r = await c.post("/api/admin/users/bulk", headers=h,
                             json={"action": "change_status", "user_ids": [can_bo_cheo["id"]], "status": "banned"})
    finally:
        await c.aclose()
    assert da_tiem, "tiền đề: lỗi phải được tiêm ĐÚNG chỗ (nhật ký thu hồi / bước sau thu hồi)"
    assert r.status_code == 500, r.text
    assert await mot("SELECT role FROM \"user\" WHERE id = :u", u=can_bo_cheo["id"]) == "officer"
    assert await mot("SELECT status FROM \"user\" WHERE id = :u", u=can_bo_cheo["id"]) == "active"
    await _chua_thu_hoi(q)
    # Casbin (adapter ghi bằng phiên riêng) chưa bị đụng: thu hồi chạy TRƯỚC đồng bộ vai.
    assert "role:officer" in await fastapi_app.state.enforcer.get_roles_for_user(f"user:{can_bo_cheo['id']}")


# ---------------------------------------------------------------------------------------------------- (iii) lô đang chạy
async def _lo_cheo_3_ho_so(client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, cfg, tien_to):
    ps = await ho_so(client, admin_token_headers, officer_user_in_db, cfg, 3, tien_to=tien_to)
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], cfg["unit_id"], verify=True)
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"] for p in ps], "grant_id": gid})
    assert r.status_code == 201 and r.json()["counts"]["documents"] == 6, r.text
    return ps, gid, r.json()["batch_id"]


def _ket_qua(muc):
    kq = {}
    for m in muc:
        kq.setdefault(m["profile_id"], set()).add((m["result"], m["reason_code"]))
    return kq


async def _goi_nhan(nhan, ham):
    NHAN.set(nhan)
    return await ham()


async def test_q4_lo_cheo_dang_chay_bi_khoa_tai_khoan_giua_hai_ho_so_thi_dung_truoc_ho_so_ke(
    client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Ca nghiệm thu quan trọng nhất (owner): hồ sơ đã duyệt xong giữ nguyên; sau khi việc khoá commit, lô DỪNG trước khi
    ghi hồ sơ kế tiếp."""
    ps, gid, ma = await _lo_cheo_3_ho_so(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, "q4lo"
    )
    diem = Diem(lan=1)
    boc(monkeypatch, svc, "_commit_profile", diem)  # dừng NGAY SAU commit hồ sơ 1
    cb, hb = await dang_nhap(can_bo_cheo)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        viec = asyncio.create_task(cb.post(f"{CROSS}/bulk-verify/{ma}/execute", headers=hb, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        r_khoa = await ca.put(f"/api/admin/users/{can_bo_cheo['id']}", headers=ha, data={"status": "inactive"})
        assert r_khoa.status_code == 200, r_khoa.text  # đã commit (lô đang dừng, không giữ khoá dòng nào)
        diem.di.set()
        r = await asyncio.wait_for(viec, 60)
    finally:
        diem.di.set()
        await cb.aclose()
        await ca.aclose()
    assert r.status_code == 200 and r.json()["status"] == "stopped", r.text
    kq = _ket_qua(await dong_muc(ma))
    assert kq[ps[0]["id"]] == {("recorded", None)}
    assert kq[ps[1]["id"]] == {("error", "actor_not_authorized")} and kq[ps[2]["id"]] == {("not_processed", None)}
    assert (await giay(ps[0]["id"], lo_config["codes"]["A"])).status == "verified"
    assert (await giay(ps[1]["id"], lo_config["codes"]["A"])).status == "paper_submitted"
    assert [x["reason"] for x in await _thu_hoi_cua(gid)] == [LY_DO_KHOA]


@pytest.mark.parametrize("thay_doi", [{"status": "inactive"}, {"role": "accountant"}])
async def test_q4_doi_vai_khoa_khi_lo_cheo_dang_ghi_mot_ho_so_xep_hang_o_dong_quyen_khong_be_tac(
    thay_doi, client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config,
    lo_routers,
):
    """Cặp Codex (điều phối 20-11): lô chéo ĐANG xử lý hồ sơ 1 (giữ dòng quyền FOR SHARE + hồ sơ / lead / giấy, CHƯA khoá
    người) ‖ Admin đổi vai / khoá người chạy lô (Q4: người FOR NO KEY UPDATE → quyền FOR UPDATE). C phải bị ĐÚNG phiên lô
    chặn (phiên thứ ba, ``pg_blocking_pids``); thả ⇒ lô khoá người FOR KEY SHARE (không xung đột) ⇒ ghi xong hồ sơ 1 ⇒ C
    commit ⇒ lô dừng ở hồ sơ 2. Không bên nào 500 / ``profile_busy`` (bế tắc ``40P01``)."""
    ps, gid, ma = await _lo_cheo_3_ho_so(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, "q4cap"
    )
    diem = Diem(lan=1)
    boc(monkeypatch, bulk_repo, "lock_documents", diem)  # dừng SAU khi khoá giấy hồ sơ 1, TRƯỚC khoá người
    than_chay = await xac_nhan(ma)
    cb, hb = await dang_nhap(can_bo_cheo)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        with PidTheoNhan() as ghi:
            viec = asyncio.create_task(_goi_nhan("B", lambda: cb.post(
                f"{CROSS}/bulk-verify/{ma}/execute", headers=hb, json=than_chay)))
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_b = set(ghi.pid.get("B", ()))
            assert pid_b
            viec_c = asyncio.create_task(_goi_nhan("C", lambda: ca.put(
                f"/api/admin/users/{can_bo_cheo['id']}", headers=ha, data=thay_doi)))
            assert await bi_chan_boi_pid(viec_c, ghi, "C", pid_b) == "chan", "đổi vai / khoá phải xếp hàng sau lô"
            diem.di.set()
            r = await asyncio.wait_for(viec, 60)
            r_c = await asyncio.wait_for(viec_c, 60)
    finally:
        diem.di.set()
        await cb.aclose()
        await ca.aclose()
    assert r_c.status_code == 200, r_c.text
    assert r.status_code == 200 and r.json()["status"] == "stopped", r.text
    kq = _ket_qua(await dong_muc(ma))
    assert kq[ps[0]["id"]] == {("recorded", None)}, kq
    assert kq[ps[1]["id"]] == {("error", "actor_not_authorized")} and kq[ps[2]["id"]] == {("not_processed", None)}, kq
    assert (await _thu_hoi_cua(gid))[0]["da_thu_hoi"] is True


# ---------------------------------------------------------------------------------------------------- (iv) mở khoá
async def test_q4_mo_khoa_ngay_trong_ngay_quyen_cu_van_thu_hoi_cho_toi_khi_admin_cap_moi(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, seed_other_unit, lo_config,
    lo_routers,
):
    await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="q4mo")
    q = await _bon_quyen(client, admin_user_in_db, can_bo_cheo, lo_config["unit_id"], seed_other_unit["unit_id"])
    for trang_thai in ("inactive", "active"):
        r = await client.put(
            f"/api/admin/users/{can_bo_cheo['id']}", headers=admin_token_headers, data={"status": trang_thai}
        )
        assert r.status_code == 200, r.text
    await _kiem_tu_thu_hoi(q, admin_user_in_db["id"], LY_DO_KHOA)
    h = await dn(client, can_bo_cheo)
    r = await client.get(f"{CROSS}/eligibility", headers=h)
    assert r.status_code == 200 and r.json() == {"eligible": False, "grants": []}, r.text
    r = await client.get(f"{CROSS}/queue", headers=h)
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True, ly_do="Cấp lại sau mở khoá")
    h = await dn(client, can_bo_cheo)
    r = await client.get(f"{CROSS}/queue", headers=h)
    assert r.status_code == 200 and r.json()["total_count"] >= 1, r.text
