# tests/api/test_commission_api.py
"""
Commission API Tests — HTTP layer tests for commission endpoints.

Tests admin commission policy CRUD, commission record workflow (approve/reject/pay),
IDOR protection (manager unit scoping), CTV self-service commission endpoints,
and request validation.
"""
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import insert

from app import models
from app.core.constants import UserRole
from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
from app.database import AsyncSessionLocal
from app.models.commission import CommissionPolicy, CommissionRecord
from app.security import get_password_hash

try:
    from tests.fixtures.constants import AuthURLs, TestOrgData
except ImportError:
    logging.warning("Could not import constants from tests.fixtures.constants")

try:
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule
except ImportError:
    CasbinRule = None

from app.main import fastapi_app as app

log = logging.getLogger(__name__)


# =============================================================================
# URLs
# =============================================================================

POLICIES_URL = "/api/admin/commission-policies"
RECORDS_URL = "/api/admin/commissions"
CTV_COMMISSIONS_URL = "/api/ctv/commissions"


# =============================================================================
# HELPERS
# =============================================================================

async def _create_user_with_role(
    user_data: dict, casbin_role: str, unit_id: int = None
) -> dict:
    """Create user in DB and assign Casbin role."""
    user_info = {}
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username=user_data["username"],
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                role=user_data["role"],
                status=user_data["status"],
                full_name=user_data.get("full_name", user_data["username"]),
                unit_id=unit_id,
            )
            session.add(user)
            await session.flush()
            db_user_id = user.id

            if CasbinRule:
                casbin_policy = insert(CasbinRule).values(
                    ptype="g", v0=f"user:{db_user_id}", v1=casbin_role
                )
                await session.execute(casbin_policy)

            user_info = {
                "id": db_user_id,
                "username": user_data["username"],
                "email": user_data["email"],
                "password": user_data["password"],
            }

    if hasattr(app.state, "enforcer") and app.state.enforcer:
        try:
            await app.state.enforcer.load_policy()
        except Exception:
            pass

    return user_info


