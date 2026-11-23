"""GĐ2-C C1 × PR-B lượt 8 (gộp PR-B ``5effed10``, 23-11) — chặn lưu gộp "đổi email + khoá / hạ vai" khi người đích giữ quyền
Thư ký Hội đồng; đổi vai riêng thu hồi CẢ quyền duyệt chéo lẫn quyền Thư ký trong CÙNG giao dịch.

Luật (owner 23-11 ``gd1b/sua/QUYET-DINH-OWNER-PR-B-LUOT8-CHAN-GOP-EMAIL-KHOA-2026-11-23.md``; chữ ở
``repositories/document_bulk_repository.lock_user_key_share``): không đường nào giữ dòng người ``FOR UPDATE`` rồi đi chờ dòng
quyền. PUT ĐỔI email khoá người đích ``FOR UPDATE`` ngay từ đầu ⇒ nếu cùng lần lưu kéo theo tự thu hồi (lý do duyệt chéo HOẶC lý
do Thư ký, tính DƯỚI khoá) thì ``revoke_grants_on_account_change`` trả 409 ``COMBINED_KEY_CHANGE_AND_REVOKE`` TRƯỚC khi khoá BẤT
KỲ dòng quyền nào — kể cả dòng quyền Thư ký C1 thêm.

1. Lưu gộp với người giữ quyền Thư ký ⇒ 409, không ghi gì (tài khoản, quyền duyệt chéo, quyền Thư ký, nhật ký).
   - Cán bộ giữ CẢ HAI quyền: {email + khoá} / {email + hạ vai}.
   - Quản lý giữ quyền Thư ký: {email + sang Kế toán} — CHỈ có lý do Thư ký (vị từ duyệt chéo không áp cho Quản lý). Ca này
     phân biệt "chặn theo cả hai lý do" với "chỉ chặn theo lý do duyệt chéo" (bản PR-B trước khi gộp C1).
   - Đối chứng: Quản lý {email + sang Cán bộ} (Quản lý ↔ Cán bộ giữ quyền Thư ký, không lý do thu hồi) ⇒ 200, quyền còn.
2. Hai phiên: Admin KHÁC đang thu hồi tay quyền Thư ký của Quản lý X (giữ dòng quyền ``FOR UPDATE``); Admin lưu gộp {email +
   hạ vai X} ⇒ xong NGAY với 409, không chờ dòng quyền (``pg_blocking_pids`` từ kết nối thứ ba).
3. Đổi vai riêng (không đổi email): Cán bộ giữ cả hai quyền ⇒ 200, cả hai bị thu hồi cùng câu lý do, cùng người thao tác; tiêm
   lỗi vào nhật ký thu hồi Thư ký ⇒ 500 và quyền DUYỆT CHÉO (thu hồi TRƯỚC trong cùng hàm) cũng còn nguyên.

Mọi phép kiểm đọc CSDL từ phiên RIÊNG.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.repositories import review_secretary_repository as sec_repo
from tests.api.gd1b_cheo_tro_giup import can_bo_cheo, cap  # noqa: F401
from tests.api.gd1b_cheo_tro_giup import hang, tao_nguoi
from tests.api.gd1b_lo_tro_giup import Diem, PidTheoNhan, bi_chan_boi, boc, dang_nhap, dn, goi
from tests.api.gd2c_thu_ky_tro_giup import P, dong_quyen, gan, vet
from tests.api.test_gd1b_cheo_tu_thu_hoi_2 import _con_hieu_luc
from tests.api.test_gd2c_c1_thu_ky_k4_hai_phien import _LoiCsdl
from tests.fixtures.constants import AdminURLs, AuthURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

MA_CHAN_GOP = "COMBINED_KEY_CHANGE_AND_REVOKE"
LY_DO_HA_CAN_BO = "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Kế toán"


async def _tai_khoan(uid: int) -> tuple:
    return tuple((await hang('SELECT email, status, role FROM "user" WHERE id = :u', u=uid))[0].values())


async def _thu_ky_con(gid: int) -> bool:
    return (await dong_quyen(gid))["revoked_at"] is None


async def _vet_cheo(gid: int) -> list:
    return await hang(
        "SELECT action, actor_user_id, reason FROM entity_audit_log"
        " WHERE entity_type = 'document_cross_review_grant' AND entity_id = :g ORDER BY id",
        g=gid,
    )


# ═════════════════════════════════════════════ 1. lưu gộp ⇒ 409, không ghi gì ═════════════════════════════════════════
@pytest.mark.parametrize("thay_doi", [{"status": "inactive"}, {"role": "accountant"}], ids=["khoa", "ha_vai"])
async def test_can_bo_giu_ca_hai_quyen_luu_gop_email_va_khoa_hoac_ha_vai_409_thu_ky_khong_bi_thu_hoi(
    thay_doi, client, admin_user_in_db, can_bo_cheo, seed_lead_dependencies  # noqa: F811
):
    gid_cheo = await cap(client, admin_user_in_db, can_bo_cheo["id"], seed_lead_dependencies["unit_id"], verify=True)
    gid_tk = (await gan(client, admin_user_in_db, can_bo_cheo["id"]))["id"]
    truoc = await _tai_khoan(can_bo_cheo["id"])
    h = await dn(client, admin_user_in_db)  # token mới sau ``cap`` / ``gan`` (đăng nhập lại cùng thiết bị)
    r = await client.put(
        AdminURLs.USER_DETAIL(can_bo_cheo["id"]), headers=h, data={"email": "gd2c_gop_cb_moi@example.com", **thay_doi}
    )
    assert r.status_code == 409, (r.status_code, r.text)  # status TRƯỚC khi đọc thân (CLAUDE.md §3)
    assert r.json().get("error_code") == MA_CHAN_GOP, r.text
    assert (
        await _tai_khoan(can_bo_cheo["id"]),
        await _con_hieu_luc(gid_cheo),
        await _thu_ky_con(gid_tk),
        [v["action"] for v in await vet(gid_tk)],
    ) == (truoc, True, True, ["granted"])


async def test_quan_ly_giu_quyen_thu_ky_luu_gop_email_va_ha_vai_409_khong_ghi_gi(
    client, admin_user_in_db, seed_lead_dependencies
):
    """CHỈ có lý do Thư ký: bản chặn "chỉ theo lý do duyệt chéo" để lần lưu này đi tiếp, giữ người ``FOR UPDATE`` rồi khoá dòng
    quyền Thư ký ``FOR UPDATE`` (trái luật PR-B lượt 8) ⇒ 200 và quyền bị thu hồi ⇒ ca này ĐỎ."""
    from app.services import document_cross_review_service as cheo
    from app.services import review_secretary_service as thu_ky

    thay_doi = dict(old_role="manager", old_status="active", new_role="accountant")
    assert (cheo.auto_revoke_reason(**thay_doi), thu_ky.auto_revoke_reason(**thay_doi) is not None) == (None, True), (
        "tiền đề: thay đổi này chỉ sinh lý do Thư ký"
    )
    ql = await tao_nguoi("gd2c_gop_quanly", "manager", seed_lead_dependencies["unit_id"])
    gid = (await gan(client, admin_user_in_db, ql["id"]))["id"]
    truoc = await _tai_khoan(ql["id"])
    h = await dn(client, admin_user_in_db)
    r = await client.put(
        AdminURLs.USER_DETAIL(ql["id"]), headers=h, data={"email": "gd2c_gop_ql_moi@example.com", "role": "accountant"}
    )
    assert r.status_code == 409, (r.status_code, r.text)
    assert r.json().get("error_code") == MA_CHAN_GOP, r.text
    assert (await _tai_khoan(ql["id"]), await _thu_ky_con(gid), [v["action"] for v in await vet(gid)]) == (
        truoc,
        True,
        ["granted"],
    )


async def test_quan_ly_doi_email_kem_sang_can_bo_van_luu_duoc_quyen_thu_ky_con(
    client, admin_user_in_db, seed_lead_dependencies
):
    """Đối chứng: Quản lý ↔ Cán bộ giữ quyền Thư ký (không lý do thu hồi nào) ⇒ đổi email cùng lần vẫn lưu được. Chặn mà không
    xét lý do thu hồi (vd chặn mọi lần đổi email kèm đổi vai) ⇒ ca này ĐỎ."""
    ql = await tao_nguoi("gd2c_gop_ql_sang_cb", "manager", seed_lead_dependencies["unit_id"])
    gid = (await gan(client, admin_user_in_db, ql["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.put(
        AdminURLs.USER_DETAIL(ql["id"]), headers=h, data={"email": "gd2c_gop_ql_cb@example.com", "role": "officer"}
    )
    assert r.status_code == 200, r.text
    assert (await _tai_khoan(ql["id"]), await _thu_ky_con(gid)) == (
        ("gd2c_gop_ql_cb@example.com", "active", "officer"),
        True,
    )


# ═════════════════════════════════════════════ 2. hai phiên ═══════════════════════════════════════════════════════════
async def test_hai_phien_admin_khac_dang_thu_hoi_tay_thu_ky_luu_gop_bi_chan_ngay_khong_cho_dong_quyen(
    client, monkeypatch, admin_user_in_db, seed_lead_dependencies
):
    """A = Admin khác thu hồi tay quyền Thư ký của Quản lý X, dừng NGAY SAU khi giữ dòng quyền ``FOR UPDATE`` (đã giữ chính A
    ``FOR KEY SHARE``, không xin dòng người nào nữa). B = Admin lưu gộp {email mới + X sang Kế toán}. B phải xong NGAY với 409 —
    không chờ A. Gỡ / thu hẹp phép chặn (chỉ theo lý do duyệt chéo) ⇒ B giữ X ``FOR UPDATE`` rồi CHỜ dòng quyền A đang giữ
    (``chan``); thả A ⇒ B đi tiếp 200. 0 lỗi CSDL ở cả hai phiên."""
    ql = await tao_nguoi("gd2c_gop_hp_quanly", "manager", seed_lead_dependencies["unit_id"])
    gid = (await gan(client, admin_user_in_db, ql["id"]))["id"]
    truoc = await _tai_khoan(ql["id"])
    admin_a = await tao_nguoi("gd2c_gop_hp_admin_a", "admin", None)
    ca, ha = await dang_nhap(admin_a)
    cb, hb = await dang_nhap(admin_user_in_db)
    diem = Diem()
    boc(monkeypatch, sec_repo, "lock_grant_for_update", diem)  # A dừng SAU khi giữ dòng quyền Thư ký FOR UPDATE
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            ta = asyncio.create_task(goi("A", lambda: ca.post(f"{P}/{gid}/revoke", headers=ha, json={"reason": "Hết nhiệm vụ"})))
            tb = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                tb = asyncio.create_task(goi("B", lambda: cb.put(
                    AdminURLs.USER_DETAIL(ql["id"]), headers=hb,
                    data={"email": "gd2c_gop_hp_moi@example.com", "role": "accountant"},
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
    ma_loi_b = rb.json().get("error_code") if rb.status_code == 409 else None  # chỉ đọc thân khi đúng status
    assert (tt, rb.status_code, ma_loi_b, ra.status_code, loi.loi) == ("xong", 409, MA_CHAN_GOP, 200, {}), (
        ra.status_code, ra.text, rb.status_code, rb.text,
    )
    assert await _tai_khoan(ql["id"]) == truoc, "lần lưu gộp bị chặn không được ghi gì"


# ═════════════════════════════════════════════ 3. đổi vai riêng ═══════════════════════════════════════════════════════
async def test_doi_vai_rieng_thu_hoi_ca_quyen_cheo_lan_thu_ky_cung_cau_ly_do(
    client, admin_user_in_db, can_bo_cheo, seed_lead_dependencies  # noqa: F811
):
    gid_cheo = await cap(client, admin_user_in_db, can_bo_cheo["id"], seed_lead_dependencies["unit_id"], verify=True)
    gid_tk = (await gan(client, admin_user_in_db, can_bo_cheo["id"]))["id"]
    h = await dn(client, admin_user_in_db)
    r = await client.put(AdminURLs.USER_DETAIL(can_bo_cheo["id"]), headers=h, data={"role": "accountant"})
    assert r.status_code == 200, r.text
    admin_id = admin_user_in_db["id"]
    dong_tk = await dong_quyen(gid_tk)
    assert (
        await _con_hieu_luc(gid_cheo),
        (await _vet_cheo(gid_cheo))[-1],
        dong_tk["revoked_at"] is not None,
        (dong_tk["revoked_by_user_id"], dong_tk["revoke_reason"]),
    ) == (
        False,
        {"action": "revoked", "actor_user_id": admin_id, "reason": LY_DO_HA_CAN_BO},
        True,
        (admin_id, LY_DO_HA_CAN_BO),
    )


async def test_doi_vai_rieng_loi_nhat_ky_thu_hoi_thu_ky_thi_quyen_cheo_cung_con_nguyen(
    client, monkeypatch, admin_user_in_db, can_bo_cheo, seed_lead_dependencies  # noqa: F811
):
    """Cùng GIAO DỊCH, không chỉ cùng hàm: quyền duyệt chéo bị thu hồi TRƯỚC quyền Thư ký trong ``revoke_grants_on_account_change``;
    tiêm lỗi vào dòng nhật ký thu hồi Thư ký ⇒ 500 và quyền duyệt chéo vẫn còn hiệu lực (thu hồi duyệt chéo bị rollback cùng).
    Biến thể "thu hồi duyệt chéo commit riêng / ở phiên riêng trước khi thu hồi Thư ký" ⇒ quyền chéo đã mất ⇒ ca này ĐỎ."""
    from app.main import fastapi_app
    from app.services import audit_service

    gid_cheo = await cap(client, admin_user_in_db, can_bo_cheo["id"], seed_lead_dependencies["unit_id"], verify=True)
    gid_tk = (await gan(client, admin_user_in_db, can_bo_cheo["id"]))["id"]
    goc = audit_service.log_audit
    da_tiem = []

    async def hong(db, entity_type, *a, **kw):
        if entity_type == "admission_review_secretary_grant":
            da_tiem.append(entity_type)
            raise RuntimeError("tiêm lỗi ghi nhật ký kiểm toán")
        return await goc(db, entity_type, *a, **kw)

    monkeypatch.setattr(audit_service, "log_audit", hong)
    c = AsyncClient(transport=ASGITransport(app=fastapi_app, raise_app_exceptions=False), base_url="http://test",
                    headers={"User-Agent": "gd2c-c1-chan-gop-500"})
    try:
        r = await c.post(AuthURLs.LOGIN, data={"username": admin_user_in_db["username"],
                                               "password": admin_user_in_db["password"]})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.cookies.get('access_token')}"}
        r = await c.put(AdminURLs.USER_DETAIL(can_bo_cheo["id"]), headers=h, data={"role": "accountant"})
    finally:
        await c.aclose()
    assert da_tiem, "tiền đề: lỗi phải được tiêm ĐÚNG ở nhật ký thu hồi Thư ký"
    assert r.status_code == 500, r.text
    assert (await _con_hieu_luc(gid_cheo), await _thu_ky_con(gid_tk), (await _tai_khoan(can_bo_cheo["id"]))[2]) == (
        True,
        True,
        "officer",
    )
