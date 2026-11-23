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

Codex 22-11 (PR-B lượt 6 @``160d7e97``) H1: ``UPDATE`` ĐỔI cột có chỉ mục duy nhất (email) cần ``FOR UPDATE`` — khoá người
đích ``FOR NO KEY UPDATE`` rồi để PostgreSQL nâng lúc flush ⇒ chờ ``FOR KEY SHARE`` của bên kia GIỮA chừng ⇒ ``40P01``. Nay
đổi THẬT cột khoá ⇒ khoá người đích ``FOR UPDATE`` ngay từ đầu (vẫn theo id tăng).

PR-B lượt 8 (owner 23-11, ``gd1b/sua/QUYET-DINH-OWNER-PR-B-LUOT8-CHAN-GOP-EMAIL-KHOA-2026-11-23.md``): chính bản vá lượt 6
sinh vòng chờ mới — PUT {email mới + khoá / hạ vai} giữ người đích ``FOR UPDATE`` rồi chờ dòng quyền ``FOR UPDATE``; lô chéo
§5.4 giữ dòng quyền ``FOR SHARE`` rồi xin người bấm ``FOR KEY SHARE`` ⇒ ``40P01``. Owner chọn "chặn gộp, làm 2 bước": lần
lưu gộp ⇒ 409 ``COMBINED_KEY_CHANGE_AND_REVOKE`` (quyết DƯỚI khoá, trước khi khoá dòng quyền); đổi email riêng / khoá riêng
vẫn qua.
"""
from __future__ import annotations

import asyncio

import pytest

from app import models, schemas
from app.database import AsyncSessionLocal
from app.repositories import document_bulk_repository as bulk_repo
from app.repositories.collaborator_repository import CollaboratorRepository
from tests.api.gd1b_cheo_tro_giup import can_bo_cheo, cap, ho_so  # noqa: F401
from tests.api.gd1b_cheo_tro_giup import hang, mot, tao_nguoi
from tests.api.gd1b_lo_tro_giup import CROSS, Diem, PidTheoNhan, bi_chan_boi, boc, dang_nhap, goi, xac_nhan
from tests.api.gd1b_lo_tro_giup import dn, lo_config, lo_routers, sql  # noqa: F401
from tests.api.test_gd1b_cheo_tu_thu_hoi_2 import _con_hieu_luc, _vai
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


# ---------------------------------------------------------------------------------------------------- đổi email (Codex lượt 6 H1)
async def test_cot_khoa_cua_bang_user_dung_bang_so_cot_khoa(client):
    """Cột có chỉ mục DUY NHẤT thường (không một phần, không biểu thức) của ``user`` trong lược đồ THẬT = ``id`` ∪
    ``USER_KEY_COLUMNS`` — thêm cột duy nhất mới (vd số điện thoại) mà quên ghi ⇒ ĐỎ: đổi cột ấy cũng cần ``FOR UPDATE``."""
    from app.services.user_deletion_policy import USER_KEY_COLUMNS

    cot = await hang(
        "SELECT DISTINCT a.attname FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = '\"user\"'::regclass AND i.indisunique AND i.indpred IS NULL AND i.indexprs IS NULL"
    )
    assert {r["attname"] for r in cot} == {"id", *USER_KEY_COLUMNS}


async def test_hai_admin_sua_email_cua_nhau_cung_luc_khong_be_tac(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """Admin A (id nhỏ) đổi email của Admin U, dừng NGAY SAU bước khoá người; U đổi email của A. U phải CHỜ đúng lệnh của
    A (``pg_blocking_pids``); thả A ⇒ cả hai 200, 0 lỗi CSDL. Bản lượt 5: A giữ U ``NO KEY UPDATE`` + A ``KEY SHARE``, U lấy
    được A ``NO KEY UPDATE`` + U ``KEY SHARE`` rồi cả hai cùng nâng lên ``FOR UPDATE`` lúc flush ⇒ ``40P01``."""
    from app.services import user_deletion_policy

    a = await _admin_dang_nhap_duoc("prb_l6_email_a")
    u = await _admin_dang_nhap_duoc("prb_l6_email_u")
    assert a["id"] < u["id"], "tiền đề: A có id nhỏ hơn U"
    ca, ha = await dang_nhap(a)
    cu, hu = await dang_nhap(u)
    diem = Diem()
    boc(monkeypatch, user_deletion_policy, "lock_users_in_id_order", diem)  # lần gọi ĐẦU (A sửa U) dừng SAU bước khoá
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            ta = asyncio.create_task(
                goi("A", lambda: ca.put(f"/api/admin/users/{u['id']}", headers=ha, data={"email": "prb_l6_u_moi@example.com"}))
            )
            tb = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                tb = asyncio.create_task(
                    goi("B", lambda: cu.put(f"/api/admin/users/{a['id']}", headers=hu, data={"email": "prb_l6_a_moi@example.com"}))
                )
                tt = await bi_chan_boi(tb, ghi, bi="B", boi="A")
            finally:
                diem.di.set()
                if tb is None:  # A không tới điểm dừng: vẫn chờ A xong để không bỏ lại tác vụ treo
                    await asyncio.gather(ta, return_exceptions=True)
            ra, rb = await asyncio.gather(ta, tb)
    finally:
        await ca.aclose()
        await cu.aclose()
    assert tt == "chan", f"lệnh của U phải CHỜ lệnh của A đang giữ khoá ({tt})"
    assert (ra.status_code, rb.status_code, loi.loi) == (200, 200, {}), (ra.text, rb.text)


async def _dich_vu_sua_email(uid, actor_id, email):
    from app.services import user_service

    async with AsyncSessionLocal() as s:
        nguoi = await s.get(models.User, uid)
        await user_service.update_user(s, nguoi, schemas.UserUpdate(email=email), assigned_by_user_id=actor_id)
        await s.commit()
    return "xong"


async def _dich_vu_xoa(uid, actor_id):
    from app.services import user_service

    async with AsyncSessionLocal() as s:
        await user_service.delete_user(s, uid, actor_id=actor_id)
        await s.commit()
    return "xong"


async def test_xoa_tai_khoan_trong_luc_nguoi_bi_xoa_sua_email_nguoi_xoa_khong_be_tac(
    client, monkeypatch, admin_user_in_db, lo_config, lo_routers  # noqa: F811
):
    """U (id nhỏ) xoá A (không phải admin ⇒ K4 chỉ khoá A ``FOR UPDATE`` + U ``KEY SHARE``) trong lúc A đổi email của U.
    Gọi THẲNG tầng dịch vụ (hai phiên riêng): đường HTTP cần A là Quản lý được sửa U — cấu hình quyền ngoài phạm vi phép đo
    khoá. A dừng NGAY SAU bước khoá; K4 của U phải CHỜ đúng phiên của A; thả A ⇒ cả hai xong, 0 lỗi CSDL. Bản lượt 5: A giữ
    U ``NO KEY UPDATE``, K4 lấy được U ``KEY SHARE`` rồi chờ A; A nâng U lên ``FOR UPDATE`` lúc flush ⇒ ``40P01``."""
    from app.services import user_deletion_policy

    u = await _admin_dang_nhap_duoc("prb_l6_xoa_u")
    a = await tao_nguoi("prb_l6_xoa_a", "officer", lo_config["unit_id"])
    assert u["id"] < a["id"], "tiền đề: U có id nhỏ hơn A"
    diem = Diem()
    boc(monkeypatch, user_deletion_policy, "lock_users_in_id_order", diem)  # lần gọi ĐẦU (A sửa U) dừng SAU bước khoá
    with PidTheoNhan() as ghi, _LoiCsdl() as loi:
        ta = asyncio.create_task(goi("A", lambda: _dich_vu_sua_email(u["id"], a["id"], "prb_l6_xoa_u_moi@example.com")))
        tb = None
        try:
            await asyncio.wait_for(diem.toi.wait(), 30)
            tb = asyncio.create_task(goi("B", lambda: _dich_vu_xoa(a["id"], u["id"])))
            tt = await bi_chan_boi(tb, ghi, bi="B", boi="A")
        finally:
            diem.di.set()
            if tb is None:
                await asyncio.gather(ta, return_exceptions=True)
        ra, rb = await asyncio.gather(ta, tb, return_exceptions=True)
    assert tt == "chan", f"K4 (U xoá A) phải CHỜ phiên của A đang giữ khoá ({tt})"
    assert (ra, rb, loi.loi) == ("xong", "xong", {}), (repr(ra), repr(rb))


# ---------------------------------------------------------------------------------------------------- lượt 8: chặn gộp
MA_CHAN_GOP = "COMBINED_KEY_CHANGE_AND_REVOKE"


async def _email_trang_thai_vai(uid):
    return tuple((await hang('SELECT email, status, role FROM "user" WHERE id = :u', u=uid))[0].values())


@pytest.mark.parametrize("thay_doi", [{"status": "inactive"}, {"role": "accountant"}], ids=["khoa", "ha_vai"])
async def test_luu_gop_doi_email_va_khoa_hoac_ha_vai_bi_chan_409_khong_ghi_gi(
    thay_doi, client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers  # noqa: F811
):
    """Một lần lưu vừa đổi email vừa khoá / hạ Cán bộ (kéo theo thu hồi quyền chéo) ⇒ 409 mã riêng; email, trạng thái, vai
    và quyền chéo giữ NGUYÊN (không ghi gì)."""
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    truoc = await _email_trang_thai_vai(can_bo_cheo["id"])
    h = await dn(client, admin_user_in_db)
    r = await client.put(
        f"/api/admin/users/{can_bo_cheo['id']}", headers=h, data={"email": "prb_l8_gop_moi@example.com", **thay_doi}
    )
    assert (r.status_code, r.json().get("error_code")) == (409, MA_CHAN_GOP), r.text
    assert (await _email_trang_thai_vai(can_bo_cheo["id"]), await _con_hieu_luc(gid)) == (truoc, True)


async def test_doi_email_rieng_van_luu_duoc_quyen_cheo_con(
    client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers  # noqa: F811
):
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, admin_user_in_db)
    r = await client.put(f"/api/admin/users/{can_bo_cheo['id']}", headers=h, data={"email": "prb_l8_rieng@example.com"})
    assert r.status_code == 200, r.text
    assert ((await _email_trang_thai_vai(can_bo_cheo["id"]))[0], await _con_hieu_luc(gid)) == (
        "prb_l8_rieng@example.com",
        True,
    )


async def test_khoa_rieng_van_luu_duoc_va_tu_thu_hoi(
    client, admin_user_in_db, can_bo_cheo, lo_config, lo_routers  # noqa: F811
):
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, admin_user_in_db)
    r = await client.put(f"/api/admin/users/{can_bo_cheo['id']}", headers=h, data={"status": "inactive"})
    assert r.status_code == 200, r.text
    assert ((await _email_trang_thai_vai(can_bo_cheo["id"]))[1], await _con_hieu_luc(gid)) == ("inactive", False)


async def test_hai_phien_lo_cheo_dang_giu_quyen_luu_gop_email_va_khoa_bi_chan_ngay_khong_be_tac(
    client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config,
    lo_routers,  # noqa: F811
):
    """Lô duyệt chéo của Cán bộ X (A) dừng NGAY SAU khi giữ dòng quyền ``FOR SHARE`` (§5.4, trước khoá hồ sơ); Admin lưu gộp
    {email mới + khoá X} (B). B phải xong NGAY với 409 mã riêng — không chờ A (``pg_blocking_pids`` từ kết nối thứ ba);
    thả A ⇒ lô chạy xong; 0 lỗi CSDL. Gỡ chặn ⇒ B giữ X ``FOR UPDATE`` rồi chờ dòng quyền; A xin X ``FOR KEY SHARE`` ⇒
    ``40P01``."""
    from app.services import admission_service

    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="l8hp"))[0]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"]], "grant_id": gid})
    assert r.status_code == 201, r.text
    ma = r.json()["batch_id"]
    than_chay = await xac_nhan(ma)
    ca, ha = await dang_nhap(can_bo_cheo)
    cb, hb = await dang_nhap(admin_user_in_db)
    diem = Diem()
    # §5.4: dòng quyền đã giữ FOR SHARE (``lock_grant_share``), CHƯA khoá hồ sơ / người bấm.
    boc(monkeypatch, admission_service, "_lock_profile_for_document_write", diem, truoc=True)
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            ta = asyncio.create_task(goi("A", lambda: ca.post(f"{CROSS}/bulk-verify/{ma}/execute", headers=ha, json=than_chay)))
            tb = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                tb = asyncio.create_task(goi("B", lambda: cb.put(
                    f"/api/admin/users/{can_bo_cheo['id']}", headers=hb,
                    data={"email": "prb_l8_hai_phien@example.com", "status": "inactive"},
                )))
                tt = await bi_chan_boi(tb, ghi, bi="B", boi="A")
            finally:
                diem.di.set()
                if tb is None:  # A không tới điểm dừng: vẫn chờ A xong để không bỏ lại tác vụ treo
                    await asyncio.gather(ta, return_exceptions=True)
            ra, rb = await asyncio.gather(ta, tb)
    finally:
        await ca.aclose()
        await cb.aclose()
    assert (tt, rb.status_code, rb.json().get("error_code"), ra.status_code < 500, loi.loi) == (
        "xong", 409, MA_CHAN_GOP, True, {}
    ), (ra.status_code, ra.text, rb.text)
