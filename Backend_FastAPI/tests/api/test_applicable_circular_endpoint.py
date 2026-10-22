"""``POST /api/v2/admissions/{id}/applicable-circular`` — đổi thông tư áp dụng (V3 C5, nhóm F).

Owner chốt: T2c (manager + admin, có lịch sử) · Q3 "Như ấn định KV" (ma trận trạng thái dùng CHUNG với
``override_kv``) · Q4 "Chỉ lý do". Mỗi ca canh MỘT bất biến; đột biến ghi trong docstring từng ca.
"""

import itertools
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app import models
from app.constants import admission_circular as ac
from app.database import AsyncSessionLocal
from app.models.priority_audit import PriorityAuditLog
from app.services import admission_service, applicable_circular_service, priority_override_service
from tests.conftest import _create_user_and_role, _get_token_headers

pytestmark = pytest.mark.asyncio

_DEM = itertools.count(1)
_LY_DO = "Ho so nop truoc moc nhung truong xet theo thong tu moi"

_ACCOUNTANT = {
    "username": "v3tt_accountant",
    "email": "v3tt_accountant@example.com",
    "password": "AccountantPassword!345",
    "role": "accountant",
    "status": "active",
}
_MANAGER_KHONG_DON_VI = {
    "username": "v3tt_manager_no_unit",
    "email": "v3tt_manager_no_unit@example.com",
    "password": "ManagerPassword!345",
    "role": "manager",
    "status": "active",
}


async def _ho_so(status="draft", unit_id=1, assigned_officer_id=None, **cot):
    so = next(_DEM)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name="V3 doi thong tu %d" % so,
                phone="07%08d" % so,
                email="v3tt-%d@example.com" % so,
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
            )
            s.add(lead)
            await s.flush()
            p = models.AdmissionProfile(
                lead_id=lead.id,
                status=status,
                citizen_id="081%09d" % so,
                version=1,
                applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
                academic_year=2026,
                **cot,
            )
            s.add(p)
            await s.flush()
            return p.id


async def _doi(client, headers, pid, *, circular=ac.TT76_2026, version=1, reason=_LY_DO, ack=False):
    return await client.post(
        "/api/v2/admissions/%d/applicable-circular" % pid,
        json={"version": version, "circular": circular, "reason": reason, "acknowledge_post_publish": ack},
        headers=headers,
    )


async def _doc(pid):
    async with AsyncSessionLocal() as s:
        p = (
            await s.execute(select(models.AdmissionProfile).where(models.AdmissionProfile.id == pid))
        ).scalar_one()
        return p.applicable_circular, p.applicable_circular_source, p.version


async def _nhat_ky(pid):
    async with AsyncSessionLocal() as s:
        return (
            (
                await s.execute(
                    select(PriorityAuditLog).where(
                        PriorityAuditLog.profile_id == pid, PriorityAuditLog.action_type == "circular_changed"
                    )
                )
            )
            .scalars()
            .all()
        )


# --- Đường đúng --------------------------------------------------------------------------------------


async def test_f0_manager_doi_tren_ho_so_nhap_cung_don_vi(client: AsyncClient, manager_token_headers):
    """Manager cùng đơn vị đổi được: cột ``manual``, version +1, đúng một hàng nhật ký, phản hồi mang thông tư mới.

    Đột biến: service quên ``profile.version += 1``.
    """
    pid = await _ho_so()
    r = await _doi(client, manager_token_headers, pid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["applicable_circular"], body["applicable_circular_effective_basis"]) == (ac.TT76_2026, "stored")
    assert await _doc(pid) == (ac.TT76_2026, ac.CIRCULAR_SOURCE_MANUAL, 2)
    assert len(await _nhat_ky(pid)) == 1


async def test_f12_doi_sang_dung_gia_tri_dang_co_bi_tu_choi(client: AsyncClient, manager_token_headers):
    """Đổi sang đúng thông tư đang có ⇒ 400, KHÔNG sinh hàng nhật ký rỗng.

    Đột biến: bỏ phép kiểm ``cu == circular``.
    """
    pid = await _ho_so(
        applicable_circular=ac.TT05_2021, applicable_circular_source=ac.CIRCULAR_SOURCE_MANUAL
    )
    r = await _doi(client, manager_token_headers, pid, circular=ac.TT05_2021)
    assert (r.status_code, len(await _nhat_ky(pid))) == (400, 0)


