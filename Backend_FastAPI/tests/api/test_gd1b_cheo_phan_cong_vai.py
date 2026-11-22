"""GĐ1b PR-B lượt 5 — Codex 22-11 B-P1 / B-P3: đổi vai CSDL phải đổi CẢ bản ghi phân công đang hiệu lực.

``user_unit_assignment`` là NGUỒN CHUẨN của vai + đơn vị (``app/models/user_unit_assignment.py``: "``user.role`` và
``user.unit_id`` chỉ là bản sao"); quy ước thời gian: đổi vai ⇒ bản ghi cũ đóng lại (``is_active = false``, có
``end_date``), bản ghi MỚI mang vai mới. Bộ chọn người nhận thông báo theo vai (``notification_resolvers`` —
``UnitManagersResolver`` / ``UnitStaffResolver``) đọc ở bảng ấy, không đọc ``user.role``.

Trước lượt 5: gỡ vai (``DELETE /api/admin/roles/{role}/users``), đồng bộ vai (``POST /api/admin/users/sync``), xoá vai tuỳ
biến (``DELETE /api/admin/roles/{role}``) và gắn tài khoản vào CTV (``POST /api/collaborators``) chỉ ghi ``user.role`` ⇒ bản
ghi phân công còn mang vai cũ ⇒ người vừa bị gỡ vai Quản lý vẫn được chọn làm người nhận thông báo của Quản lý đơn vị.
Nay cả bốn đường đi qua ĐÚNG hàm ``PUT`` đổi vai dùng (``user_service._create_or_update_user_assignment``).

Dữ liệu CÓ phân công đang hiệu lực (dựng bằng SQL như bản ghi ``create_user_by_admin`` để lại). Mọi phép kiểm đọc CSDL từ
PHIÊN MỚI (``mot`` / ``hang`` / phiên ``AsyncSessionLocal`` riêng cho bộ chọn người nhận). Mỗi ca một bất biến.
"""
from __future__ import annotations

import pytest

from app.database import AsyncSessionLocal
from tests.api.gd1b_cheo_tro_giup import hang, mot, tao_nguoi
from tests.api.gd1b_lo_tro_giup import dn, lo_config, lo_routers, sql  # noqa: F401
from tests.api.test_gd1b_cheo_tu_thu_hoi_2 import _vai
from tests.api.test_gd1b_cheo_tu_thu_hoi_3 import _go_vai, _them_vai_casbin, _vai_tuy_bien

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _phan_cong(uid, vai, unit_id):
    """Một bản ghi phân công ĐANG HIỆU LỰC cho người ``uid`` (vai ``vai`` ở đơn vị ``unit_id``) + con trỏ
    ``current_assignment_id`` — đúng dạng ``_create_or_update_user_assignment`` để lại khi tạo tài khoản có đơn vị."""
    await sql(
        "INSERT INTO user_unit_assignment (user_id, unit_id, role, start_date, is_active, created_at, updated_at) "
        "VALUES (:u, :d, :r, now(), true, now(), now())",
        u=uid,
        d=unit_id,
        r=vai,
    )
    await sql(
        'UPDATE "user" SET current_assignment_id = (SELECT id FROM user_unit_assignment WHERE user_id = :u AND is_active) '
        "WHERE id = :u",
        u=uid,
    )
    assert await _hien_hanh(uid) == [(vai, unit_id)], "tiền đề: có đúng một bản ghi phân công đang hiệu lực"


async def _hien_hanh(uid):
    """[(vai, đơn vị)] các bản ghi phân công ĐANG HIỆU LỰC của người — đọc từ phiên mới."""
    return [
        (r["role"], r["unit_id"])
        for r in await hang(
            "SELECT role, unit_id FROM user_unit_assignment WHERE user_id = :u AND is_active ORDER BY id", u=uid
        )
    ]


