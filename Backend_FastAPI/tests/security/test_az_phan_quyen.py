# tests/security/test_az_phan_quyen.py
"""Phân quyền theo phạm vi — test ÂM TÍNH cho bốn luồng.

Mỗi ca khoá ĐÚNG MỘT bất biến. Ca ``doi_chung_*`` là đối chứng dương: chúng
phải XANH cả trước lẫn sau bản vá, để chứng minh dữ liệu dựng đúng và các ca
âm không xanh vì endpoint hỏng.

Điều kiện tiên quyết lặp lại ở mọi ca âm: ``status < 500``. Đó không phải bất
biến thứ hai mà là chốt chống "xanh giả": một 500 không trả dữ liệu nên sẽ làm
bất biến "không lộ" xanh vì lý do sai.

(1) POST /api/collaborators kèm ``user_id``: create_collaborator ĐỔI User.role
    của người được gắn thành 'collaborator', mà Casbin lấy subject =
    role:{User.role} ⇒ gắn tài khoản nhân sự là tước quyền của họ. Chỉ được gắn
    tài khoản không phải nhân sự, và (trừ admin) chỉ trong đơn vị người gọi
    (chủ sở hữu: deps.validate_collaborator_create).
(2) drill-down khi phạm vi manager có 0 officer active: effective_officer_ids
    RỖNG phải ra 0 hàng, không được hiểu là "không lọc"
    (chủ sở hữu: drilldown_service._officer_scope_condition).
(3) GET /api/pipeline/board và GET /api/leads: phạm vi đơn vị chỉ lấy từ
    lead_filter (không fallback về ``unit_id`` client gửi); manager chưa gán
    đơn vị bị từ chối (chủ sở hữu: deps.get_lead_list_filter).
(4) GET /api/collaborators(+/claims): manager chưa gán đơn vị bị từ chối
    (chủ sở hữu: deps.manager_unit_scope_or_deny).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import insert, select

from app import models
from app.database import AsyncSessionLocal
from app.main import fastapi_app as app
from app.models.pipeline import OutcomeTypeEnum
from app.security import get_password_hash
from tests.fixtures.constants import AuthURLs, TestOrgData

try:
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule
except ImportError:  # pragma: no cover
    CasbinRule = None

pytestmark = [pytest.mark.security]

UNIT_A = TestOrgData.UNIT_1["id"]  # đơn vị của manager (seed_lead_dependencies)
UNIT_B = TestOrgData.UNIT_2["id"]  # đơn vị khác (seed_other_unit)
MAT_KHAU = "AzP@ssw0rd!2026"


# =============================================================================
# HELPER
# =============================================================================

async def _tao_user(username: str, role: str, unit_id=None) -> dict:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username=username,
                email=f"{username}@az.test",
                password_hash=get_password_hash(MAT_KHAU),
                role=role,
                status="active",
                full_name=f"AZ {username}",
                unit_id=unit_id,
            )
            session.add(user)
            await session.flush()
            uid = user.id
            if CasbinRule is not None:
                await session.execute(
                    insert(CasbinRule).values(ptype="g", v0=f"user:{uid}", v1=f"role:{role}")
                )
    if getattr(app.state, "enforcer", None):
        await app.state.enforcer.load_policy()
    return {"id": uid, "username": username, "password": MAT_KHAU}


async def _cookie(client: AsyncClient, user: dict) -> dict:
    client.cookies.clear()
    res = await client.post(
        AuthURLs.LOGIN, data={"username": user["username"], "password": user["password"]}
    )
    assert res.status_code == 200, f"login {user['username']}: {res.status_code} {res.text}"
    token = res.cookies.get("access_token")
    assert token, "thiếu cookie access_token"
    client.cookies.clear()
    return {"Cookie": f"access_token={token}"}


async def _goi(client: AsyncClient, method: str, url: str, headers: dict, **kw):
    # Xoá jar trước MỖI lượt gọi: app ưu tiên cookie, jar còn cookie của người
    # đăng nhập sau cùng sẽ âm thầm đổi danh tính của request.
    client.cookies.clear()
    return await client.request(method, url, headers=headers, **kw)


async def _role_cua(user_id: int) -> str:
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(models.User.role).where(models.User.id == user_id)
        )).scalar_one()


async def _tao_lead(full_name: str, phone: str, unit_id: int, officer_id=None,
                    stage_id="STAGE_A", status_id=None) -> int:
    from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=full_name,
                phone=phone,
                source="website",
                status="new",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                pipeline_stage_id=stage_id,
                consultation_status_id=status_id or INITIAL_LEAD_STATUS_ID,
            )
            session.add(lead)
            await session.flush()
            return lead.id


def _ids_board(body) -> set:
    if not isinstance(body, dict):
        return set()
    return {l["id"] for st in body.get("stages", []) for l in (st.get("leads") or [])}


def _ids(body, key: str, field: str = "id") -> set:
    if not isinstance(body, dict):
        return set()
    return {row[field] for row in (body.get(key) or [])}


def _json(res):
    try:
        return res.json()
    except Exception:  # noqa: BLE001
        return None


# =============================================================================
# (1) LIÊN KẾT user_id KHI TẠO CTV
# =============================================================================

@pytest_asyncio.fixture
async def az1(client: AsyncClient, seed_lead_dependencies, seed_other_unit):
    officer = await _tao_user("az1_officer", "officer", UNIT_A)
    return {"officer": officer, "headers": await _cookie(client, officer)}


@pytest.mark.asyncio
class TestAZ1LienKetUserKhiTaoCTV:

    async def test_officer_khong_doi_duoc_role_admin(self, client, az1):
        admin = await _tao_user("az1_admin", "admin", None)
        res = await _goi(client, "POST", "/api/collaborators", az1["headers"], json={
            "full_name": "CTV gan admin", "phone": "0912000101", "user_id": admin["id"],
        })
        assert res.status_code < 500, res.text
        assert await _role_cua(admin["id"]) == "admin"

    async def test_officer_khong_doi_duoc_role_manager_don_vi_khac(self, client, az1):
        mgr = await _tao_user("az1_mgr_b", "manager", UNIT_B)
        res = await _goi(client, "POST", "/api/collaborators", az1["headers"], json={
            "full_name": "CTV gan manager", "phone": "0912000102", "user_id": mgr["id"],
        })
        assert res.status_code < 500, res.text
        assert await _role_cua(mgr["id"]) == "manager"

    async def test_officer_khong_doi_duoc_role_user_don_vi_khac(self, client, az1):
        u = await _tao_user("az1_user_b", "user", UNIT_B)
        res = await _goi(client, "POST", "/api/collaborators", az1["headers"], json={
            "full_name": "CTV gan user B", "phone": "0912000103", "user_id": u["id"],
        })
        assert res.status_code < 500, res.text
        assert await _role_cua(u["id"]) == "user"

    async def test_officer_khong_doi_duoc_role_officer_cung_don_vi(self, client, az1):
        peer = await _tao_user("az1_officer_peer", "officer", UNIT_A)
        res = await _goi(client, "POST", "/api/collaborators", az1["headers"], json={
            "full_name": "CTV gan dong nghiep", "phone": "0912000104", "user_id": peer["id"],
        })
        assert res.status_code < 500, res.text
        assert await _role_cua(peer["id"]) == "officer"

    async def test_manager_khong_tao_duoc_ctv_o_don_vi_khac(self, client, az1):
        mgr = await _tao_user("az1_mgr_a", "manager", UNIT_A)
        h = await _cookie(client, mgr)
        res = await _goi(client, "POST", "/api/collaborators", h, json={
            "full_name": "CTV don vi khac", "phone": "0912000106", "unit_id": UNIT_B,
        })
        assert res.status_code < 500, res.text
        async with AsyncSessionLocal() as session:
            n = (await session.execute(
                select(models.Collaborator.id).where(
                    models.Collaborator.phone == "0912000106",
                    models.Collaborator.unit_id == UNIT_B,
                )
            )).all()
        assert n == []

    async def test_officer_khong_doi_duoc_role_accountant_cung_don_vi(self, client, az1):
        acc = await _tao_user("az1_accountant_a", "accountant", UNIT_A)
        res = await _goi(client, "POST", "/api/collaborators", az1["headers"], json={
            "full_name": "CTV gan ke toan", "phone": "0912000107", "user_id": acc["id"],
        })
        assert res.status_code < 500, res.text
        assert await _role_cua(acc["id"]) == "accountant"

    async def test_admin_khong_doi_duoc_role_officer(self, client, az1):
        # Vế "chỉ gắn tài khoản không phải nhân sự" áp cho MỌI vai, kể cả admin.
        admin = await _tao_user("az1_admin_goi", "admin", None)
        off = await _tao_user("az1_officer_bi_gan", "officer", UNIT_A)
        h = await _cookie(client, admin)
        res = await _goi(client, "POST", "/api/collaborators", h, json={
            "full_name": "CTV admin gan officer", "phone": "0912000108",
            "unit_id": UNIT_A, "user_id": off["id"],
        })
        assert res.status_code < 500, res.text
        assert await _role_cua(off["id"]) == "officer"

    async def test_manager_khong_doi_duoc_role_user_don_vi_khac(self, client, az1):
        # unit_id của CTV là đơn vị CỦA manager: chỉ vế "user được gắn phải cùng
        # đơn vị người gọi" chặn ca này.
        mgr = await _tao_user("az1_mgr_gan_user_b", "manager", UNIT_A)
        u = await _tao_user("az1_user_b_cho_mgr", "user", UNIT_B)
        h = await _cookie(client, mgr)
        res = await _goi(client, "POST", "/api/collaborators", h, json={
            "full_name": "CTV manager gan user B", "phone": "0912000109",
            "unit_id": UNIT_A, "user_id": u["id"],
        })
        assert res.status_code < 500, res.text
        assert await _role_cua(u["id"]) == "user"

    async def test_doi_chung_officer_lien_ket_user_cung_don_vi_van_duoc(self, client, az1):
        u = await _tao_user("az1_user_a", "user", UNIT_A)
        res = await _goi(client, "POST", "/api/collaborators", az1["headers"], json={
            "full_name": "CTV hop le", "phone": "0912000105", "user_id": u["id"],
        })
        assert res.status_code == 201, res.text


# =============================================================================
# (2) DRILL-DOWN KHI PHẠM VI CÓ 0 OFFICER ACTIVE
# =============================================================================

@pytest_asyncio.fixture
async def az2(client: AsyncClient, seed_lead_dependencies, seed_other_unit):
    # Đơn vị A: CHỈ có manager, KHÔNG officer active nào ⇒ effective_officer_ids = [].
    mgr = await _tao_user("az2_mgr_a", "manager", UNIT_A)
    officer_b = await _tao_user("az2_officer_b", "officer", UNIT_B)
    lead_b = await _tao_lead("AZ2 Lead B", "0912000201", UNIT_B, officer_b["id"])
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(models.Consultation(
                lead_id=lead_b, officer_id=officer_b["id"], method="phone",
                consultation_status_id="sts02",
            ))
            session.add(models.LeadStatusHistory(
                lead_id=lead_b, changed_by_user_id=officer_b["id"],
                old_status="new", new_status="contacted",
                old_pipeline_stage_id="STAGE_A", new_pipeline_stage_id="stg02",
                new_consultation_status_id="sts02",
            ))
            # Dữ liệu cho nhánh enrollments_monthly của get_transitions_drilldown.
            session.add(models.ConsultationStatus(
                id="az_pos_final", name="AZ nhap hoc", color_code="#00AA00",
                stage_id="stg06", is_final=True, counts_for_funnel=True,
                outcome_type=OutcomeTypeEnum.positive,
            ))
    lead_b2 = await _tao_lead("AZ2 Lead B2", "0912000202", UNIT_B, officer_b["id"],
                              stage_id="stg06", status_id="az_pos_final")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(models.LeadStatusHistory(
                lead_id=lead_b2, changed_by_user_id=officer_b["id"],
                old_status="contacted", new_status="enrolled",
                old_pipeline_stage_id="stg05", new_pipeline_stage_id="stg06",
                new_consultation_status_id="az_pos_final",
            ))
    return {
        "mgr": mgr, "officer_b": officer_b, "lead_b": lead_b, "lead_b2": lead_b2,
        "mgr_headers": await _cookie(client, mgr),
    }


@pytest.mark.asyncio
class TestAZ2DrilldownPhamViRong:

    async def test_consultations_manager_0_officer_khong_thay_don_vi_khac(self, client, az2):
        res = await _goi(client, "GET", "/api/officer/drilldowns/consultations", az2["mgr_headers"],
                         params={"scope": "unit", "metric_key": "consultations_today"})
        assert res.status_code < 500, res.text
        assert az2["lead_b"] not in _ids(_json(res), "rows", "lead_id")

    async def test_transitions_manager_0_officer_khong_thay_don_vi_khac(self, client, az2):
        res = await _goi(client, "GET", "/api/officer/drilldowns/transitions", az2["mgr_headers"],
                         params={"scope": "unit", "metric_key": "bottleneck"})
        assert res.status_code < 500, res.text
        assert az2["lead_b"] not in _ids(_json(res), "rows", "lead_id")

    async def test_enrollments_manager_0_officer_khong_thay_don_vi_khac(self, client, az2):
        res = await _goi(client, "GET", "/api/officer/drilldowns/transitions", az2["mgr_headers"],
                         params={"scope": "unit", "metric_key": "enrollments_monthly"})
        assert res.status_code < 500, res.text
        assert az2["lead_b2"] not in _ids(_json(res), "rows", "lead_id")

    async def test_cohorts_manager_0_officer_khong_thay_don_vi_khac(self, client, az2):
        res = await _goi(client, "GET", "/api/officer/drilldowns/cohorts", az2["mgr_headers"],
                         params={"scope": "unit", "metric_key": "new_lead_conversion"})
        assert res.status_code < 500, res.text
        assert az2["lead_b"] not in _ids(_json(res), "rows", "lead_id")

    async def test_officer_scope_organization_khong_thay_don_vi_khac(self, client, az2):
        # FE chuyển NGUYÊN query sang drill-down: officer xin scope=organization +
        # scope_unit_id lạ. get_officer_dashboard_scope chặn officer khác
        # 'personal' — ca này XANH cả trước bản vá, giữ lại để canh nó ở yên đó.
        off_a = await _tao_user("az2_officer_a_khac", "officer", UNIT_A)
        h = await _cookie(client, off_a)
        res = await _goi(client, "GET", "/api/officer/drilldowns/consultations", h,
                         params={"scope": "organization", "scope_unit_id": UNIT_B,
                                 "metric_key": "consultations_today"})
        assert res.status_code < 500, res.text
        assert az2["lead_b"] not in _ids(_json(res), "rows", "lead_id")

    async def test_doi_chung_admin_to_chuc_thay_tu_van_don_vi_khac(self, client, az2):
        admin = await _tao_user("az2_admin", "admin", None)
        h = await _cookie(client, admin)
        res = await _goi(client, "GET", "/api/officer/drilldowns/consultations", h,
                         params={"scope": "organization", "metric_key": "consultations_today"})
        assert az2["lead_b"] in _ids(_json(res), "rows", "lead_id"), res.text


# =============================================================================
# (3) PIPELINE BOARD
# =============================================================================

@pytest_asyncio.fixture
async def az3(client: AsyncClient, seed_lead_dependencies, seed_other_unit):
    # Đơn vị A KHÔNG có officer: tránh nhánh "đúng 1 officer" của get_lead_list_filter
    # tự thêm bộ lọc officer và che mất lỗi phạm vi đơn vị.
    mgr = await _tao_user("az3_mgr_a", "manager", UNIT_A)
    lead_a = await _tao_lead("AZ3 Lead A", "0912000301", UNIT_A)
    lead_b = await _tao_lead("AZ3 Lead B", "0912000302", UNIT_B)
    return {"mgr": mgr, "lead_a": lead_a, "lead_b": lead_b,
            "mgr_headers": await _cookie(client, mgr)}


@pytest.mark.asyncio
class TestAZ3PipelineBoard:

    async def test_board_manager_scope_va_unit_id_don_vi_khac_khong_lo(self, client, az3):
        res = await _goi(client, "GET", "/api/pipeline/board", az3["mgr_headers"],
                         params={"scope": "unit", "unit_id": UNIT_B})
        assert res.status_code < 500, res.text
        assert az3["lead_b"] not in _ids_board(_json(res))

    async def test_board_manager_scope_khong_unit_id_khong_lo(self, client, az3):
        res = await _goi(client, "GET", "/api/pipeline/board", az3["mgr_headers"],
                         params={"scope": "unit"})
        assert res.status_code < 500, res.text
        assert az3["lead_b"] not in _ids_board(_json(res))

    async def test_board_manager_unit_null_khong_lo(self, client, az3):
        mgr0 = await _tao_user("az3_mgr_null", "manager", None)
        h = await _cookie(client, mgr0)
        res = await _goi(client, "GET", "/api/pipeline/board", h)
        assert res.status_code < 500, res.text
        assert az3["lead_b"] not in _ids_board(_json(res))

    async def test_leads_list_manager_unit_null_khong_lo(self, client, az3):
        mgr0 = await _tao_user("az3_mgr_null2", "manager", None)
        h = await _cookie(client, mgr0)
        res = await _goi(client, "GET", "/api/leads", h, params={"page_size": 100})
        assert res.status_code < 500, res.text
        assert az3["lead_b"] not in _ids(_json(res), "leads")

    async def test_doi_chung_board_manager_thay_lead_don_vi_minh(self, client, az3):
        res = await _goi(client, "GET", "/api/pipeline/board", az3["mgr_headers"])
        assert az3["lead_a"] in _ids_board(_json(res)), res.text


# =============================================================================
# (4) DANH SÁCH CTV / CLAIM — manager unit_id NULL
# =============================================================================

@pytest_asyncio.fixture
async def az4(client: AsyncClient, seed_lead_dependencies, seed_other_unit):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            collab_a = models.Collaborator(code="CTV-AZ-0401", full_name="AZ CTV A",
                                           phone="0912000401", status="active", unit_id=UNIT_A)
            collab_b = models.Collaborator(code="CTV-AZ-0402", full_name="AZ CTV B",
                                           phone="0912000402", status="active", unit_id=UNIT_B)
            session.add_all([collab_a, collab_b])
            await session.flush()
            ids = {"collab_a": collab_a.id, "collab_b": collab_b.id}
    lead_b = await _tao_lead("AZ4 Lead B", "0912000403", UNIT_B)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            claim = models.LeadClaim(collaborator_id=ids["collab_b"], lead_id=lead_b,
                                     status="pending")
            session.add(claim)
            await session.flush()
            ids["claim_b"] = claim.id
    return ids


@pytest.mark.asyncio
class TestAZ4DanhSachCTVManagerKhongDonVi:

    async def test_list_ctv_manager_unit_null_khong_lo(self, client, az4):
        mgr0 = await _tao_user("az4_mgr_null", "manager", None)
        h = await _cookie(client, mgr0)
        res = await _goi(client, "GET", "/api/collaborators", h, params={"limit": 100})
        assert res.status_code < 500, res.text
        assert az4["collab_b"] not in _ids(_json(res), "collaborators")

    async def test_list_claims_manager_unit_null_khong_lo(self, client, az4):
        mgr0 = await _tao_user("az4_mgr_null2", "manager", None)
        h = await _cookie(client, mgr0)
        res = await _goi(client, "GET", "/api/collaborators/claims", h, params={"limit": 100})
        assert res.status_code < 500, res.text
        assert az4["claim_b"] not in _ids(_json(res), "claims")

    async def test_doi_chung_list_ctv_manager_co_unit_thay_ctv_don_vi_minh(self, client, az4):
        mgr = await _tao_user("az4_mgr_a", "manager", UNIT_A)
        h = await _cookie(client, mgr)
        res = await _goi(client, "GET", "/api/collaborators", h, params={"limit": 100})
        assert az4["collab_a"] in _ids(_json(res), "collaborators"), res.text