# --- F1: cùng giao dịch -----------------------------------------------------------------------------


async def test_f1_nhat_ky_hong_thi_cot_cung_khong_doi(client: AsyncClient, manager_token_headers, monkeypatch):
    """Ghi nhật ký hỏng (CHECK action_type) ⇒ cột thông tư KHÔNG được ghi: cột và nhật ký cùng một giao dịch.

    Đột biến: service ``commit`` cột trước rồi mới ghi nhật ký (hoặc ghi nhật ký ở phiên riêng).
    """

    def _nhat_ky_hong(**kw):
        kw["action_type"] = "khong_hop_le"
        return PriorityAuditLog(**kw)

    monkeypatch.setattr(applicable_circular_service, "models", SimpleNamespace(PriorityAuditLog=_nhat_ky_hong))
    pid = await _ho_so()
    try:
        await _doi(client, manager_token_headers, pid)
    except Exception:  # noqa: BLE001 — ca chỉ xét trạng thái CSDL sau lỗi
        pass
    assert await _doc(pid) == (None, None, 1)


# --- F2–F5: ai được gọi -----------------------------------------------------------------------------


async def test_f2_officer_bi_tu_choi(client: AsyncClient, officer_user_in_db, officer_token_headers):
    """Officer ĐƯỢC GÁN lead (qua được IDOR) ⇒ 403. Không gán thì dependency IDOR chặn trước bằng 404 và ca không
    còn đo được lớp quyền.

    Hai lớp chặn (Casbin + service) ⇒ ca HTTP này chỉ đỏ khi gỡ CẢ HAI; từng lớp có ca riêng (F2b, F2c).
    """
    pid = await _ho_so(assigned_officer_id=officer_user_in_db["id"])
    r = await _doi(client, officer_token_headers, pid)
    assert r.status_code == 403


async def test_f3_accountant_bi_tu_choi_du_ke_thua_officer(client: AsyncClient, seed_lead_dependencies):
    """Accountant cùng đơn vị ⇒ 403 nhờ dòng DENY tường minh.

    Đột biến: gỡ dòng deny khỏi ``ACCOUNTANT_TEMPLATE`` VÀ thêm allow cho officer (accountant kế thừa officer).
    """
    user = await _create_user_and_role(_ACCOUNTANT, "role:accountant", unit_id=seed_lead_dependencies["unit_id"])
    headers = await _get_token_headers(client, user)
    pid = await _ho_so()
    r = await _doi(client, headers, pid)
    assert r.status_code == 403


async def test_f4_manager_khac_don_vi_404(
    client: AsyncClient, seed_lead_dependencies, manager_other_unit_user_in_db
):
    """Manager ở đơn vị khác ⇒ 404 (không lộ hồ sơ tồn tại).

    Đột biến: dùng dependency không xét phạm vi đơn vị thay ``get_admission_for_user``.
    """
    headers = await _get_token_headers(client, manager_other_unit_user_in_db)
    pid = await _ho_so()
    r = await _doi(client, headers, pid)
    assert r.status_code == 404


async def test_f5_manager_khong_don_vi_404(client: AsyncClient, seed_lead_dependencies):
    """Manager KHÔNG có đơn vị ⇒ 404 trên hồ sơ của đơn vị 1.

    Kế hoạch v1 (K9) nêu thêm ca "lead không đơn vị" — không tồn tại: ``lead.unit_id`` NOT NULL. Ca này đo mã IDOR
    HIỆN CÓ (``get_admission_for_user``), không phải mã V3.
    """
    user = await _create_user_and_role(_MANAGER_KHONG_DON_VI, "role:manager", unit_id=None)
    headers = await _get_token_headers(client, user)
    pid = await _ho_so()
    r = await _doi(client, headers, pid)
    assert r.status_code == 404, r.text


# --- F6–F10: điều kiện ------------------------------------------------------------------------------