async def _da_dong(uid, vai):
    """Số bản ghi phân công ĐÃ ĐÓNG (``is_active = false`` + có ``end_date``) mang vai ``vai`` của người."""
    return await mot(
        "SELECT count(*) FROM user_unit_assignment WHERE user_id = :u AND role = :r AND NOT is_active "
        "AND end_date IS NOT NULL",
        u=uid,
        r=vai,
    )


async def _quan_ly_don_vi(unit_id):
    """Người nhận "Quản lý đơn vị" mà bộ chọn người nhận thông báo trả về — phiên MỚI."""
    from app.services.notification_resolvers import UnitManagersResolver

    async with AsyncSessionLocal() as s:
        return await UnitManagersResolver().resolve_users(s, {"unit_id": unit_id})


# ---------------------------------------------------------------------------------------------------- gỡ vai
async def test_go_vai_quan_ly_ban_ghi_phan_cong_hien_hanh_mang_vai_moi_ban_cu_dong(
    client, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Quản lý (CSDL + phân công) có thêm vai Cán bộ trong Casbin; gỡ ``role:manager`` ⇒ vai CSDL Cán bộ VÀ bản ghi phân
    công hiện hành mang vai Cán bộ cùng đơn vị; bản ghi Quản lý đóng lại (quy ước thời gian của bảng phân công)."""
    don_vi = lo_config["unit_id"]
    u = await tao_nguoi("prb_l5_go_vai", "manager", don_vi)
    await _phan_cong(u["id"], "manager", don_vi)
    await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:officer")
    h = await dn(client, admin_user_in_db)
    r = await _go_vai(client, h, u["id"], "role:manager")
    assert r.status_code == 200, r.text
    assert (await _vai(u["id"]), await _hien_hanh(u["id"]), await _da_dong(u["id"], "manager")) == (
        "officer",
        [("officer", don_vi)],
        1,
    )


async def test_go_vai_quan_ly_bo_chon_nguoi_nhan_khong_con_chon_nguoi_ay(
    client, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Đường người dùng thật: gỡ vai Quản lý qua HTTP ⇒ bộ chọn người nhận "Quản lý đơn vị" (``UnitManagersResolver`` —
    đọc bản ghi phân công) không còn chọn người ấy. Đối chứng dương trước khi gỡ: có chọn."""
    don_vi = lo_config["unit_id"]
    u = await tao_nguoi("prb_l5_nguoi_nhan", "manager", don_vi)
    await _phan_cong(u["id"], "manager", don_vi)
    assert u["id"] in await _quan_ly_don_vi(don_vi), "đối chứng dương: trước khi gỡ, bộ chọn phải chọn người ấy"
    h = await dn(client, admin_user_in_db)
    r = await _go_vai(client, h, u["id"], "role:manager")
    assert r.status_code == 200, r.text
    assert await _vai(u["id"]) == "user", "tiền đề: gỡ vai thành công"
    assert u["id"] not in await _quan_ly_don_vi(don_vi)


async def test_go_vai_khong_doi_vai_csdl_thi_khong_mo_ban_ghi_phan_cong_moi(
    client, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Đối chứng: gỡ một vai KHÔNG phải vai CSDL (Quản lý có thêm Cán bộ trong Casbin, gỡ Cán bộ) ⇒ vai CSDL vẫn Quản lý ⇒
    bản ghi phân công đang hiệu lực GIỮ NGUYÊN (cùng id) — không đẻ lịch sử giả."""
    don_vi = lo_config["unit_id"]
    u = await tao_nguoi("prb_l5_khong_doi", "manager", don_vi)
    await _phan_cong(u["id"], "manager", don_vi)
    id_cu = await mot("SELECT id FROM user_unit_assignment WHERE user_id = :u AND is_active", u=u["id"])
    await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:officer")
    h = await dn(client, admin_user_in_db)
    r = await _go_vai(client, h, u["id"], "role:officer")
    assert r.status_code == 200, r.text
    assert await _vai(u["id"]) == "manager", "tiền đề: vai CSDL không đổi"
    assert await hang("SELECT id, is_active FROM user_unit_assignment WHERE user_id = :u ORDER BY id", u=u["id"]) == [
        {"id": id_cu, "is_active": True}
    ]


# ---------------------------------------------------------------------------------------------------- đồng bộ vai
async def test_dong_bo_vai_ban_ghi_phan_cong_hien_hanh_mang_vai_dong_bo(
    client, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """CSDL Quản lý (+ phân công Quản lý); Casbin chỉ còn Cán bộ (gán Cán bộ, thu hồi Quản lý — chỉ Casbin) ⇒ đồng bộ ⇒ vai
    CSDL Cán bộ VÀ bản ghi phân công hiện hành Cán bộ cùng đơn vị."""
    don_vi = lo_config["unit_id"]
    u = await tao_nguoi("prb_l5_dong_bo", "manager", don_vi)
    await _phan_cong(u["id"], "manager", don_vi)
    await _them_vai_casbin(client, admin_user_in_db, u["id"], "role:officer")
    h = await dn(client, admin_user_in_db)
    r = await client.request(
        "DELETE", "/api/admin/roles/revoke", headers=h, json={"user_id": u["id"], "role": "role:manager"}
    )
    assert r.status_code == 200, r.text
    assert await _vai(u["id"]) == "manager", "tiền đề: thu hồi Casbin không đụng vai CSDL"
    r = await client.post("/api/admin/users/sync", headers=h, json={"user_ids": [u["id"]]})
    assert r.status_code == 200, r.text
    assert (await _vai(u["id"]), await _hien_hanh(u["id"]), await _da_dong(u["id"], "manager")) == (
        "officer",
        [("officer", don_vi)],
        1,
    )


# ---------------------------------------------------------------------------------------------------- xoá vai tuỳ biến
async def test_xoa_vai_tuy_bien_ban_ghi_phan_cong_hien_hanh_ve_vai_user(
    client, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Người mang vai tuỳ biến (CSDL + Casbin + phân công); xoá vai ⇒ vai CSDL ``user`` VÀ bản ghi phân công hiện hành
    ``user`` cùng đơn vị."""
    don_vi = lo_config["unit_id"]
    ten = "prb_l5_tuy_bien"
    await _vai_tuy_bien(client, admin_user_in_db, ten)
    u = await tao_nguoi("prb_l5_nguoi_tuy_bien", ten, don_vi)
    await _phan_cong(u["id"], ten, don_vi)
    h = await dn(client, admin_user_in_db)
    r = await client.request("DELETE", f"/api/admin/roles/role:{ten}", headers=h)
    assert r.status_code == 200, r.text
    assert (await _vai(u["id"]), await _hien_hanh(u["id"]), await _da_dong(u["id"], ten)) == (
        "user",
        [("user", don_vi)],
        1,
    )


# ---------------------------------------------------------------------------------------------------- gắn tài khoản vào CTV
async def test_gan_tai_khoan_vao_ctv_ban_ghi_phan_cong_hien_hanh_mang_vai_ctv(
    client, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Rà cùng khuôn: Admin tạo hồ sơ CTV gắn tài khoản vai ``user`` (có phân công) ⇒ vai CSDL ``collaborator`` VÀ bản ghi
    phân công hiện hành ``collaborator`` cùng đơn vị."""
    don_vi = lo_config["unit_id"]
    u = await tao_nguoi("prb_l5_gan_ctv", "user", don_vi)
    await _phan_cong(u["id"], "user", don_vi)
    h = await dn(client, admin_user_in_db)
    r = await client.post(
        "/api/collaborators",
        headers=h,
        json={"full_name": "GIA CTV lượt 5", "phone": "0909555001", "unit_id": don_vi, "user_id": u["id"]},
    )
    assert r.status_code == 201, r.text
    assert (await _vai(u["id"]), await _hien_hanh(u["id"]), await _da_dong(u["id"], "user")) == (
        "collaborator",
        [("collaborator", don_vi)],
        1,
    )
