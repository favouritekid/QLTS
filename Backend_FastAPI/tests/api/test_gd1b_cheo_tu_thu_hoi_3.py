"""GĐ1b PR-B lượt 3 — gỡ vai / xoá vai tuỳ biến: tuần tự theo tài khoản, vai CSDL khớp Casbin, không đảo thứ tự khoá
(Codex lượt 2 PR-B, điểm chặn 3 và 5 / 4.1).

Điểm chặn 3 (``DELETE /api/admin/roles/{role}/users``): ``check_permission`` lấy vai từ ``user.role`` ⇒ vai CSDL phải tính
từ CÙNG tập vai Casbin mà lệnh dùng để ghi.
- Hai lệnh gỡ HAI vai khác nhau của một người chạy chồng nhau ⇒ lệnh sau phải chờ ở DÒNG NGƯỜI (phiên thứ ba,
  ``pg_blocking_pids``) và KHÔNG đọc vai Casbin (bảng ``casbin_rule``) trước khi có khoá; kết quả: vai CSDL = vai Casbin.
- PR-B lượt 4 (Codex lượt 3 điểm chặn 2): mọi quyết định (thu hồi + nhật ký, vai CSDL, dòng ``casbin_rule``) tính từ MỘT
  lần đọc ``casbin_rule`` SAU khoá dòng người; một thao tác CHỈ sửa Casbin commit trước lần đọc ấy được tính vào — tài khoản
  bắt đầu và kết thúc ở Cán bộ ⇒ quyền chéo còn, không nhật ký đổi vai. (Thay ca lượt 3 "chen giữa lúc ghi CSDL và lúc ghi
  Casbin": lượt 4 ghi Casbin TRONG giao dịch, dòng ``casbin_rule`` của người ấy bị khoá ``FOR UPDATE`` tới commit.)
- Vá nhánh cùng khuôn: ``POST /api/admin/users/sync`` cũng khoá dòng người TRƯỚC khi đọc Casbin.

Điểm chặn 5 (``DELETE /api/admin/roles/{role}`` — xoá vai tuỳ biến):
- người đang mang vai bị xoá được đổi sang Cán bộ + cấp quyền chéo SAU lần tìm người của lệnh xoá ⇒ lệnh xoá đọc lại vai
  DƯỚI khoá dòng người, KHÔNG ghi đè thành ``user`` (bản cũ ghi đè, bỏ qua tự thu hồi ⇒ trả vai Cán bộ là dùng lại quyền cũ);
- lệnh đổi vai đang giữ dòng người (chưa tới lock Casbin) ⇒ lệnh xoá vai chờ ở dòng người MÀ KHÔNG giữ lock Casbin; thả lệnh
  đổi vai ⇒ cả hai xong (bản cũ khoá dòng người khi đang giữ lock Casbin ⇒ bế tắc lock asyncio ↔ khoá CSDL).

Mọi phép kiểm đọc CSDL từ phiên riêng.
"""
from __future__ import annotations

import asyncio

import pytest

from app.repositories import document_bulk_repository as bulk_repo
from app.services import document_cross_review_service as cross_service
from tests.api.gd1b_cheo_tro_giup import bi_chan_boi_pid, cap, mot, tao_nguoi  # noqa: F401
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    NHAN,
    Diem,
    PidTheoNhan,
    boc,
    dang_nhap,
    dn,
    goi,
    lo_config,
    lo_routers,
)
from tests.api.test_gd1b_cheo_tu_thu_hoi import _thu_hoi_cua
from tests.api.test_gd1b_cheo_tu_thu_hoi_2 import _casbin_g, _con_hieu_luc, _vai

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _them_vai_casbin(client, admin, uid, vai):
    """Gán thêm một vai CHỈ trong Casbin (``POST /api/admin/roles/assign`` — không đụng vai CSDL)."""
    h = await dn(client, admin)
    r = await client.post("/api/admin/roles/assign", headers=h, json={"user_id": uid, "role": vai})
    assert r.status_code == 201, r.text


async def _go_vai(c, h, uid, vai):
    return await c.request("DELETE", f"/api/admin/roles/{vai}/users", headers=h, json={"user_ids": [uid], "role_to_remove": vai})