async def test_f6_version_cu_409(client: AsyncClient, manager_token_headers):
    """``version`` cũ ⇒ 409, cột không đổi.

    Đột biến: bỏ phép kiểm version.
    """
    pid = await _ho_so()
    r = await _doi(client, manager_token_headers, pid, version=0)
    assert (r.status_code, await _doc(pid)) == (409, (None, None, 1))


async def test_f7_sau_cong_bo_manager_bi_tu_choi_ke_ca_co_co(client: AsyncClient, manager_token_headers):
    """Hồ sơ ``approved``: manager gửi kèm cờ xác nhận vẫn ⇒ 403.

    Đột biến: cho manager qua khi có cờ.
    """
    pid = await _ho_so("approved")
    r = await _doi(client, manager_token_headers, pid, ack=True)
    assert r.status_code == 403


async def test_f8a_sau_cong_bo_admin_thieu_co_400(client: AsyncClient, seed_lead_dependencies, admin_token_headers):
    """Hồ sơ ``approved``: admin KHÔNG gửi cờ xác nhận ⇒ 400.

    Đột biến: bỏ phép kiểm cờ.
    """
    pid = await _ho_so("approved")
    r = await _doi(client, admin_token_headers, pid, ack=False)
    assert (r.status_code, await _doc(pid)) == (400, (None, None, 1))


async def test_f8b_sau_cong_bo_admin_co_co_duoc_va_ghi_co(
    client: AsyncClient, seed_lead_dependencies, admin_token_headers
):
    """Hồ sơ ``approved``: admin có cờ ⇒ 200 và nhật ký ghi ``acknowledged_post_publish: true``.

    Đột biến: không ghi cờ vào metadata nhật ký.
    """
    pid = await _ho_so("approved")
    r = await _doi(client, admin_token_headers, pid, ack=True)
    assert r.status_code == 200, r.text
    hang = await _nhat_ky(pid)
    assert [h.audit_metadata.get("acknowledged_post_publish") for h in hang] == [True]


async def test_f9_trang_thai_cam_tu_choi_ca_admin_co_co(
    client: AsyncClient, seed_lead_dependencies, admin_token_headers
):
    """``withdrawn`` / ``rejected`` / ``withdrawal_pending``: admin có cờ vẫn ⇒ 400.

    Đột biến: bớt một phần tử khỏi ``_HARD_DENIED_STATUS``.
    """
    ket_qua = {}
    for status in ("withdrawn", "rejected", "withdrawal_pending"):
        pid = await _ho_so(status)
        ket_qua[status] = (await _doi(client, admin_token_headers, pid, ack=True)).status_code
    assert ket_qua == {"withdrawn": 400, "rejected": 400, "withdrawal_pending": 400}


async def test_f10_ly_do_ngan_422(client: AsyncClient, manager_token_headers):
    """Lý do 19 ký tự ⇒ 422 (schema).

    Đột biến: hạ ``min_length`` của request xuống 10.
    """
    pid = await _ho_so()
    r = await _doi(client, manager_token_headers, pid, reason="x" * 19)
    assert r.status_code == 422


async def test_f10b_nguong_ly_do_schema_bang_service():
    """Ngưỡng lý do của request = ngưỡng của service ấn định KV (một nguồn).

    Đột biến: đổi ``max_length`` của request thành 400.
    """
    from app.schemas.admission import ApplicableCircularChangeRequest

    f = ApplicableCircularChangeRequest.model_fields["reason"]
    gioi_han = {type(m).__name__: m for m in f.metadata}
    assert (gioi_han["MinLen"].min_length, gioi_han["MaxLen"].max_length) == (
        priority_override_service._MIN_REASON_LEN,
        priority_override_service._MAX_REASON_LEN,
    )


async def test_f11_dung_chinh_tap_trang_thai_cua_an_dinh_kv():
    """Service đổi thông tư dùng CHÍNH hai tập trạng thái của ``priority_override_service`` (phép so ``is``).

    Đột biến: chép tập thành hằng mới trong ``applicable_circular_service``.
    """
    assert applicable_circular_service._HARD_DENIED_STATUS is priority_override_service._HARD_DENIED_STATUS
    assert applicable_circular_service._POST_PUBLISH_STATUS is priority_override_service._POST_PUBLISH_STATUS


