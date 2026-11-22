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

Codex 22-11 (PR-B lượt 5 @``d6601383``):

- P1 — gỡ ĐƠN VỊ của Quản lý (``PUT``, ``unit_id`` = 0): hàm phân công từng trả về sớm ở nhánh "không đơn vị" TRƯỚC khi đóng
  bản ghi cũ ⇒ bộ chọn người nhận vẫn chọn người ấy làm Quản lý đơn vị cũ.
- P2 — hai phiên với K4: Admin A đổi vai / đơn vị / trạng thái của U (giữ U) rồi ghi khoá ngoại tới A; Admin B cùng lúc xoá
  lô {A, U} (K4 khoá ``FOR UPDATE ORDER BY id``, id A < U ⇒ giữ A chờ U) ⇒ bế tắc ``40P01``. Nay mọi đường ghi tài khoản
  khoá người đích ∪ người được tham chiếu theo id TĂNG TRƯỚC mọi câu ghi (``user_deletion_policy.lock_users_in_id_order``):
  K4 chờ lệnh của A (đo bằng ``pg_blocking_pids`` từ kết nối thứ ba), lệnh của A xong, không lỗi CSDL nào.
"""
from __future__ import annotations

import asyncio

import pytest

from app.database import AsyncSessionLocal
from app.repositories import document_bulk_repository as bulk_repo
from app.repositories.collaborator_repository import CollaboratorRepository
from tests.api.gd1b_cheo_tro_giup import hang, mot, tao_nguoi
from tests.api.gd1b_lo_tro_giup import Diem, PidTheoNhan, bi_chan_boi, boc, dang_nhap, goi
from tests.api.gd1b_lo_tro_giup import dn, lo_config, lo_routers, sql  # noqa: F401
from tests.api.test_gd1b_cheo_tu_thu_hoi_2 import _vai
from tests.api.test_gd1b_cheo_tu_thu_hoi_3 import _go_vai, _them_vai_casbin, _vai_tuy_bien
from tests.api.test_gd1b_xoa_tai_khoan_hai_phien import _admin_dang_nhap_duoc, _LoiCsdl
from tests.fixtures.constants import AdminURLs

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


# ---------------------------------------------------------------------------------------------------- gỡ đơn vị (Codex P1)
async def test_go_don_vi_cua_quan_ly_bo_chon_nguoi_nhan_khong_con_chon_nguoi_ay(
    client, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Codex 22-11 P1 — đường người dùng thật: Admin gỡ ĐƠN VỊ của Quản lý (``PUT``, ``unit_id`` = 0 ⇒ để trống) ⇒ bộ chọn
    người nhận "Quản lý đơn vị" (``UnitManagersResolver`` — đọc bản ghi phân công) không còn chọn người ấy cho đơn vị cũ.
    Đối chứng dương trước khi gỡ: có chọn."""
    don_vi = lo_config["unit_id"]
    u = await tao_nguoi("prb_l5_go_don_vi", "manager", don_vi)
    await _phan_cong(u["id"], "manager", don_vi)
    assert u["id"] in await _quan_ly_don_vi(don_vi), "đối chứng dương: trước khi gỡ, bộ chọn phải chọn người ấy"
    h = await dn(client, admin_user_in_db)
    r = await client.put(f"/api/admin/users/{u['id']}", headers=h, data={"unit_id": "0"})
    assert r.status_code == 200, r.text
    assert await mot('SELECT unit_id FROM "user" WHERE id = :u', u=u["id"]) is None, "tiền đề: đã gỡ đơn vị"
    assert u["id"] not in await _quan_ly_don_vi(don_vi)


# ---------------------------------------------------------------------------------------------------- hai phiên K4 (Codex P2)
async def _nguoi_co_phan_cong(ten, vai, don_vi):
    u = await tao_nguoi(ten, vai, don_vi)
    await _phan_cong(u["id"], vai, don_vi)
    return u["id"]


async def _duong_go_vai(client, admin, don_vi):
    uid = await _nguoi_co_phan_cong("prb_l5_k4_go_vai", "manager", don_vi)
    await _them_vai_casbin(client, admin, uid, "role:officer")
    return uid, (lambda c, h: _go_vai(c, h, uid, "role:manager")), 200


async def _duong_put_doi_vai(client, admin, don_vi):
    uid = await _nguoi_co_phan_cong("prb_l5_k4_put", "manager", don_vi)
    return uid, (lambda c, h: c.put(f"/api/admin/users/{uid}", headers=h, data={"role": "officer"})), 200


async def _duong_khoa_hang_loat(client, admin, don_vi):
    uid = await _nguoi_co_phan_cong("prb_l5_k4_khoa", "officer", don_vi)
    than = {"action": "change_status", "user_ids": [uid], "status": "banned"}
    return uid, (lambda c, h: c.post(AdminURLs.BULK_ACTION, headers=h, json=than)), 200


