"""GĐ1b PR-B lượt 4 — vai Casbin quyết từ bảng ``casbin_rule`` (nguồn chung mọi worker), đối tượng làm mới dưới khoá, thứ
tự khoá xoá vai tuỳ biến (Codex lượt 3 PR-B, điểm chặn 1, 3, 5).

Điểm chặn 1: mỗi worker Gunicorn có enforcer RIÊNG trong bộ nhớ (``admin_v2_casbin.py``). Ca dùng HAI enforcer độc lập:
worker 1 = enforcer của ứng dụng; worker 2 = một ``AsyncEnforcer`` thứ hai nạp từ CSDL TRƯỚC khi worker 1 đổi Casbin (bản
cũ), gắn vào ứng dụng cho yêu cầu kế (``app.state.enforcer``) — yêu cầu đi qua HTTP thật.
- gỡ vai ở worker 2 không ghi lại vai worker 1 vừa gỡ;
- đồng bộ vai ở worker 2 không ghi lại vai worker 1 vừa gỡ;
- vá nhánh: ``PUT`` đổi vai ở worker 2 gỡ HẾT vai cũ trong ``casbin_rule`` (kể cả vai worker 1 vừa gán) — ghi bảng trong
  giao dịch, theo các dòng đọc + khoá ở chính bảng ấy.

Codex lượt 4 (C1a, C2): ``PUT`` đổi vai mà bước ghi ``casbin_rule`` lỗi ⇒ 500, không commit gì (vai CSDL, bảng quyền, quyền
chéo, nhật ký giữ nguyên); gỡ vai xoá ĐÚNG các dòng đã đọc + khoá — dòng cùng cặp chèn + commit sau lần đọc còn nguyên.

``PUT`` CHỈ đổi đơn vị (owner câu 4): giữ quyền chéo, ``casbin_rule`` nguyên, không nhật ký thu hồi; và không ghi đè vai mà
một lệnh đổi vai khác vừa commit (đường đổi đơn vị ghi cả ``user.role`` — phải là vai đọc dưới khoá).

Điểm chặn 3: đồng bộ vai nạp đối tượng người dùng TRƯỚC khoá; vai CSDL đổi giữa lúc nạp và lúc khoá ⇒ phải GHI thật (đọc
lại vai từ phiên CSDL mới), không chỉ tăng ``synced_count``.

Điểm chặn 5: xoá vai tuỳ biến giữ khoá người id LỚN, rồi phát hiện thêm người id NHỎ hơn ⇒ phải bảo toàn thứ tự khoá tăng
(không giữ id lớn chờ id nhỏ) — không bế tắc với đồng bộ vai đi chiều tăng (phiên thứ ba ``pg_blocking_pids``).

Mọi phép kiểm đọc CSDL từ phiên riêng.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.repositories.user_repository import UserRepository
from app.services import casbin_service, user_service
from tests.api.gd1b_cheo_tro_giup import bi_chan_boi_pid, cap, hang, mot, tao_nguoi  # noqa: F401
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
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
from tests.api.test_gd1b_cheo_tu_thu_hoi import _client_500, _thu_hoi_cua
from tests.api.test_gd1b_cheo_tu_thu_hoi_2 import _casbin_g, _con_hieu_luc, _vai
from tests.api.test_gd1b_cheo_tu_thu_hoi_3 import _go_vai, _them_vai_casbin, _vai_con_policy, _vai_tuy_bien

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

MO_HINH = Path(__file__).resolve().parents[2] / "auth_model.conf"


async def _enforcer_worker_hai():
    """Enforcer RIÊNG (như worker Gunicorn thứ hai): nạp từ CSDL ở THỜI ĐIỂM GỌI, sau đó không tự cập nhật."""
    import casbin
    from casbin_async_sqlalchemy_adapter import Adapter

    import app.database as csdl

    e = casbin.AsyncEnforcer(str(MO_HINH), Adapter(csdl.engine))
    await e.load_policy()
    return e


async def _bang(uid):
    return (await _casbin_g(uid))[0]


async def _hai_vai_roi_worker_mot_go_manager(client, admin, unit_id, ten):
    """Người có hai vai Casbin {manager, officer} (CSDL manager); worker 2 nạp bản ấy; worker 1 gỡ ``role:manager`` ⇒ CSDL
    officer, ``casbin_rule`` {officer}. Trả (người, enforcer worker 2 — vẫn thấy {manager, officer})."""
    u = await tao_nguoi(ten, "manager", unit_id)
    await _them_vai_casbin(client, admin, u["id"], "role:officer")
    e2 = await _enforcer_worker_hai()
    h = await dn(client, admin)
    r = await _go_vai(client, h, u["id"], "role:manager")
    assert r.status_code == 200, r.text
    assert (await _vai(u["id"]), await _bang(u["id"])) == ("officer", {"role:officer"}), "tiền đề: worker 1 đã gỡ"
    assert set(await e2.get_roles_for_user(f"user:{u['id']}")) == {"role:manager", "role:officer"}, "tiền đề: worker 2 cũ"
    return u, e2


# ---------------------------------------------------------------------------------------------------- điểm chặn 1
async def test_hai_worker_go_vai_o_worker_hai_bo_nho_cu_khong_ghi_lai_vai_worker_mot_vua_go(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    from app.main import fastapi_app

    u, e2 = await _hai_vai_roi_worker_mot_go_manager(client, admin_user_in_db, lo_config["unit_id"], "prb_l4_w_go")
    monkeypatch.setattr(fastapi_app.state, "enforcer", e2)
    h = await dn(client, admin_user_in_db)
    r = await _go_vai(client, h, u["id"], "role:officer")
    assert r.status_code == 200, r.text
    # Quyết từ bộ nhớ worker 2 ⇒ còn {manager} ⇒ CSDL ghi lại ``manager`` (quyền Quản lý qua ``check_permission``).
    assert (await _vai(u["id"]), await _bang(u["id"])) == ("user", {"role:user"})


async def test_hai_worker_dong_bo_vai_o_worker_hai_bo_nho_cu_khong_ghi_lai_vai_worker_mot_vua_go(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    from app.main import fastapi_app

    u, e2 = await _hai_vai_roi_worker_mot_go_manager(client, admin_user_in_db, lo_config["unit_id"], "prb_l4_w_db")
    monkeypatch.setattr(fastapi_app.state, "enforcer", e2)
    h = await dn(client, admin_user_in_db)
    r = await client.post("/api/admin/users/sync", headers=h, json={"user_ids": [u["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["synced_count"] == 0, r.json()
    assert (await _vai(u["id"]), await _bang(u["id"])) == ("officer", {"role:officer"})


async def test_hai_worker_doi_vai_put_o_worker_hai_go_het_vai_cu_trong_casbin_rule(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Vá nhánh cùng khuôn: ``PUT`` đổi vai từng gỡ "mọi vai cũ" theo ảnh trong bộ nhớ worker (rồi dọn thêm đúng vai cũ
    trong ``user.role``) — worker 2 chưa thấy ``role:manager`` worker 1 vừa gán ⇒ dòng ấy sót lại trong ``casbin_rule`` (vai
    CSDL accountant, Casbin {manager, accountant}). Nay gỡ mọi dòng đọc + khoá ở chính bảng."""
    from app.main import fastapi_app

    u = await tao_nguoi("prb_l4_w_put", "officer", lo_config["unit_id"])
    e2 = await _enforcer_worker_hai()
    await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:manager")
    assert await _bang(u["id"]) == {"role:officer", "role:manager"}, "tiền đề: worker 1 gán thêm"
    assert set(await e2.get_roles_for_user(f"user:{u['id']}")) == {"role:officer"}, "tiền đề: worker 2 cũ"
    monkeypatch.setattr(fastapi_app.state, "enforcer", e2)
    h = await dn(client, admin_user_in_db)
    r = await client.put(f"/api/admin/users/{u['id']}", headers=h, data={"role": "accountant"})
    assert r.status_code == 200, r.text
    assert (await _vai(u["id"]), await _bang(u["id"])) == ("accountant", {"role:accountant"})