async def _dong_bo_nhat_quan(uid):
    bang, chay = await _casbin_g(uid)
    return await _vai(uid), bang, chay


# ---------------------------------------------------------------------------------------------------- điểm chặn 3
async def test_hai_lenh_go_hai_vai_cua_mot_nguoi_tuan_tu_theo_tai_khoan_vai_csdl_khop_casbin(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    u = await tao_nguoi("prb_l3_hai_vai", "manager", lo_config["unit_id"])
    await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:officer")
    assert (await _casbin_g(u["id"]))[0] == {"role:manager", "role:officer"}, "tiền đề: hai vai trong casbin_rule"
    diem = Diem()
    boc(monkeypatch, bulk_repo, "lock_user_no_key_update", diem)  # P dừng NGAY SAU lần khoá dòng người đầu tiên
    cp, hp = await dang_nhap(admin_user_in_db)
    cq, hq = await dang_nhap(admin_user_in_db)
    try:
        with PidTheoNhan() as ghi:
            viec_p = asyncio.create_task(goi("P", lambda: _go_vai(cp, hp, u["id"], "role:manager")))
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_p = set(ghi.pid.get("P", ()))
            assert pid_p
            viec_q = asyncio.create_task(goi("Q", lambda: _go_vai(cq, hq, u["id"], "role:officer")))
            assert await bi_chan_boi_pid(viec_q, ghi, "Q", pid_p) == "chan", "lệnh gỡ vai thứ hai phải chờ ở dòng người"
            doc_casbin = [c for c in ghi.cau.get("Q", ()) if "casbin_rule" in c]
            assert not doc_casbin, "lệnh thứ hai đọc vai Casbin TRƯỚC khi có khoá dòng người (không tuần tự theo tài khoản)"
            diem.di.set()
            r_p = await asyncio.wait_for(viec_p, 30)
            r_q = await asyncio.wait_for(viec_q, 30)
    finally:
        diem.di.set()
        await cp.aclose()
        await cq.aclose()
    assert r_p.status_code == 200 and r_q.status_code == 200, (r_p.text, r_q.text)
    assert await _dong_bo_nhat_quan(u["id"]) == ("user", {"role:user"}, {"role:user"})


async def test_go_vai_quyet_tu_mot_lan_doc_casbin_rule_sau_khoa_bat_dau_va_ket_thuc_o_can_bo_quyen_cheo_con(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Codex lượt 3 điểm chặn 2. Tài khoản ở Cán bộ (CSDL ``officer``, quyền chéo còn hiệu lực); CHỈ Casbin đổi
    ``role:officer`` thành ``role:manager`` (owner câu 7: không đổi vai CSDL, không thu hồi). Lệnh gỡ ``role:manager`` (P)
    dừng NGAY SAU khoá dòng người, TRƯỚC khi đọc ``casbin_rule``; trong lúc ấy CHỈ Casbin gán lại ``role:officer`` (commit).
    Thả P ⇒ P đọc {manager, officer} ⇒ vai cuối vẫn Cán bộ ⇒ KHÔNG thu hồi, KHÔNG nhật ký; Casbin còn {officer}. Quyết thu
    hồi từ một lần đọc TRƯỚC khoá (rồi mới đọc lại để ghi Casbin) ⇒ quyền chéo bị thu hồi + nhật ký đổi vai dù vai cuối vẫn
    là Cán bộ."""
    u = await tao_nguoi("prb_l4_can_bo_giu", "officer", lo_config["unit_id"])
    gid = await cap(client, admin_user_in_db, u["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, admin_user_in_db)
    r = await client.request("DELETE", "/api/admin/roles/revoke", headers=h, json={"user_id": u["id"], "role": "role:officer"})
    assert r.status_code == 200, r.text
    await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:manager")
    assert await _dong_bo_nhat_quan(u["id"]) == ("officer", {"role:manager"}, {"role:manager"}), "tiền đề"
    diem = Diem()
    boc(monkeypatch, bulk_repo, "lock_user_no_key_update", diem)  # P dừng NGAY SAU khoá dòng người
    cp, hp = await dang_nhap(admin_user_in_db)
    try:
        viec = asyncio.create_task(_go_vai(cp, hp, u["id"], "role:manager"))
        await asyncio.wait_for(diem.toi.wait(), 30)
        await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:officer")
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await cp.aclose()
    assert r.status_code == 200, r.text
    assert await _dong_bo_nhat_quan(u["id"]) == ("officer", {"role:officer"}, {"role:officer"})
    assert await _con_hieu_luc(gid)
    assert await _thu_hoi_cua(gid) == [
        {"da_thu_hoi": False, "revoked_by_user_id": None, "actor_user_id": None, "reason": None, "co_luc": False}
    ], "không được có nhật ký thu hồi"


async def test_dong_bo_vai_tu_casbin_cho_lenh_doi_vai_dang_giu_dong_nguoi_roi_moi_doc_casbin(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Vá nhánh cùng khuôn điểm chặn 3 — ``POST /api/admin/users/sync`` (vai CSDL ← Casbin). Tài khoản lệch sẵn: CSDL
    ``user``, Casbin {user, officer}. Lệnh đổi vai sang Quản lý (C, ``PUT``) đã khoá dòng người, dừng TRƯỚC khi ghi Casbin.
    Lượt đồng bộ (S) phải chờ ở dòng người (phiên thứ ba, ``pg_blocking_pids``); thả C ⇒ S đọc Casbin SAU C = {officer,
    manager} ⇒ vai CSDL ``manager``. Đọc Casbin TRƯỚC khi có khoá ⇒ ghi đè ``officer`` lên vai Quản lý vừa đổi."""
    u = await tao_nguoi("prb_l3_dong_bo", "user", lo_config["unit_id"])
    await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:officer")
    diem = Diem()
    boc(monkeypatch, cross_service, "revoke_grants_on_account_change", diem)  # C dừng SAU khoá dòng người
    cc, hc = await dang_nhap(admin_user_in_db)
    cs, hs = await dang_nhap(admin_user_in_db)
    try:
        with PidTheoNhan() as ghi:
            viec_c = asyncio.create_task(goi("C", lambda: cc.put(f"/api/admin/users/{u['id']}", headers=hc, data={"role": "manager"})))
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_c = set(ghi.pid.get("C", ()))
            assert pid_c
            viec_s = asyncio.create_task(goi("S", lambda: cs.post("/api/admin/users/sync", headers=hs, json={"user_ids": [u["id"]]})))
            assert await bi_chan_boi_pid(viec_s, ghi, "S", pid_c) == "chan", "lượt đồng bộ phải chờ ở dòng người"
            diem.di.set()
            r_c = await asyncio.wait_for(viec_c, 30)
            r_s = await asyncio.wait_for(viec_s, 30)
    finally:
        diem.di.set()
        await cc.aclose()
        await cs.aclose()
    assert r_c.status_code == 200 and r_s.status_code == 200, (r_c.text, r_s.text)
    # Vai CSDL = vai C vừa đặt, và đó là vai cao nhất Casbin đang có (``PUT`` thay bộ vai Casbin của người ấy — đo 21-11:
    # còn {role:manager}); lượt đồng bộ đọc Casbin TRƯỚC C sẽ ghi đè ``officer``.
    vai, bang, chay = await _dong_bo_nhat_quan(u["id"])
    assert vai == "manager" and bang == chay and "role:manager" in chay, (vai, bang, chay)


# ---------------------------------------------------------------------------------------------------- điểm chặn 5 (4.1)
async def _vai_tuy_bien(client, admin, ten):
    h = await dn(client, admin)
    r = await client.post(
        "/api/admin/roles/policies", headers=h, json={"subject": f"role:{ten}", "object": f"/api/{ten}/*", "action": "GET"}
    )
    assert r.status_code == 201, r.text


async def _vai_con_policy(ten):
    return await mot("SELECT count(*) FROM casbin_rule WHERE ptype = 'p' AND v0 = :v", v=f"role:{ten}")


async def test_xoa_vai_tuy_bien_doc_lai_vai_duoi_khoa_khong_ghi_de_nguoi_vua_thanh_can_bo(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Lệnh xoá vai (A) đã tìm thấy người mang vai rồi dừng (chưa khoá gì). Admin đổi người ấy sang Cán bộ + cấp quyền duyệt
    chéo (commit). Thả A ⇒ A khoá + đọc lại vai = Cán bộ ⇒ KHÔNG đổi sang ``user``; quyền chéo còn nguyên."""
    from app.repositories.user_repository import UserRepository

    ten = "prb_l3_tb_a"
    await _vai_tuy_bien(client, admin_user_in_db, ten)
    o = await tao_nguoi("prb_l3_tb_nguoi_a", ten, lo_config["unit_id"])
    diem = Diem()
    boc(monkeypatch, UserRepository, "get_by_db_role", diem)  # A dừng SAU lần tìm người mang vai (chưa khoá dòng nào)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        viec = asyncio.create_task(ca.request("DELETE", f"/api/admin/roles/role:{ten}", headers=ha))
        await asyncio.wait_for(diem.toi.wait(), 30)
        h = await dn(client, admin_user_in_db)
        r = await client.put(f"/api/admin/users/{o['id']}", headers=h, data={"role": "officer"})
        assert r.status_code == 200, r.text
        gid = await cap(client, admin_user_in_db, o["id"], lo_config["unit_id"], verify=True)
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 200, r.text
    assert await _vai(o["id"]) == "officer"
    assert await _con_hieu_luc(gid)
    assert await _vai_con_policy(ten) == 0


async def test_xoa_vai_tuy_bien_cho_khoa_dong_nguoi_ma_khong_giu_lock_casbin(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Lệnh đổi vai (C, ``PUT``) đã khoá dòng người, dừng TRƯỚC lock Casbin. Lệnh xoá vai (A) phải chờ ở DÒNG NGƯỜI (phiên
    thứ ba, ``pg_blocking_pids``) mà KHÔNG giữ lock Casbin; thả C ⇒ C lấy được lock Casbin, cả hai xong. Giữ lock Casbin khi
    chờ khoá CSDL ⇒ C chờ lock Casbin, A chờ dòng người của C ⇒ bế tắc (PostgreSQL không phát hiện được)."""
    ten = "prb_l3_tb_b"
    await _vai_tuy_bien(client, admin_user_in_db, ten)
    o = await tao_nguoi("prb_l3_tb_nguoi_b", ten, lo_config["unit_id"])
    diem = Diem()
    boc(monkeypatch, cross_service, "revoke_grants_on_account_change", diem)  # C dừng SAU khoá dòng người
    cc, hc = await dang_nhap(admin_user_in_db)
    ca, ha = await dang_nhap(admin_user_in_db)
    viec_c = viec_a = None
    try:
        with PidTheoNhan() as ghi:
            viec_c = asyncio.create_task(goi("C", lambda: cc.put(f"/api/admin/users/{o['id']}", headers=hc, data={"role": "officer"})))
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_c = set(ghi.pid.get("C", ()))
            assert pid_c
            viec_a = asyncio.create_task(goi("A", lambda: ca.request("DELETE", f"/api/admin/roles/role:{ten}", headers=ha)))
            assert await bi_chan_boi_pid(viec_a, ghi, "A", pid_c) == "chan", "lệnh xoá vai phải chờ ở dòng người"
            diem.di.set()
            try:
                r_c, r_a = await asyncio.wait_for(asyncio.gather(viec_c, viec_a), 30)
            except asyncio.TimeoutError:
                pytest.fail("bế tắc: lệnh xoá vai giữ lock Casbin trong lúc chờ khoá dòng người của lệnh đổi vai")
    finally:
        diem.di.set()
        for v in (viec_c, viec_a):
            if v is not None and not v.done():
                v.cancel()
        await asyncio.gather(*(v for v in (viec_c, viec_a) if v is not None), return_exceptions=True)
        await cc.aclose()
        await ca.aclose()
    assert r_c.status_code == 200 and r_a.status_code == 200, (r_c.text, r_a.text)
    vai, bang, chay = await _dong_bo_nhat_quan(o["id"])
    assert vai == "officer" and "role:officer" in chay and f"role:{ten}" not in chay, (vai, bang, chay)
    assert await _vai_con_policy(ten) == 0
