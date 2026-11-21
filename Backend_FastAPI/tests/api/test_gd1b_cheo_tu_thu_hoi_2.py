"""GĐ1b PR-B lượt 2 — tự thu hồi quyền duyệt chéo (Q4) — các điểm chặn Codex lượt 1 + owner chốt 21-11.

- Điểm chặn 3 / owner câu 7: gỡ vai Cán bộ HÀNG LOẠT mà ghi nhật ký lỗi (ở người thứ hai) ⇒ 500, không gì commit; THỬ LẠI
  phải đưa Casbin, vai CSDL, dấu thu hồi + nhật ký về nhất quán — kể cả người thứ nhất mà lần trước Casbin đã gỡ.
- Điểm chặn 4: liên kết tài khoản với CTV — giữa cổng kiểm và lúc ghi vai, tài khoản thành Cán bộ và được cấp quyền chéo ⇒
  yêu cầu cũ bị TỪ CHỐI bằng đúng lỗi hiện có của luật liên kết (404), vai và quyền chéo giữ nguyên.
- Owner câu 1: vừa khoá vừa đổi vai ⇒ ghi CẢ HAI câu lý do. (Câu 6 — người thu hồi = đúng người thực hiện: cả 4 đường
  truyền id người đã đăng nhập; Quản lý KHÔNG có dòng Casbin cho ``/api/admin/users/*`` ⇒ hiện không có đường HTTP nào
  để Quản lý đổi vai / trạng thái — đo 21-11: 403.)
- Vá nhánh (cùng khuôn điểm chặn 4): quyết thu hồi bằng vai / trạng thái đọc DƯỚI khoá, không bằng bản đọc từ đầu yêu cầu.

Mọi phép kiểm đọc CSDL từ phiên riêng.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.services import collaborator_service, user_service
from tests.api.gd1b_cheo_tro_giup import bi_chan_boi_pid, can_bo_cheo, cap, hang, mot, tao_nguoi  # noqa: F401
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    CROSS,
    NHAN,
    Diem,
    PidTheoNhan,
    boc,
    dang_nhap,
    dn,
    lo_config,
    lo_routers,
    sql,
)
from tests.api.test_gd1b_cheo_tu_thu_hoi import LY_DO_KHOA, _client_500, _thu_hoi_cua

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

LY_DO_NGUOI_DUNG = "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Người dùng"


async def _vai(uid):
    return await mot('SELECT role FROM "user" WHERE id = :u', u=uid)


async def _con_hieu_luc(gid):
    return await mot(
        "SELECT revoked_at IS NULL AND expires_at > clock_timestamp() FROM document_cross_review_grant WHERE id = :g", g=gid
    )


async def _casbin_g(uid):
    """Dòng ``g`` của người trong BẢNG ``casbin_rule`` (adapter ghi bằng phiên riêng) + vai trong enforcer đang chạy."""
    from app.main import fastapi_app

    async with AsyncSessionLocal() as s:
        bang = {
            r[0]
            for r in (
                await s.execute(text("SELECT v1 FROM casbin_rule WHERE ptype = 'g' AND v0 = :v"), {"v": f"user:{uid}"})
            ).all()
        }
    return bang, set(await fastapi_app.state.enforcer.get_roles_for_user(f"user:{uid}"))


# ---------------------------------------------------------------------------------------------------- điểm chặn 3
async def test_go_vai_hang_loat_nhat_ky_loi_o_nguoi_thu_hai_thu_lai_dua_ca_ba_ve_nhat_quan(
    client, monkeypatch, admin_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    from app.services import audit_service

    x2 = await tao_nguoi("prb_l2_canbo2", "officer", lo_config["unit_id"])
    truoc, sau = sorted((can_bo_cheo["id"], x2["id"]))
    g_truoc = await cap(client, admin_user_in_db, truoc, lo_config["unit_id"], verify=True)
    g_sau = await cap(client, admin_user_in_db, sau, lo_config["unit_id"], reject=True)
    goc = audit_service.log_audit
    tiem = {"bat": True, "so_lan": 0}

    async def hong(db, entity_type, entity_id, *a, **kw):
        if tiem["bat"] and entity_type == "document_cross_review_grant" and entity_id == g_sau:
            tiem["so_lan"] += 1
            raise RuntimeError("tiêm lỗi ghi nhật ký thu hồi ở người thứ hai")
        return await goc(db, entity_type, entity_id, *a, **kw)

    monkeypatch.setattr(audit_service, "log_audit", hong)
    than = {"user_ids": [sau, truoc], "role_to_remove": "role:officer"}
    c, h = await _client_500(admin_user_in_db)
    try:
        r = await c.request("DELETE", "/api/admin/roles/role:officer/users", headers=h, json=than)
        assert tiem["so_lan"] == 1, "tiền đề: lỗi phải được tiêm đúng lần ghi nhật ký của người thứ hai"
        assert r.status_code == 500, r.text
        # Lần 1 rollback: vai CSDL + quyền chéo nguyên; người THỨ NHẤT đã bị gỡ vai trong Casbin (phiên riêng) — đúng tình
        # huống "thử lại phải đồng bộ lại", người thứ hai Casbin chưa đụng.
        assert (await _vai(truoc), await _vai(sau)) == ("officer", "officer")
        assert await _con_hieu_luc(g_truoc) and await _con_hieu_luc(g_sau)
        bang, chay = await _casbin_g(truoc)
        assert "role:officer" not in bang and "role:officer" not in chay, (bang, chay)
        bang, chay = await _casbin_g(sau)
        assert "role:officer" in bang and "role:officer" in chay, (bang, chay)
        # Thử lại khi nhật ký đã ghi được.
        tiem["bat"] = False
        r = await c.request("DELETE", "/api/admin/roles/role:officer/users", headers=h, json=than)
        assert r.status_code == 200, r.text
    finally:
        await c.aclose()
    for uid, gid in ((truoc, g_truoc), (sau, g_sau)):
        assert await _vai(uid) == "user", uid
        bang, chay = await _casbin_g(uid)
        assert "role:officer" not in bang and "role:officer" not in chay and "role:user" in chay, (uid, bang, chay)
        assert await _thu_hoi_cua(gid) == [{
            "da_thu_hoi": True, "revoked_by_user_id": admin_user_in_db["id"], "actor_user_id": admin_user_in_db["id"],
            "reason": LY_DO_NGUOI_DUNG, "co_luc": True,
        }], uid


# ---------------------------------------------------------------------------------------------------- điểm chặn 4
async def test_lien_ket_ctv_ma_tai_khoan_vua_thanh_can_bo_va_duoc_cap_quyen_thi_tu_choi_404(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    t = await tao_nguoi("prb_l2_ctv_dich", "user", lo_config["unit_id"])
    diem = Diem()
    boc(monkeypatch, collaborator_service, "create_collaborator", diem, truoc=True)  # SAU cổng deps, TRƯỚC khi ghi vai
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        viec = asyncio.create_task(ca.post("/api/collaborators", headers=ha, json={
            "full_name": "CTV PR-B lượt 2", "phone": "0912000777", "user_id": t["id"], "unit_id": lo_config["unit_id"],
        }))
        await asyncio.wait_for(diem.toi.wait(), 30)
        h = await dn(client, admin_user_in_db)
        r = await client.put(f"/api/admin/users/{t['id']}", headers=h, data={"role": "officer"})
        assert r.status_code == 200, r.text  # đã commit
        gid = await cap(client, admin_user_in_db, t["id"], lo_config["unit_id"], verify=True)
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 404 and r.json()["detail"] == f"User {t['id']} not found", r.text
    assert await _vai(t["id"]) == "officer"
    assert await _con_hieu_luc(gid)
    assert await mot("SELECT count(*) FROM collaborator WHERE user_id = :u", u=t["id"]) == 0


async def _goi_nhan(nhan, ham):
    NHAN.set(nhan)
    return await ham()


async def test_lien_ket_ctv_giu_khoa_dong_nguoi_tu_luc_doc_lai_toi_luc_ghi_vai_doi_vai_phai_cho(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Điểm chặn 4 — phần KHOÁ: yêu cầu liên kết CTV (A) dừng SAU bước đọc lại tài khoản, TRƯỚC khi ghi vai. Lệnh đổi vai
    tài khoản ấy (C, ``PUT`` của Admin) phải bị CHÍNH A chặn (phiên thứ ba, ``pg_blocking_pids``) — nên không thể có "vừa
    thành Cán bộ và được cấp quyền" chen giữa lúc A kiểm và lúc A ghi vai. Thả A ⇒ A liên kết (vai lúc khoá là ``user``) rồi
    C mới đổi vai."""
    from app.repositories.collaborator_repository import CollaboratorRepository

    t = await tao_nguoi("prb_l2_ctv_khoa", "user", lo_config["unit_id"])
    diem = Diem()
    boc(monkeypatch, CollaboratorRepository, "get_by_user_id", diem)  # ngay SAU bước khoá + đọc lại tài khoản
    ca, ha = await dang_nhap(admin_user_in_db)
    cc, hc = await dang_nhap(admin_user_in_db)
    try:
        with PidTheoNhan() as ghi:
            viec_a = asyncio.create_task(_goi_nhan("A", lambda: ca.post("/api/collaborators", headers=ha, json={
                "full_name": "CTV PR-B khoá", "phone": "0912000778", "user_id": t["id"], "unit_id": lo_config["unit_id"],
            })))
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_a = set(ghi.pid.get("A", ()))
            assert pid_a
            viec_c = asyncio.create_task(_goi_nhan("C", lambda: cc.put(
                f"/api/admin/users/{t['id']}", headers=hc, data={"role": "officer"})))
            assert await bi_chan_boi_pid(viec_c, ghi, "C", pid_a) == "chan", "đổi vai phải chờ yêu cầu liên kết CTV"
            diem.di.set()
            r_a = await asyncio.wait_for(viec_a, 30)
            r_c = await asyncio.wait_for(viec_c, 30)
    finally:
        diem.di.set()
        await ca.aclose()
        await cc.aclose()
    assert r_a.status_code == 201, r_a.text
    assert r_c.status_code == 200, r_c.text
    assert await mot("SELECT count(*) FROM collaborator WHERE user_id = :u", u=t["id"]) == 1
    assert await _vai(t["id"]) == "officer"