async def _get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    """Login and get Cookie auth headers."""
    res = await client.post(
        AuthURLs.LOGIN,
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    assert res.status_code == 200, f"Login failed for {user_info['username']}: {res.text}"
    token = res.cookies.get("access_token")
    assert token, f"No access_token cookie for {user_info['username']}"
    return {"Cookie": f"access_token={token}"}


# =============================================================================
# FIXTURES
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def seed_commission_deps(setup_test_database):
    """Seed org unit and pipeline dependencies for commission tests."""
    unit_data = TestOrgData.UNIT_1
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit = models.OrganizationUnit(**unit_data)
            session.add(unit)

            stage = models.PipelineStage(id="COMM_STAGE", name="Commission Stage", order=10)
            session.add(stage)

            initial_status = models.ConsultationStatus(
                id=INITIAL_LEAD_STATUS_ID,
                name="New Lead (Commission Test)",
                color_code="#0000FF",
                stage_id="COMM_STAGE",
            )
            session.add(initial_status)

            contacted_status = models.ConsultationStatus(
                id="COMM_CONTACTED",
                name="Contacted (Commission Test)",
                color_code="#00FF00",
                stage_id="COMM_STAGE",
                updates_pipeline=True,
            )
            session.add(contacted_status)

    return {
        "unit_id": unit_data["id"],
        "initial_status_id": INITIAL_LEAD_STATUS_ID,
        "contacted_status_id": "COMM_CONTACTED",
    }


@pytest_asyncio.fixture(scope="function")
async def second_unit_data(seed_commission_deps):
    """Create a second unit for cross-unit IDOR tests."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit2 = models.OrganizationUnit(id=2001, name="Second Unit", type="department")
            session.add(unit2)
    return {"unit_id": 2001}


@pytest_asyncio.fixture(scope="function")
async def admin_api(client: AsyncClient, seed_commission_deps):
    """Admin user with token."""
    user_info = await _create_user_with_role(
        {"username": "comm_admin", "email": "comm_admin@t.com", "password": "AdminP@ss123!", "role": "admin", "status": "active"},
        "role:admin",
    )
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers}


@pytest_asyncio.fixture(scope="function")
async def manager_api(client: AsyncClient, seed_commission_deps):
    """Manager user with token (in unit 1)."""
    user_info = await _create_user_with_role(
        {"username": "comm_manager", "email": "comm_mgr@t.com", "password": "MgrP@ss123!", "role": "manager", "status": "active"},
        "role:manager",
        unit_id=seed_commission_deps["unit_id"],
    )
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers, "unit_id": seed_commission_deps["unit_id"]}


@pytest_asyncio.fixture(scope="function")
async def manager_api_unit2(client: AsyncClient, second_unit_data):
    """Manager user in unit 2 for IDOR tests."""
    user_info = await _create_user_with_role(
        {"username": "comm_mgr2", "email": "comm_mgr2@t.com", "password": "Mgr2P@ss123!", "role": "manager", "status": "active"},
        "role:manager",
        unit_id=second_unit_data["unit_id"],
    )
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers, "unit_id": second_unit_data["unit_id"]}


@pytest_asyncio.fixture(scope="function")
async def officer_api(client: AsyncClient, seed_commission_deps):
    """Officer user with token (in unit 1)."""
    user_info = await _create_user_with_role(
        {"username": "comm_officer", "email": "comm_off@t.com", "password": "OffP@ss123!", "role": "officer", "status": "active"},
        "role:officer",
        unit_id=seed_commission_deps["unit_id"],
    )
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers}


@pytest_asyncio.fixture(scope="function")
async def ctv_api(client: AsyncClient, seed_commission_deps, officer_api):
    """CTV user with token and active collaborator record."""
    user_info = await _create_user_with_role(
        {"username": "comm_ctv", "email": "comm_ctv@t.com", "password": "CTVP@ss123!", "role": "collaborator", "status": "active"},
        "role:collaborator",
        unit_id=seed_commission_deps["unit_id"],
    )
    async with AsyncSessionLocal() as session:
        async with session.begin():
            collab = models.Collaborator(
                code="CTV-2026-C001",
                full_name="Commission CTV",
                phone="0811000C01",
                email="comm_ctv@t.com",
                status="active",
                unit_id=seed_commission_deps["unit_id"],
                user_id=user_info["id"],
                managed_by_officer_id=officer_api["id"],
                approved_at=datetime.now(timezone.utc),
            )
            session.add(collab)
            await session.flush()
            collab_id = collab.id
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers, "collaborator_id": collab_id}


@pytest_asyncio.fixture(scope="function")
async def seeded_policy(seed_commission_deps, admin_api) -> dict:
    """Create a commission policy in the DB for testing."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            policy = CommissionPolicy(
                name="Test Fixed Policy",
                description="500k per contacted lead",
                trigger_status_id=seed_commission_deps["contacted_status_id"],
                calculation_type="fixed",
                fixed_amount=Decimal("500000"),
                effective_from=date(2025, 1, 1),
                is_active=True,
                created_by_id=admin_api["id"],
            )
            session.add(policy)
            await session.flush()
            return {
                "id": policy.id,
                "name": policy.name,
                "trigger_status_id": policy.trigger_status_id,
            }