# ---------------------------------------------------------------------------------------------------- điểm chặn 3
async def test_dong_bo_vai_doi_tuong_nap_truoc_khoa_van_ghi_vai_moi_doc_tu_phien_moi(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Lượt đồng bộ (S) nạp đối tượng người dùng (vai ``officer``) rồi dừng — TRƯỚC khoá. Vai CSDL đổi sang ``manager``
    (commit, Casbin vẫn {officer}). Thả S ⇒ S khoá, thấy ``manager`` ≠ Casbin ⇒ phải GHI ``officer`` thật. Gán vào đối
    tượng nạp trước khoá (vai ``officer`` cũ) ⇒ ORM bỏ UPDATE, CSDL giữ ``manager`` mà ``synced_count`` vẫn = 1."""
    u = await tao_nguoi("prb_l4_dong_bo_cu", "officer", lo_config["unit_id"])
    cs, hs = await dang_nhap(admin_user_in_db)
    diem = Diem()
    boc(monkeypatch, UserRepository, "get_by_ids", diem)  # S dừng SAU khi nạp đối tượng người dùng
    try:
        viec = asyncio.create_task(cs.post("/api/admin/users/sync", headers=hs, json={"user_ids": [u["id"]]}))
        await asyncio.wait_for(diem.toi.wait(), 30)
        await sql("UPDATE \"user\" SET role = 'manager' WHERE id = :u", u=u["id"])
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await cs.aclose()
    assert r.status_code == 200 and r.json()["synced_count"] == 1, r.text
    assert await mot('SELECT role FROM "user" WHERE id = :u', u=u["id"]) == "officer"


# ---------------------------------------------------------------------------------------------------- điểm chặn 5
async def test_xoa_vai_tuy_bien_tap_nguoi_mo_rong_id_nho_hon_bao_toan_thu_tu_khoa_khong_be_tac_voi_dong_bo(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """Lệnh xoá vai (A) đã khoá người H (id lớn, mang vai) rồi dừng ở đầu bước kiểm lại. Người L (id NHỎ hơn) được gán vai
    ấy (CSDL + ``casbin_rule``, commit). Lượt đồng bộ (S) khoá L rồi chờ H — phiên thứ ba xác nhận S bị CHÍNH A chặn. Thả A
    ⇒ A thấy L chưa khoá, id nhỏ hơn H ⇒ nhả khoá (rollback savepoint) và khoá lại theo id tăng ⇒ S xong, A xong (cả hai
    200). Khoá thêm L khi vẫn giữ H ⇒ A chờ L (S giữ), S chờ H (A giữ) ⇒ PostgreSQL phát hiện bế tắc, huỷ một bên (500)."""
    ten = "prb_l4_tb_thu_tu"
    await _vai_tuy_bien(client, admin_user_in_db, ten)
    nho = await tao_nguoi("prb_l4_thu_tu_l", "user", lo_config["unit_id"])
    lon = await tao_nguoi("prb_l4_thu_tu_h", ten, lo_config["unit_id"])
    assert nho["id"] < lon["id"]
    ca, ha = await dang_nhap(admin_user_in_db)
    cs, hs = await dang_nhap(admin_user_in_db)
    diem = Diem()
    boc(monkeypatch, casbin_service, "dong_bo_tu_nguon_ben_vung", diem, truoc=True)  # A dừng ở đầu bước kiểm lại
    viec_a = viec_s = None
    try:
        with PidTheoNhan() as ghi:
            viec_a = asyncio.create_task(goi("A", lambda: ca.request("DELETE", f"/api/admin/roles/role:{ten}", headers=ha)))
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_a = set(ghi.pid.get("A", ()))
            assert pid_a
            await sql("UPDATE \"user\" SET role = :r WHERE id = :u", r=ten, u=nho["id"])
            await sql("INSERT INTO casbin_rule (ptype, v0, v1) VALUES ('g', :s, :r)", s=f"user:{nho['id']}", r=f"role:{ten}")
            viec_s = asyncio.create_task(goi("S", lambda: cs.post(
                "/api/admin/users/sync", headers=hs, json={"user_ids": [nho["id"], lon["id"]]})))
            assert await bi_chan_boi_pid(viec_s, ghi, "S", pid_a) == "chan", "đồng bộ (đã giữ L) phải chờ dòng H mà A giữ"
            diem.di.set()
            r_a, r_s = await asyncio.wait_for(asyncio.gather(viec_a, viec_s), 60)
    finally:
        diem.di.set()
        for v in (viec_a, viec_s):
            if v is not None and not v.done():
                v.cancel()
        await asyncio.gather(*(v for v in (viec_a, viec_s) if v is not None), return_exceptions=True)
        await ca.aclose()
        await cs.aclose()
    assert r_a.status_code == 200 and r_s.status_code == 200, (r_a.text, r_s.text)
    # Đọc lại CẢ HAI người + dòng gán vai từ phiên CSDL MỚI: không ai còn vai đã xoá (CSDL lẫn ``casbin_rule``); L đã được
    # lượt đồng bộ đưa về ``user`` (Casbin {user, X} ⇒ ``user``), H được lệnh xoá đổi sang ``user`` + gán ``role:user``.
    assert (await _vai(nho["id"]), await _bang(nho["id"])) == ("user", {"role:user"})
    assert (await _vai(lon["id"]), await _bang(lon["id"])) == ("user", {"role:user"})
    assert await mot("SELECT count(*) FROM casbin_rule WHERE ptype = 'g' AND v1 = :r", r=f"role:{ten}") == 0
    assert await _vai_con_policy(ten) == 0


# ---------------------------------------------------------------------------------------------------- Codex lượt 4 (C1a, C2)
async def test_put_doi_vai_ghi_casbin_rule_loi_thi_vai_csdl_casbin_quyen_cheo_nhat_ky_giu_nguyen(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """C1a: ``PUT`` đổi vai Cán bộ → Kế toán; bước ghi bảng ``casbin_rule`` lỗi ⇒ 500 lỗi chung rõ ràng, KHÔNG commit gì:
    vai CSDL vẫn ``officer``, ``casbin_rule`` vẫn {officer}, quyền chéo còn, không nhật ký tự thu hồi. Nuốt lỗi đồng bộ (bản
    cũ: chỉ ghi log) ⇒ 200, vai CSDL đổi + quyền bị thu hồi mà bảng quyền lệch."""
    u = await tao_nguoi("prb_l4_put_loi", "officer", lo_config["unit_id"])
    gid = await cap(client, admin_user_in_db, u["id"], lo_config["unit_id"], verify=True)
    goc = UserRepository.add_grouping
    tiem = []

    async def hong(self, user_id, role):
        if user_id == u["id"]:
            tiem.append(role)
            raise RuntimeError("tiêm lỗi ghi casbin_rule")
        return await goc(self, user_id, role)

    monkeypatch.setattr(UserRepository, "add_grouping", hong)
    c, h = await _client_500(admin_user_in_db)
    try:
        r = await c.put(f"/api/admin/users/{u['id']}", headers=h, data={"role": "accountant"})
    finally:
        await c.aclose()
    assert tiem == ["role:accountant"], "tiền đề: lỗi phải được tiêm ĐÚNG bước ghi bảng quyền của người này"
    assert r.status_code == 500 and r.json()["error_code"] == "INTERNAL_ERROR", r.text
    assert (await _vai(u["id"]), await _bang(u["id"])) == ("officer", {"role:officer"})
    assert await _con_hieu_luc(gid)
    assert await _thu_hoi_cua(gid) == [
        {"da_thu_hoi": False, "revoked_by_user_id": None, "actor_user_id": None, "reason": None, "co_luc": False}
    ]


async def test_go_vai_dong_casbin_cung_cap_chen_va_commit_sau_lan_doc_van_con(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers
):
    """C2: lệnh gỡ ``role:manager`` (P) đã đọc + khoá các dòng gán vai của người ấy rồi dừng; một dòng CÙNG CẶP (người,
    ``role:manager``) được chèn + commit (như worker khác gán lại). Thả P ⇒ P xoá ĐÚNG dòng đã đọc (theo id) — dòng mới
    còn. Xoá theo cặp (người, vai) ⇒ xoá luôn dòng đến sau."""
    u = await tao_nguoi("prb_l4_cung_cap", "manager", lo_config["unit_id"])
    cu = await mot("SELECT id FROM casbin_rule WHERE ptype = 'g' AND v0 = :s AND v1 = 'role:manager'", s=f"user:{u['id']}")
    diem = Diem()
    boc(monkeypatch, UserRepository, "lock_grouping_rows", diem)  # P dừng SAU khi đọc + khoá các dòng gán vai
    cp, hp = await dang_nhap(admin_user_in_db)
    try:
        viec = asyncio.create_task(_go_vai(cp, hp, u["id"], "role:manager"))
        await asyncio.wait_for(diem.toi.wait(), 30)
        await sql("INSERT INTO casbin_rule (ptype, v0, v1) VALUES ('g', :s, 'role:manager')", s=f"user:{u['id']}")
        moi = await mot(
            "SELECT max(id) FROM casbin_rule WHERE ptype = 'g' AND v0 = :s AND v1 = 'role:manager'", s=f"user:{u['id']}"
        )
        assert moi != cu
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await cp.aclose()
    assert r.status_code == 200, r.text
    assert await mot("SELECT count(*) FROM casbin_rule WHERE id = :i", i=cu) == 0, "dòng đã đọc phải bị xoá"
    assert await mot("SELECT count(*) FROM casbin_rule WHERE id = :i", i=moi) == 1, "dòng cùng cặp chèn sau lần đọc phải còn"


# ---------------------------------------------------------------------------------------------------- PUT chỉ đổi đơn vị
async def test_put_chi_doi_don_vi_giu_quyen_cheo_casbin_rule_khong_nhat_ky_thu_hoi(
    client, admin_user_in_db, seed_other_unit, lo_config, lo_routers
):
    """Owner câu 4: Cán bộ chuyển đơn vị ⇒ GIỮ quyền đã cấp (áp cho đúng đơn vị ghi trên quyền), vai giữ Cán bộ, bảng
    ``casbin_rule`` không đổi, không nhật ký tự thu hồi. Đọc lại mọi thứ từ phiên CSDL mới."""
    u = await tao_nguoi("prb_l4_chi_doi_dv", "officer", lo_config["unit_id"])
    gid = await cap(client, admin_user_in_db, u["id"], lo_config["unit_id"], verify=True)
    truoc = await mot("SELECT array_agg(id ORDER BY id) FROM casbin_rule WHERE ptype = 'g' AND v0 = :s", s=f"user:{u['id']}")
    h = await dn(client, admin_user_in_db)
    r = await client.put(f"/api/admin/users/{u['id']}", headers=h, data={"unit_id": seed_other_unit["unit_id"]})
    assert r.status_code == 200, r.text
    assert await _vai(u["id"]) == "officer"
    assert await mot('SELECT unit_id FROM "user" WHERE id = :u', u=u["id"]) == seed_other_unit["unit_id"]
    assert await _bang(u["id"]) == {"role:officer"}
    assert await mot(
        "SELECT array_agg(id ORDER BY id) FROM casbin_rule WHERE ptype = 'g' AND v0 = :s", s=f"user:{u['id']}"
    ) == truoc, "dòng casbin_rule phải giữ nguyên (không xoá / chèn lại)"
    assert await _con_hieu_luc(gid)
    assert await _thu_hoi_cua(gid) == [
        {"da_thu_hoi": False, "revoked_by_user_id": None, "actor_user_id": None, "reason": None, "co_luc": False}
    ]


async def test_put_chi_doi_don_vi_khong_ghi_de_vai_ma_lenh_doi_vai_khac_vua_commit(
    client, monkeypatch, admin_user_in_db, seed_other_unit, lo_config, lo_routers
):
    """Lệnh đổi đơn vị (A) đã nạp tài khoản (vai ``officer``) rồi dừng TRƯỚC dịch vụ; lệnh đổi vai sang Kế toán (B) commit
    (thu hồi quyền chéo, ``casbin_rule`` = {accountant}). Thả A ⇒ A khoá + đọc lại vai = ``accountant`` ⇒ chỉ đổi đơn vị.
    Tính từ bản nạp đầu yêu cầu ⇒ đường đổi đơn vị ghi vai cũ ``officer`` vào bản ghi phân công mới (``user_unit_assignment``)
    trong khi vai CSDL / Casbin là Kế toán."""
    u = await tao_nguoi("prb_l4_dv_ghi_de", "officer", lo_config["unit_id"])
    diem = Diem(lan=1)
    boc(monkeypatch, user_service, "update_user", diem, truoc=True)  # chỉ dừng lần gọi ĐẦU (yêu cầu A)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        viec = asyncio.create_task(ca.put(f"/api/admin/users/{u['id']}", headers=ha, data={"unit_id": seed_other_unit["unit_id"]}))
        await asyncio.wait_for(diem.toi.wait(), 30)
        h = await dn(client, admin_user_in_db)
        r = await client.put(f"/api/admin/users/{u['id']}", headers=h, data={"role": "accountant"})
        assert r.status_code == 200, r.text
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 200, r.text
    assert await _vai(u["id"]) == "accountant"
    assert await mot('SELECT unit_id FROM "user" WHERE id = :u', u=u["id"]) == seed_other_unit["unit_id"]
    assert await _bang(u["id"]) == {"role:accountant"}
    # Kiểm ngược l4_m7b (22-11): ``user.role`` KHÔNG bị ghi đè dù A tính từ bản cũ — ORM bỏ UPDATE khi gán trùng giá trị đã
    # nạp. Chỗ vai cũ thực sự bị ghi là BẢN GHI PHÂN CÔNG mới A tạo (``user_unit_assignment.role``, nơi các bộ lọc theo đơn
    # vị đọc vai): phải là vai HIỆN HÀNH ``accountant``, đúng một bản ghi còn hiệu lực.
    assert await hang(
        "SELECT role, unit_id FROM user_unit_assignment WHERE user_id = :u AND is_active", u=u["id"]
    ) == [{"role": "accountant", "unit_id": seed_other_unit["unit_id"]}]