# ---------------------------------------------------------------------------------------------------- owner câu 1
async def test_vua_khoa_vua_doi_vai_ghi_ca_hai_cau_ly_do(
    client, admin_token_headers, admin_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, admin_user_in_db)
    r = await client.put(
        f"/api/admin/users/{can_bo_cheo['id']}", headers=h, data={"role": "accountant", "status": "inactive"}
    )
    assert r.status_code == 200, r.text
    assert [x["reason"] for x in await _thu_hoi_cua(gid)] == [
        "Tự thu hồi: tài khoản bị khoá; Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Kế toán"
    ]


# ---------------------------------------------------------------------------------------------------- vá nhánh: đọc dưới khoá
async def test_khoa_tai_khoan_quyet_bang_trang_thai_doc_duoi_khoa_khong_bang_ban_doc_dau_yeu_cau(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Yêu cầu A nạp tài khoản lúc đang ``inactive`` rồi dừng; yêu cầu B mở lại (``active``) và Admin cấp quyền chéo MỚI;
    thả A (đặt ``inactive``) ⇒ phải tự thu hồi quyền mới (trạng thái đọc dưới khoá là ``active``). Quyết bằng bản đọc đầu
    yêu cầu (``inactive`` → ``inactive``: "không đổi") ⇒ tài khoản bị khoá mà quyền còn hiệu lực (trái owner câu 2)."""
    t = await tao_nguoi("prb_l2_canbo_cu", "officer", lo_config["unit_id"])
    await sql("UPDATE \"user\" SET status = 'inactive' WHERE id = :u", u=t["id"])
    diem = Diem(lan=1)
    boc(monkeypatch, user_service, "update_user", diem, truoc=True)  # chỉ dừng lần gọi ĐẦU (yêu cầu A)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        viec = asyncio.create_task(ca.put(f"/api/admin/users/{t['id']}", headers=ha, data={"status": "inactive"}))
        await asyncio.wait_for(diem.toi.wait(), 30)
        h = await dn(client, admin_user_in_db)
        r = await client.put(f"/api/admin/users/{t['id']}", headers=h, data={"status": "active"})
        assert r.status_code == 200, r.text
        gid = await cap(client, admin_user_in_db, t["id"], lo_config["unit_id"], verify=True)
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 200, r.text
    assert await mot('SELECT status FROM "user" WHERE id = :u', u=t["id"]) == "inactive"
    assert not await _con_hieu_luc(gid)
    assert [x["reason"] for x in await _thu_hoi_cua(gid)] == [LY_DO_KHOA]