async def _duong_dong_bo(client, admin, don_vi):
    uid = await _nguoi_co_phan_cong("prb_l5_k4_dong_bo", "manager", don_vi)
    await _them_vai_casbin(client, admin, uid, "role:officer")
    h = await dn(client, admin)
    r = await client.request("DELETE", "/api/admin/roles/revoke", headers=h, json={"user_id": uid, "role": "role:manager"})
    assert r.status_code == 200, r.text
    return uid, (lambda c, h: c.post("/api/admin/users/sync", headers=h, json={"user_ids": [uid]})), 200


async def _duong_xoa_vai_tuy_bien(client, admin, don_vi):
    ten = "prb_l5_k4_tuy_bien"
    await _vai_tuy_bien(client, admin, ten)
    uid = await _nguoi_co_phan_cong("prb_l5_k4_nguoi_tuy_bien", ten, don_vi)
    return uid, (lambda c, h: c.request("DELETE", f"/api/admin/roles/role:{ten}", headers=h)), 200


async def _duong_gan_ctv(client, admin, don_vi):
    uid = await _nguoi_co_phan_cong("prb_l5_k4_gan_ctv", "user", don_vi)
    than = {"full_name": "GIA CTV K4", "phone": "0909555002", "unit_id": don_vi, "user_id": uid}
    return uid, (lambda c, h: c.post("/api/collaborators", headers=h, json=than)), 201


#: đường ghi tài khoản → (dựng dữ liệu + yêu cầu của Admin A, điểm dừng "đã giữ dòng U, CHƯA ghi gì").
_DUONG_GHI_TAI_KHOAN = {
    "go_vai": (_duong_go_vai, (bulk_repo, "lock_user_no_key_update")),
    "put_doi_vai": (_duong_put_doi_vai, (bulk_repo, "lock_user_no_key_update")),
    "khoa_hang_loat": (_duong_khoa_hang_loat, (bulk_repo, "lock_user_no_key_update")),
    "dong_bo_vai": (_duong_dong_bo, (bulk_repo, "lock_user_no_key_update")),
    "xoa_vai_tuy_bien": (_duong_xoa_vai_tuy_bien, (bulk_repo, "lock_user_no_key_update")),
    # Gắn CTV khoá dòng U bằng câu riêng (``select … with_for_update``); dừng ngay SAU bước khoá + đọc lại tài khoản.
    "gan_ctv": (_duong_gan_ctv, (CollaboratorRepository, "get_by_user_id")),
}


@pytest.mark.parametrize("duong", list(_DUONG_GHI_TAI_KHOAN))
async def test_hai_phien_admin_ghi_tai_khoan_trong_luc_admin_khac_xoa_lo_gom_ca_hai_khong_be_tac(
    duong, client, monkeypatch, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Codex 22-11 P2. Admin A (id NHỎ hơn U) ghi tài khoản U qua ``duong`` và dừng NGAY SAU khi đã giữ dòng U, CHƯA ghi gì;
    Admin B xoá lô {A, U} (K4). B phải CHỜ đúng lệnh của A (``pg_blocking_pids`` từ kết nối thứ ba); thả A ⇒ A xong đúng mã,
    B xong không 500, KHÔNG lỗi CSDL nào ở cả hai phiên (bản cũ: A giữ U rồi mới lấy khoá khoá-ngoại trên A, K4 giữ A chờ U
    ⇒ ``DeadlockDetectedError/40P01``)."""
    dung_va_yeu_cau, (chu, ten) = _DUONG_GHI_TAI_KHOAN[duong]
    a = await _admin_dang_nhap_duoc(f"prb_l5_k4_a_{duong}")
    uid, yeu_cau, ma_a = await dung_va_yeu_cau(client, admin_user_in_db, lo_config["unit_id"])
    assert a["id"] < uid, "tiền đề: người thao tác A có id NHỎ hơn người đích U (thứ tự K4 khoá A trước U)"
    ca, ha = await dang_nhap(a)
    cb, hb = await dang_nhap(admin_user_in_db)
    diem = Diem()
    boc(monkeypatch, chu, ten, diem)
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            ta = asyncio.create_task(goi("A", lambda: yeu_cau(ca, ha)))
            tb = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                xoa_lo = {"action": "delete", "user_ids": [a["id"], uid]}
                tb = asyncio.create_task(goi("B", lambda: cb.post(AdminURLs.BULK_ACTION, headers=hb, json=xoa_lo)))
                tt = await bi_chan_boi(tb, ghi, bi="B", boi="A")
            finally:
                diem.di.set()
                if tb is None:  # A không tới điểm dừng: vẫn chờ A xong để không bỏ lại tác vụ treo
                    await asyncio.gather(ta, return_exceptions=True)
            ra, rb = await asyncio.gather(ta, tb)
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"lệnh xoá lô (B) phải CHỜ lệnh của A đang giữ khoá ({tt})"
    assert (ra.status_code, rb.status_code < 500, loi.loi) == (ma_a, True, {}), (ra.text, rb.status_code, rb.text)
