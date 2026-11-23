"""GĐ2-C C1 — quyền "Thư ký Hội đồng" qua REQUEST THẬT (router → deps → dịch vụ → CSDL thật).

Nguồn: QĐB:26; thiết kế GĐ2-C 22-11 §2.2, §4, §6 hàng C1; owner C1 22-11 (không hết hạn, giữ tới khi Admin thu hồi), C2 22-11
(toàn trường). Phần:

1. Admin gán / liệt kê / thu hồi — lý do bắt buộc, vai hợp lệ, một quyền còn hiệu lực mỗi người, nhật ký kiểm toán.
   1b. Ứng viên cho ô tìm (owner 22-11 câu 3): chỉ Quản lý / Cán bộ đang hoạt động chưa có quyền; tìm họ tên bỏ dấu / tên đăng
   nhập / email; ký tự mẫu LIKE là chữ; trả tối thiểu trường. Biến thể: bỏ lọc trạng thái / vai / "chưa có quyền" ⇒ ca
   "chỉ Quản lý …" đỏ; bỏ thoát LIKE ⇒ ca ``%`` đỏ.
2. Quyền route: chỉ Admin (Casbin + lớp phụ); đóng băng tuyển sinh chặn route GHI (503), GET vẫn được.
3. Tự thu hồi khi tài khoản bị khoá / đổi sang vai không được gán — MỌI đường đổi vai / trạng thái đi qua ĐÚNG tầng chủ sở hữu
   ``revoke_grants_on_account_change`` (đường lẻ, hàng loạt, gỡ vai); Quản lý ↔ Cán bộ giữ quyền; lỗi ghi nhật ký ⇒ rollback cả.
4. K4: tài khoản từng được gán / từng gán / từng thu hồi ⇒ không xoá được (409), dù chỉ còn đúng dòng quyền ấy.

Mọi phép kiểm đọc CSDL từ phiên RIÊNG. Mỗi ca kiểm MỘT bất biến.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from tests.api.gd1b_cheo_tro_giup import hang, mot, tao_nguoi
from tests.api.gd1b_lo_tro_giup import dn, sql
from tests.api.gd2b_lan_xet_tro_giup import client_500, so_vet
from tests.api.gd2c_thu_ky_tro_giup import P, dong_quyen, gan, thu_hoi, vet
from tests.fixtures.constants import AdminURLs, AuthURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

LY_DO_KHOA = "Tự thu hồi: tài khoản bị khoá"


@pytest.fixture
async def can_bo(seed_lead_dependencies):
    return await tao_nguoi("gd2c_c1_canbo", "officer", seed_lead_dependencies["unit_id"])


@pytest.fixture
async def quan_ly(seed_lead_dependencies):
    return await tao_nguoi("gd2c_c1_quanly", "manager", seed_lead_dependencies["unit_id"])


async def _so_dong(user_id: int) -> int:
    return await mot("SELECT count(*) FROM admission_review_secretary_grant WHERE user_id = :u", u=user_id)


# ═════════════════════════════════════════════ 1. gán / liệt kê / thu hồi ═════════════════════════════════════════════
async def test_admin_gan_quyen_ghi_dong_va_nhat_ky_khong_co_han(client, admin_user_in_db, can_bo):
    body = await gan(client, admin_user_in_db, can_bo["id"], "Ban thư ký đợt 1")
    assert body["user_id"] == can_bo["id"] and body["is_active"] is True
    assert body["user"] == {
        "id": can_bo["id"], "username": "gd2c_c1_canbo", "full_name": None, "role": "officer", "status": "active",
    }
    assert "expires_at" not in body
    dong = await dong_quyen(body["id"])
    assert (dong["user_id"], dong["granted_by_user_id"], dong["reason"], dong["revoked_at"]) == (
        can_bo["id"], admin_user_in_db["id"], "Ban thư ký đợt 1", None,
    )
    assert await vet(body["id"]) == [{"action": "granted", "actor_user_id": admin_user_in_db["id"], "reason": "Ban thư ký đợt 1"}]


async def test_quan_ly_cung_duoc_gan(client, admin_user_in_db, quan_ly):
    body = await gan(client, admin_user_in_db, quan_ly["id"])
    assert body["user"]["role"] == "manager" and body["is_active"] is True


async def test_admin_thu_hoi_ghi_ba_cot_va_nhat_ky(client, admin_user_in_db, can_bo):
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    body = await thu_hoi(client, admin_user_in_db, g, "Hết nhiệm vụ")
    assert body["is_active"] is False and body["revoke_reason"] == "Hết nhiệm vụ"
    dong = await dong_quyen(g)
    assert dong["revoked_at"] is not None
    assert (dong["revoked_by_user_id"], dong["revoke_reason"]) == (admin_user_in_db["id"], "Hết nhiệm vụ")
    assert [v["action"] for v in await vet(g)] == ["granted", "revoked"]
    assert (await vet(g))[1] == {"action": "revoked", "actor_user_id": admin_user_in_db["id"], "reason": "Hết nhiệm vụ"}


async def test_gan_lai_sau_thu_hoi_la_dong_moi(client, admin_user_in_db, can_bo):
    g1 = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    await thu_hoi(client, admin_user_in_db, g1)
    g2 = (await gan(client, admin_user_in_db, can_bo["id"], "Gán lại đợt 2"))["id"]
    assert g2 != g1 and await _so_dong(can_bo["id"]) == 2
    assert (await dong_quyen(g1))["revoked_at"] is not None and (await dong_quyen(g2))["revoked_at"] is None


async def test_liet_ke_moi_nhat_truoc_loc_con_hieu_luc_va_theo_nguoi(client, admin_user_in_db, can_bo, quan_ly):
    g1 = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    await thu_hoi(client, admin_user_in_db, g1)
    g2 = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    g3 = (await gan(client, admin_user_in_db, quan_ly["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.get(P, headers=h)
    assert r.status_code == 200 and [x["id"] for x in r.json()] == [g3, g2, g1], r.text
    r = await client.get(P, headers=h, params={"active": "true"})
    assert [x["id"] for x in r.json()] == [g3, g2], r.text
    r = await client.get(P, headers=h, params={"active": "false"})
    assert [x["id"] for x in r.json()] == [g1], r.text
    r = await client.get(P, headers=h, params={"user_id": can_bo["id"]})
    assert [x["id"] for x in r.json()] == [g2, g1], r.text


@pytest.mark.parametrize("duong", ["gan", "thu_hoi"])
async def test_ly_do_chi_khoang_trang_422_khong_ghi(client, admin_user_in_db, can_bo, duong):
    h = await dn(client, admin_user_in_db)
    if duong == "gan":
        r = await client.post(P, headers=h, json={"user_id": can_bo["id"], "reason": "   "})
        assert r.status_code == 422, r.text
        assert await _so_dong(can_bo["id"]) == 0
        return
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.post(f"{P}/{g}/revoke", headers=h, json={"reason": "   "})
    assert r.status_code == 422, r.text
    assert (await dong_quyen(g))["revoked_at"] is None


async def test_gui_truong_han_bi_tu_choi_422(client, admin_user_in_db, can_bo):
    """Owner C1: không hết hạn ⇒ thân gán không có trường hạn; gửi ``expires_at`` ⇒ 422 (khoá lạ), không ghi."""
    h = await dn(client, admin_user_in_db)
    r = await client.post(
        P, headers=h, json={"user_id": can_bo["id"], "reason": "x", "expires_at": "2026-12-31T00:00:00+07:00"}
    )
    assert r.status_code == 422, r.text
    assert await _so_dong(can_bo["id"]) == 0


@pytest.mark.parametrize("loai", ["admin", "accountant", "collaborator", "user", "can_bo_bi_khoa", "khong_ton_tai"])
async def test_nguoi_khong_hop_le_400_khong_ghi(client, admin_user_in_db, seed_lead_dependencies, loai):
    if loai == "khong_ton_tai":
        uid = 2_147_480_000
    elif loai == "can_bo_bi_khoa":
        uid = (await tao_nguoi("gd2c_c1_khoa", "officer", seed_lead_dependencies["unit_id"]))["id"]
        await sql("UPDATE \"user\" SET status = 'inactive' WHERE id = :u", u=uid)
    else:
        uid = (await tao_nguoi("gd2c_c1_%s" % loai, loai, seed_lead_dependencies["unit_id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.post(P, headers=h, json={"user_id": uid, "reason": "x"})
    assert r.status_code == 400, r.text
    assert (r.json()["error_code"], r.json()["reason_code"]) == ("VALIDATION_ERROR", "review_secretary_grantee_not_eligible")
    assert await _so_dong(uid) == 0


async def test_dang_co_quyen_thi_gan_them_409(client, admin_user_in_db, can_bo):
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.post(P, headers=h, json={"user_id": can_bo["id"], "reason": "lần hai"})
    assert r.status_code == 409, r.text
    assert (r.json()["error_code"], r.json()["grant_id"]) == ("REVIEW_SECRETARY_ALREADY_ACTIVE", g)
    assert await _so_dong(can_bo["id"]) == 1


async def test_thu_hoi_lan_hai_409_mot_dong_nhat_ky(client, admin_user_in_db, can_bo):
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    await thu_hoi(client, admin_user_in_db, g, "lần một")
    h = await dn(client, admin_user_in_db)
    r = await client.post(f"{P}/{g}/revoke", headers=h, json={"reason": "lần hai"})
    assert r.status_code == 409 and r.json()["error_code"] == "REVIEW_SECRETARY_GRANT_ALREADY_REVOKED", r.text
    assert (await dong_quyen(g))["revoke_reason"] == "lần một"
    assert [v["action"] for v in await vet(g)] == ["granted", "revoked"]


async def test_thu_hoi_ma_khong_ton_tai_404(client, admin_user_in_db):
    h = await dn(client, admin_user_in_db)
    r = await client.post(f"{P}/2147480000/revoke", headers=h, json={"reason": "x"})
    assert r.status_code == 404, r.text
    assert (r.json()["error_code"], r.json()["reason_code"]) == ("RESOURCE_NOT_FOUND", "review_secretary_grant_not_found")


@pytest.mark.parametrize("duong", ["gan", "thu_hoi"])
async def test_i1_phan_hoi_lech_schema_500_khong_ghi_gi(client, admin_user_in_db, can_bo, monkeypatch, duong):
    """Rà hợp nhất 23-11 I1 + quyết định owner O2 23-11: thân phản hồi lệch ``ReviewSecretaryGrantView`` ⇒ người gọi nhận 500 và
    CSDL KHÔNG đổi — không dòng quyền / không ghi thu hồi, không dòng nhật ký (router kiểm phản hồi TRƯỚC ``commit``). Thiếu phép
    kiểm ⇒ cùng 500 nhưng quyền + nhật ký ĐÃ ghi — mã 500 một mình không phân biệt hai bản, nên ca ĐẾM CSDL. Lệch giả lập ở ĐÚNG chỗ
    dịch vụ dựng phản hồi (``_grant_view``), SAU câu ghi và SAU nhật ký."""
    from app.services import review_secretary_service as svc

    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"] if duong == "thu_hoi" else None
    vet_truoc = await so_vet(svc.GRANT_ENTITY_TYPE)
    h = await dn(client, admin_user_in_db)
    monkeypatch.setattr(svc, "_grant_view", lambda *a, **k: {"id": "khong-phai-so"})
    async with client_500() as c:
        if duong == "gan":
            r = await c.post(P, headers=h, json={"user_id": can_bo["id"], "reason": "Ban thư ký đợt 1"})
        else:
            r = await c.post(f"{P}/{g}/revoke", headers=h, json={"reason": "Hết nhiệm vụ"})
    assert r.status_code == 500, r.text
    assert await so_vet(svc.GRANT_ENTITY_TYPE) == vet_truoc
    if duong == "gan":
        assert await _so_dong(can_bo["id"]) == 0
    else:
        assert (await dong_quyen(g))["revoked_at"] is None


# ═════════════════════════════════════════════ 1b. ứng viên (ô tìm của màn hình gán — owner 22-11 câu 3) ═════════════
@pytest.fixture
async def ung_vien(client, admin_user_in_db, seed_lead_dependencies):
    """Bảy người: bốn KHÔNG được hiện (Cán bộ bị khoá, Kế toán, Admin, Cán bộ đang là Thư ký) và ba ĐƯỢC hiện (Cán bộ, Quản lý,
    Cán bộ có quyền đã thu hồi). Họ tên có dấu đặt bằng SQL."""
    unit = seed_lead_dependencies["unit_id"]
    ra = {}
    for khoa, vai in (
        ("can_bo", "officer"), ("quan_ly", "manager"), ("da_thu_hoi", "officer"),
        ("bi_khoa", "officer"), ("ke_toan", "accountant"), ("admin_khac", "admin"), ("dang_la_thu_ky", "officer"),
    ):
        ra[khoa] = (await tao_nguoi("gd2c_uv_%s" % khoa, vai, unit))["id"]
    await sql("UPDATE \"user\" SET full_name = 'Nguyễn Văn Thư' WHERE id = :u", u=ra["can_bo"])
    await sql("UPDATE \"user\" SET full_name = 'Trần Thị Ký' WHERE id = :u", u=ra["quan_ly"])
    await sql("UPDATE \"user\" SET status = 'inactive' WHERE id = :u", u=ra["bi_khoa"])
    await gan(client, admin_user_in_db, ra["dang_la_thu_ky"])
    g = (await gan(client, admin_user_in_db, ra["da_thu_hoi"]))["id"]
    await thu_hoi(client, admin_user_in_db, g)
    return ra


async def _tim(client, admin, **params):
    h = await dn(client, admin)
    r = await client.get(f"{P}/candidates", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_ung_vien_chi_quan_ly_can_bo_dang_hoat_dong_chua_co_quyen(client, admin_user_in_db, ung_vien):
    ids = {x["id"] for x in await _tim(client, admin_user_in_db)} & set(ung_vien.values())
    assert ids == {ung_vien["can_bo"], ung_vien["quan_ly"], ung_vien["da_thu_hoi"]}, ids


@pytest.mark.parametrize(
    "q, khoa",
    [("nguyen van", "can_bo"), ("NGUYỄN", "can_bo"), ("tran thi", "quan_ly"), ("gd2c_uv_quan", "quan_ly"),
     ("gd2c_uv_can_bo@example", "can_bo")],
)
async def test_ung_vien_tim_theo_ho_ten_bo_dau_ten_dang_nhap_email(client, admin_user_in_db, ung_vien, q, khoa):
    ids = {x["id"] for x in await _tim(client, admin_user_in_db, q=q)} & set(ung_vien.values())
    assert ids == {ung_vien[khoa]}, (q, ids)


@pytest.mark.parametrize(
    "q", ["%", "nguyen van th_", "\\"], ids=["phan_tram", "gach_duoi_sau_ho_ten", "gach_cheo"]
)
async def test_ung_vien_ky_tu_mau_like_la_chu_khong_phai_mau(client, admin_user_in_db, ung_vien, q):
    """``%`` / ``_`` / ``\\`` người gõ là CHỮ (thoát bằng ``escape_like_pattern``) ⇒ rỗng.

    * ``%``: không ai có ``%`` ⇒ rỗng; bỏ thoát ⇒ khớp TẤT CẢ ⇒ đỏ.
    * ``_``: KHÔNG dùng ``q="_"`` trần — tên đăng nhập / email dữ liệu thử (``gd2c_uv_*``) có dấu ``_`` THẬT, nên ``_`` đã thoát
      đúng vẫn khớp chữ ``_`` ⇒ ca ấy đỏ trên mã ĐÚNG và cũng đỏ khi bỏ thoát (không phân biệt được gì — CI 23-11 N4, rà 23-11
      G5). ``"nguyen van th_"``: thoát đúng ⇒ cần chữ ``_`` sau "nguyen van th" ⇒ không ai ⇒ rỗng; bỏ thoát ⇒ ``_`` khớp một
      ký tự ⇒ khớp "Nguyễn Văn Thư" (bỏ dấu) ⇒ đỏ.
    * ``\\``: không ai có ``\\`` ⇒ rỗng, không 500. Ca này KHÔNG phân biệt được biến thể "không nhân đôi ``\\``" (dữ liệu thử
      không có ``\\`` nào để khớp) — chỉ canh "không khớp tất cả / không lỗi"."""
    ids = {x["id"] for x in await _tim(client, admin_user_in_db, q=q)} & set(ung_vien.values())
    assert ids == set(), (q, ids)


async def test_ung_vien_tra_toi_thieu_truong(client, admin_user_in_db, ung_vien):
    ds = [x for x in await _tim(client, admin_user_in_db, q="gd2c_uv_can_bo") if x["id"] == ung_vien["can_bo"]]
    assert ds == [
        {"id": ung_vien["can_bo"], "username": "gd2c_uv_can_bo", "full_name": "Nguyễn Văn Thư",
         "email": "gd2c_uv_can_bo@example.com", "role": "officer"}
    ]


# ═════════════════════════════════════════════ 2. quyền route + đóng băng ═════════════════════════════════════════════
@pytest.mark.parametrize("vai", ["manager", "officer", "accountant"])
async def test_chi_admin_403_cho_vai_khac(client, admin_user_in_db, can_bo, seed_lead_dependencies, vai):
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    nguoi = await tao_nguoi("gd2c_c1_403_%s" % vai, vai, seed_lead_dependencies["unit_id"])
    h = await dn(client, nguoi)
    for m, duong, than in (
        ("GET", P, None),
        ("GET", f"{P}/candidates", None),
        ("POST", P, {"user_id": can_bo["id"], "reason": "x"}),
        ("POST", f"{P}/{g}/revoke", {"reason": "x"}),
    ):
        r = await client.request(m, duong, headers=h, json=than)
        assert r.status_code == 403, (vai, m, duong, r.text)
    assert (await dong_quyen(g))["revoked_at"] is None and await _so_dong(can_bo["id"]) == 1


async def test_lop_phu_chi_admin_tu_choi_vai_khac_du_lot_casbin():
    """Lớp phụ ``deps.require_review_secretary_admin`` (Casbin là tầng chủ sở hữu vai): gọi THẲNG với người không phải Admin
    ⇒ 403 — một cấu hình Casbin sai không mở được việc gán Thư ký cho vai khác."""
    from types import SimpleNamespace

    from app.core import deps
    from app.utils.exceptions import PermissionDeniedError

    for vai in ("manager", "officer", "accountant", "collaborator", "user"):
        with pytest.raises(PermissionDeniedError):
            await deps.require_review_secretary_admin(SimpleNamespace(id=1, role=vai))
    u = SimpleNamespace(id=1, role="admin")
    assert await deps.require_review_secretary_admin(u) is u


async def test_dong_bang_chan_gan_va_thu_hoi_503_doc_van_duoc(client, admin_user_in_db, can_bo, quan_ly, monkeypatch):
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)
    for duong, than in ((P, {"user_id": quan_ly["id"], "reason": "x"}), (f"{P}/{g}/revoke", {"reason": "x"})):
        r = await client.post(duong, headers=h, json=than)
        assert r.status_code == 503 and r.json()["code"] == "ADMISSION_FROZEN", (duong, r.text)
    assert (await client.get(P, headers=h)).status_code == 200
    assert (await dong_quyen(g))["revoked_at"] is None and await _so_dong(quan_ly["id"]) == 0
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", False)
    r = await client.post(f"{P}/{g}/revoke", headers=h, json={"reason": "x"})
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════ 3. tự thu hồi ══════════════════════════════════════════════════════════
async def _kiem_tu_thu_hoi(g: int, admin_id: int, ly_do: str):
    dong = await dong_quyen(g)
    assert dong["revoked_at"] is not None
    assert (dong["revoked_by_user_id"], dong["revoke_reason"]) == (admin_id, ly_do)
    assert (await vet(g))[-1] == {"action": "revoked", "actor_user_id": admin_id, "reason": ly_do}


@pytest.mark.parametrize(
    "vai_dau, thay_doi, ly_do",
    [
        ("officer", {"role": "accountant"}, "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Kế toán"),
        ("manager", {"role": "accountant"}, "Tự thu hồi: tài khoản đổi vai từ Quản lý sang Kế toán"),
        ("officer", {"status": "inactive"}, LY_DO_KHOA),
        ("manager", {"status": "banned"}, LY_DO_KHOA),
    ],
)
async def test_sua_tai_khoan_le_tu_thu_hoi(client, admin_user_in_db, seed_lead_dependencies, vai_dau, thay_doi, ly_do):
    nguoi = await tao_nguoi("gd2c_c1_le_%s" % vai_dau, vai_dau, seed_lead_dependencies["unit_id"])
    g = (await gan(client, admin_user_in_db, nguoi["id"]))["id"]
    # Token MỚI sau ``gan``: ``gan`` đăng nhập lại Admin trên CÙNG thiết bị ⇒ phiên cũ (của fixture
    # ``admin_token_headers``) bị thu hồi (``session_service._revoke_previous_sessions_on_device``) ⇒ 401 INVALID_TOKEN.
    h = await dn(client, admin_user_in_db)
    r = await client.put(AdminURLs.USER_DETAIL(nguoi["id"]), headers=h, data=thay_doi)
    assert r.status_code == 200, r.text
    await _kiem_tu_thu_hoi(g, admin_user_in_db["id"], ly_do)


@pytest.mark.parametrize("vai_dau, vai_moi", [("manager", "officer"), ("officer", "manager")])
async def test_quan_ly_can_bo_doi_qua_lai_giu_quyen(client, admin_user_in_db, seed_lead_dependencies, vai_dau, vai_moi):
    nguoi = await tao_nguoi("gd2c_c1_giu_%s" % vai_dau, vai_dau, seed_lead_dependencies["unit_id"])
    g = (await gan(client, admin_user_in_db, nguoi["id"]))["id"]
    h = await dn(client, admin_user_in_db)  # token mới sau ``gan`` (xem ``test_sua_tai_khoan_le_tu_thu_hoi``)
    r = await client.put(AdminURLs.USER_DETAIL(nguoi["id"]), headers=h, data={"role": vai_moi})
    assert r.status_code == 200, r.text
    assert await mot("SELECT role FROM \"user\" WHERE id = :u", u=nguoi["id"]) == vai_moi
    assert (await dong_quyen(g))["revoked_at"] is None


async def test_khoa_tai_khoan_hang_loat_tu_thu_hoi_tung_nguoi(client, admin_user_in_db, can_bo, quan_ly):
    g1 = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    g2 = (await gan(client, admin_user_in_db, quan_ly["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.post(
        AdminURLs.BULK_ACTION, headers=h,
        json={"action": "change_status", "user_ids": [quan_ly["id"], can_bo["id"]], "status": "banned"},
    )
    assert r.status_code == 200, r.text
    await _kiem_tu_thu_hoi(g1, admin_user_in_db["id"], LY_DO_KHOA)
    await _kiem_tu_thu_hoi(g2, admin_user_in_db["id"], LY_DO_KHOA)


async def test_go_vai_can_bo_tu_thu_hoi(client, admin_user_in_db, can_bo):
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.request(
        "DELETE", "/api/admin/roles/role:officer/users", headers=h,
        json={"user_ids": [can_bo["id"]], "role_to_remove": "role:officer"},
    )
    assert r.status_code == 200 and r.json()["removed_count"] == 1, r.text
    await _kiem_tu_thu_hoi(g, admin_user_in_db["id"], "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Người dùng")


async def test_mo_khoa_khong_khoi_phuc_quyen(client, admin_user_in_db, can_bo):
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    h = await dn(client, admin_user_in_db)  # token mới sau ``gan`` (xem ``test_sua_tai_khoan_le_tu_thu_hoi``)
    for trang_thai in ("inactive", "active"):
        r = await client.put(AdminURLs.USER_DETAIL(can_bo["id"]), headers=h, data={"status": trang_thai})
        assert r.status_code == 200, r.text
    await _kiem_tu_thu_hoi(g, admin_user_in_db["id"], LY_DO_KHOA)
    assert await mot(
        "SELECT count(*) FROM admission_review_secretary_grant WHERE user_id = :u AND revoked_at IS NULL", u=can_bo["id"]
    ) == 0


@pytest.mark.parametrize("thay_doi", [{"status": "inactive"}, {"role": "accountant"}])
async def test_loi_ghi_nhat_ky_thu_hoi_thu_ky_thi_rollback_ca_doi_vai_khoa(
    client, monkeypatch, admin_user_in_db, can_bo, thay_doi
):
    """Tự thu hồi Thư ký CÙNG giao dịch với việc khoá / đổi vai: tiêm lỗi vào dòng nhật ký thu hồi Thư ký ⇒ 500, vai / trạng
    thái / quyền đều nguyên (bắt biến thể "thu hồi ở giao dịch riêng" hoặc "nuốt lỗi rồi vẫn commit")."""
    from app.main import fastapi_app
    from app.services import audit_service

    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    goc = audit_service.log_audit
    da_tiem = []

    async def hong(db, entity_type, *a, **kw):
        if entity_type == "admission_review_secretary_grant":
            da_tiem.append(entity_type)
            raise RuntimeError("tiêm lỗi ghi nhật ký kiểm toán")
        return await goc(db, entity_type, *a, **kw)

    monkeypatch.setattr(audit_service, "log_audit", hong)
    c = AsyncClient(transport=ASGITransport(app=fastapi_app, raise_app_exceptions=False), base_url="http://test",
                    headers={"User-Agent": "gd2c-c1-500"})
    try:
        r = await c.post(AuthURLs.LOGIN, data={"username": admin_user_in_db["username"],
                                               "password": admin_user_in_db["password"]})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.cookies.get('access_token')}"}
        r = await c.put(AdminURLs.USER_DETAIL(can_bo["id"]), headers=h, data=thay_doi)
    finally:
        await c.aclose()
    assert da_tiem, "tiền đề: lỗi phải được tiêm ĐÚNG ở nhật ký thu hồi Thư ký"
    assert r.status_code == 500, r.text
    assert await hang("SELECT role, status FROM \"user\" WHERE id = :u", u=can_bo["id"]) == [
        {"role": "officer", "status": "active"}
    ]
    assert (await dong_quyen(g))["revoked_at"] is None


# ═════════════════════════════════════════════ 4. K4 ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("cot", ["user_id", "granted_by_user_id", "revoked_by_user_id"])
async def test_k4_chan_xoa_nguoi_chi_con_dong_quyen_thu_ky(client, admin_token_headers, seed_lead_dependencies, cot):
    """Người bị xoá CHỈ còn đúng một tham chiếu: cột ``cot`` của một dòng quyền (chèn thẳng SQL — không nhật ký nào mang tên
    người ấy) ⇒ K4 409 ``USER_HAS_ACTIVITY``, tài khoản còn. Thiếu dòng sổ K4 cho cột ấy ⇒ khoá ngoại RESTRICT ⇒ 500."""
    x = (await tao_nguoi("gd2c_c1_k4_x", "officer", seed_lead_dependencies["unit_id"]))["id"]
    khac = (await tao_nguoi("gd2c_c1_k4_khac", "officer", seed_lead_dependencies["unit_id"]))["id"]
    nguoi = {"user_id": khac, "granted_by_user_id": khac, "revoked_by_user_id": khac, cot: x}
    if cot == "revoked_by_user_id":
        await sql(
            "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason, revoked_at, revoked_by_user_id,"
            " revoke_reason) VALUES (:u, :g, 'x', now(), :r, 'y')",
            u=nguoi["user_id"], g=nguoi["granted_by_user_id"], r=nguoi["revoked_by_user_id"],
        )
    else:
        await sql(
            "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES (:u, :g, 'x')",
            u=nguoi["user_id"], g=nguoi["granted_by_user_id"],
        )
    client.cookies.clear()
    r = await client.delete(AdminURLs.USER_DETAIL(x), headers=admin_token_headers)
    assert r.status_code == 409 and r.json()["error_code"] == "USER_HAS_ACTIVITY", r.text
    assert await mot("SELECT count(*) FROM \"user\" WHERE id = :u", u=x) == 1


async def test_k4_chan_xoa_nguoi_da_bi_thu_hoi_quyen(client, admin_user_in_db, can_bo):
    """Lịch sử "đã từng là Thư ký" vẫn chặn xoá sau khi thu hồi (người đề xuất ≠ người khoá đọc lại lịch sử này)."""
    g = (await gan(client, admin_user_in_db, can_bo["id"]))["id"]
    await thu_hoi(client, admin_user_in_db, g)
    h = await dn(client, admin_user_in_db)  # token mới sau ``gan`` / ``thu_hoi`` (xem ``test_sua_tai_khoan_le_tu_thu_hoi``)
    r = await client.delete(AdminURLs.USER_DETAIL(can_bo["id"]), headers=h)
    assert r.status_code == 409 and r.json()["error_code"] == "USER_HAS_ACTIVITY", r.text