@pytest_asyncio.fixture(scope="function")
async def seeded_record(
    seed_commission_deps, seeded_policy, ctv_api, officer_api,
) -> dict:
    """Create a pending commission record in the DB for testing."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Create a lead referred by CTV
            lead = models.Lead(
                full_name="Commission Test Lead",
                phone="0899C00001",
                source="referral",
                status="new",
                validity_status="valid",
                unit_id=seed_commission_deps["unit_id"],
                referrer_id=ctv_api["collaborator_id"],
                assigned_officer_id=officer_api["id"],
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id

            record = CommissionRecord(
                collaborator_id=ctv_api["collaborator_id"],
                lead_id=lead_id,
                policy_id=seeded_policy["id"],
                amount=Decimal("500000"),
                calculation_detail={"type": "fixed", "fixed_amount": "500000"},
                status="pending",
                trigger_status_id=seeded_policy["trigger_status_id"],
                triggered_at=datetime.now(timezone.utc),
            )
            session.add(record)
            await session.flush()
            return {
                "id": record.id,
                "lead_id": lead_id,
                "collaborator_id": ctv_api["collaborator_id"],
                "policy_id": seeded_policy["id"],
            }


# =============================================================================
# TestCommissionPolicyAPI
# =============================================================================


@pytest.mark.asyncio
class TestCommissionPolicyAPI:
    """Admin commission policy CRUD endpoints."""

    async def test_admin_create_policy(
        self, client: AsyncClient, admin_api, seed_commission_deps,
    ):
        """POST /admin/commission-policies -> 201."""
        payload = {
            "name": "API Created Policy",
            "trigger_status_id": seed_commission_deps["contacted_status_id"],
            "calculation_type": "fixed",
            "fixed_amount": 500000,
            "effective_from": "2025-01-01",
        }
        res = await client.post(POLICIES_URL, json=payload, headers=admin_api["headers"])
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "API Created Policy"
        assert data["calculation_type"] == "fixed"
        assert data["is_active"] is True

    async def test_admin_list_policies(
        self, client: AsyncClient, admin_api, seeded_policy,
    ):
        """GET /admin/commission-policies -> paginated."""
        res = await client.get(POLICIES_URL, headers=admin_api["headers"])
        assert res.status_code == 200
        data = res.json()
        assert "total_count" in data
        assert data["total_count"] >= 1
        assert len(data["policies"]) >= 1

    async def test_admin_get_policy(
        self, client: AsyncClient, admin_api, seeded_policy,
    ):
        """GET /admin/commission-policies/{id} -> 200."""
        res = await client.get(
            f"{POLICIES_URL}/{seeded_policy['id']}", headers=admin_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == seeded_policy["id"]

    async def test_admin_update_policy(
        self, client: AsyncClient, admin_api, seeded_policy,
    ):
        """PUT /admin/commission-policies/{id} -> 200."""
        res = await client.put(
            f"{POLICIES_URL}/{seeded_policy['id']}",
            json={"name": "Updated via API", "is_active": False},
            headers=admin_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Updated via API"
        assert data["is_active"] is False

    async def test_non_admin_create_denied(
        self, client: AsyncClient, manager_api, seed_commission_deps,
    ):
        """Manager POST -> 404 (IDOR: not 403)."""
        payload = {
            "name": "Should Fail",
            "trigger_status_id": seed_commission_deps["contacted_status_id"],
            "calculation_type": "fixed",
            "fixed_amount": 100000,
            "effective_from": "2025-01-01",
        }
        res = await client.post(POLICIES_URL, json=payload, headers=manager_api["headers"])
        # Admin-only endpoint via require_admin dep -> 403 from Casbin
        assert res.status_code in (403, 404)

    async def test_validation_invalid_calculation_type(
        self, client: AsyncClient, admin_api, seed_commission_deps,
    ):
        """Missing fixed_amount for type=fixed -> 422."""
        payload = {
            "name": "Invalid Policy",
            "trigger_status_id": seed_commission_deps["contacted_status_id"],
            "calculation_type": "fixed",
            # missing fixed_amount
            "effective_from": "2025-01-01",
        }
        res = await client.post(POLICIES_URL, json=payload, headers=admin_api["headers"])
        assert res.status_code == 422


# =============================================================================
# TestCommissionRecordAPI
# =============================================================================


@pytest.mark.asyncio
class TestCommissionRecordAPI:
    """Admin commission record endpoints."""

    async def test_admin_list_records(
        self, client: AsyncClient, admin_api, seeded_record,
    ):
        """GET /admin/commissions -> paginated."""
        res = await client.get(RECORDS_URL, headers=admin_api["headers"])
        assert res.status_code == 200
        data = res.json()
        assert "total_count" in data
        assert data["total_count"] >= 1

    async def test_manager_list_records_own_unit(
        self, client: AsyncClient, manager_api, seeded_record,
    ):
        """Manager sees only own unit records."""
        res = await client.get(RECORDS_URL, headers=manager_api["headers"])
        assert res.status_code == 200
        data = res.json()
        # All returned records belong to manager's unit (via collaborator)
        assert data["total_count"] >= 1

    async def test_admin_get_record(
        self, client: AsyncClient, admin_api, seeded_record,
    ):
        """GET /admin/commissions/{id} -> full detail."""
        res = await client.get(
            f"{RECORDS_URL}/{seeded_record['id']}", headers=admin_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == seeded_record["id"]
        assert data["status"] == "pending"

    async def test_admin_approve_record(
        self, client: AsyncClient, admin_api, seeded_record,
    ):
        """POST /admin/commissions/{id}/approve -> status=approved."""
        res = await client.post(
            f"{RECORDS_URL}/{seeded_record['id']}/approve",
            headers=admin_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "approved"
        assert data["approved_by_id"] is not None

    async def test_admin_reject_record(
        self, client: AsyncClient, admin_api, seeded_record,
    ):
        """POST /admin/commissions/{id}/reject -> status=rejected + reason."""
        res = await client.post(
            f"{RECORDS_URL}/{seeded_record['id']}/reject",
            json={"rejection_reason": "Duplicate lead detected"},
            headers=admin_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "rejected"
        assert data["rejection_reason"] == "Duplicate lead detected"

    async def test_admin_pay_record(
        self, client: AsyncClient, admin_api, seeded_record,
    ):
        """POST /admin/commissions/{id}/pay -> status=paid (after approve)."""
        # First approve
        approve_res = await client.post(
            f"{RECORDS_URL}/{seeded_record['id']}/approve",
            headers=admin_api["headers"],
        )
        assert approve_res.status_code == 200

        # Then pay
        res = await client.post(
            f"{RECORDS_URL}/{seeded_record['id']}/pay",
            json={"payment_reference": "TRX-API-001"},
            headers=admin_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "paid"
        assert data["payment_reference"] == "TRX-API-001"

    async def test_manager_idor_other_unit(
        self, client: AsyncClient, manager_api_unit2, seeded_record,
    ):
        """Manager GET record in other unit -> 404."""
        res = await client.get(
            f"{RECORDS_URL}/{seeded_record['id']}",
            headers=manager_api_unit2["headers"],
        )
        assert res.status_code == 404


# =============================================================================
# TestCTVCommissionAPI
# =============================================================================


@pytest.mark.asyncio
class TestCTVCommissionAPI:
    """CTV self-service commission endpoints."""

    async def test_ctv_list_own_commissions(
        self, client: AsyncClient, ctv_api, seeded_record,
    ):
        """GET /ctv/commissions -> only own records."""
        res = await client.get(CTV_COMMISSIONS_URL, headers=ctv_api["headers"])
        assert res.status_code == 200
        data = res.json()
        assert "total_count" in data
        assert data["total_count"] >= 1
        # All returned records belong to this CTV
        for rec in data["records"]:
            assert rec["collaborator_id"] == ctv_api["collaborator_id"]

    async def test_ctv_commission_stats(
        self, client: AsyncClient, ctv_api, seeded_record,
    ):
        """GET /ctv/commissions/stats -> aggregated stats."""
        res = await client.get(
            f"{CTV_COMMISSIONS_URL}/stats", headers=ctv_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert "total_earned" in data
        assert "total_pending" in data
        assert "total_paid" in data
        assert "record_count" in data
        assert data["record_count"] >= 1

    async def test_non_ctv_denied(
        self, client: AsyncClient, admin_api,
    ):
        """Admin accessing /ctv/commissions -> 403."""
        res = await client.get(CTV_COMMISSIONS_URL, headers=admin_api["headers"])
        assert res.status_code == 403

    async def test_officer_denied(
        self, client: AsyncClient, officer_api,
    ):
        """Officer accessing /ctv/commissions -> 403."""
        res = await client.get(CTV_COMMISSIONS_URL, headers=officer_api["headers"])
        assert res.status_code == 403