async def test_f13_co_quyen_cung_ma_tran_voi_service():
    """Cờ ``permissions.change_applicable_circular`` theo đúng ma trận: cấm ⇒ ai cũng không; sau công bố ⇒ chỉ
    admin; còn lại ⇒ manager + admin.

    Đột biến: cờ cho manager ở trạng thái sau công bố.
    """
    co = admission_service._co_quyen_doi_thong_tu
    assert [co(s, is_admin=False, is_manager=True) for s in ("draft", "approved", "withdrawn")] == [True, False, False]
    assert [co(s, is_admin=True, is_manager=False) for s in ("draft", "approved", "withdrawn")] == [True, True, False]


# --- Từng lớp phòng thủ, kiểm RIÊNG ---------------------------------------------------------------
# Officer/accountant bị chặn ở CẢ Casbin (tầng chủ sở hữu, deps) LẪN phép kiểm vai trò trong service (chiều sâu).
# Ca HTTP F2/F3 chỉ đỏ khi gỡ CẢ HAI lớp ⇒ mỗi lớp cần một ca riêng thì mới chứng minh được nó còn canh.

_ROUTE = "/api/v2/admissions/*/applicable-circular"


async def test_f2b_service_tu_choi_vai_tro_khong_phai_manager_admin():
    """Lớp service: officer / accountant / user ⇒ ``PermissionError`` dù Casbin có lọt.

    Đột biến: bỏ phép kiểm ``actor.role`` trong ``change_applicable_circular``.
    """
    ket_qua = {}
    for vai_tro in ("officer", "accountant", "user"):
        ho_so = SimpleNamespace(
            id=1, version=1, status="draft", applicable_circular=None, applicable_circular_source=None
        )
        try:
            await applicable_circular_service.change_applicable_circular(
                None, ho_so, circular=ac.TT76_2026, reason=_LY_DO, expected_version=1,
                actor=SimpleNamespace(id=9, role=vai_tro),
            )
            ket_qua[vai_tro] = None
        except Exception as e:  # noqa: BLE001 — ca so đúng LOẠI lỗi ngay dưới
            ket_qua[vai_tro] = type(e).__name__
    assert ket_qua == {"officer": "PermissionError", "accountant": "PermissionError", "user": "PermissionError"}


def _dong_cua(template) -> list:
    return sorted(
        (p["action"], p.get("eft", "allow")) for p in template["policies"] if p["object"] == _ROUTE
    )


async def test_f2c_template_casbin_dung_ma_tran():
    """Lớp Casbin (template — nguồn seed dev/test): manager allow; accountant DENY tường minh; officer KHÔNG có dòng.

    Đột biến: thêm dòng allow cho officer vào ``OFFICER_TEMPLATE`` (hoặc gỡ dòng deny của accountant).
    """
    from app.casbin_config.policy_templates import ACCOUNTANT_TEMPLATE, MANAGER_TEMPLATE, OFFICER_TEMPLATE

    assert (_dong_cua(MANAGER_TEMPLATE), _dong_cua(ACCOUNTANT_TEMPLATE), _dong_cua(OFFICER_TEMPLATE)) == (
        [("POST", "allow")],
        [("POST", "deny")],
        [],
    )


async def test_f3d_migration_seed_bang_template():
    """Migration ``v3circ20261011b`` (nguồn seed production) seed đúng ma trận của template.

    Đột biến: bỏ dòng ``role:accountant … deny`` khỏi ``POLICIES`` của migration.
    """
    import importlib.util
    import pathlib

    duong = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic" / "versions" / "v3circ20261011b_circular_audit_actions_and_casbin.py"
    )
    spec = importlib.util.spec_from_file_location("_v3circ20261011b_cho_f3d", duong)
    m4 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m4)
    assert sorted((v0, v2, v3) for v0, v1, v2, v3 in m4.POLICIES if v1 == _ROUTE) == [
        ("role:accountant", "POST", "deny"),
        ("role:admin", "POST", "allow"),
        ("role:manager", "POST", "allow"),
    ]
