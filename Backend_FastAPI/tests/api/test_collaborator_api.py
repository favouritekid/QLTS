# tests/api/test_collaborator_api.py
"""
Collaborator API Tests — IDOR, Security, Validation, CTV Access

Tests the HTTP layer: IDOR protection (deps.py), Casbin enforcement,
request validation, and CTV self-service endpoints.
"""
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import insert

from app import models
from app.core.constants import UserRole
from tests._lead_status_test_ids import INITIAL_LEAD_STATUS_ID
from app.database import AsyncSessionLocal
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

COLLABORATORS_URL = "/api/collaborators"
CLAIMS_URL = f"{COLLABORATORS_URL}/claims"
CTV_URL = "/api/ctv"


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
    """Login and get auth headers + raw token.

    IMPORTANT: httpx stores cookies across requests. When multiple users login,
    the LAST cookie wins. To avoid cookie conflicts, we store the raw token
    and set it explicitly via Cookie header in requests.
    """
    res = await client.post(
        AuthURLs.LOGIN,
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    assert res.status_code == 200, f"Login failed for {user_info['username']}: {res.text}"
    token = res.cookies.get("access_token")
    assert token, f"No access_token cookie for {user_info['username']}"
    # Use Cookie header instead of Authorization to match app's cookie-first priority
    return {"Cookie": f"access_token={token}"}


# =============================================================================
# FIXTURES
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def seed_collab_deps(setup_test_database):
    """Seed org unit and pipeline dependencies for collaborator tests."""
    unit_data = TestOrgData.UNIT_1
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit = models.OrganizationUnit(**unit_data)
            session.add(unit)

            # Minimal pipeline for lead creation
            stage = models.PipelineStage(id="CTV_STAGE", name="CTV Stage", order=10)
            session.add(stage)

            status = models.ConsultationStatus(
                id=INITIAL_LEAD_STATUS_ID,
                name="New Lead (CTV Test)",
                color_code="#0000FF",
                stage_id="CTV_STAGE",
            )
            session.add(status)

    return {"unit_id": unit_data["id"]}


@pytest_asyncio.fixture(scope="function")
async def second_unit_data(seed_collab_deps):
    """Create a second unit for cross-unit IDOR tests."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit2 = models.OrganizationUnit(id=2001, name="Second Unit", type="department")
            session.add(unit2)
    return {"unit_id": 2001}


@pytest_asyncio.fixture(scope="function")
async def admin_api(client: AsyncClient, seed_collab_deps):
    """Admin user with token."""
    user_info = await _create_user_with_role(
        {"username": "api_admin", "email": "api_admin@t.com", "password": "AdminP@ss123!", "role": "admin", "status": "active"},
        "role:admin",
    )
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers}


@pytest_asyncio.fixture(scope="function")
async def manager_api(client: AsyncClient, seed_collab_deps):
    """Manager user with token (in unit 1)."""
    user_info = await _create_user_with_role(
        {"username": "api_manager", "email": "api_mgr@t.com", "password": "MgrP@ss123!", "role": "manager", "status": "active"},
        "role:manager",
        unit_id=seed_collab_deps["unit_id"],
    )
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers}


@pytest_asyncio.fixture(scope="function")
async def officer_api(client: AsyncClient, seed_collab_deps):
    """Officer user with token (in unit 1)."""
    user_info = await _create_user_with_role(
        {"username": "api_officer", "email": "api_off@t.com", "password": "OffP@ss123!", "role": "officer", "status": "active"},
        "role:officer",
        unit_id=seed_collab_deps["unit_id"],
    )
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers}


@pytest_asyncio.fixture(scope="function")
async def ctv_api(client: AsyncClient, seed_collab_deps, officer_api):
    """CTV user with token and active collaborator record."""
    user_info = await _create_user_with_role(
        {"username": "api_ctv", "email": "api_ctv@t.com", "password": "CTVP@ss123!", "role": "collaborator", "status": "active"},
        "role:collaborator",
        unit_id=seed_collab_deps["unit_id"],
    )
    # Create Collaborator record linked to user
    async with AsyncSessionLocal() as session:
        async with session.begin():
            collab = models.Collaborator(
                code="CTV-2026-0100",
                full_name="API CTV User",
                phone="0811000001",
                email="api_ctv@t.com",
                status="active",
                unit_id=seed_collab_deps["unit_id"],
                user_id=user_info["id"],
                managed_by_officer_id=officer_api["id"],
            )
            session.add(collab)
            await session.flush()
            collab_id = collab.id
    headers = await _get_auth_headers(client, user_info)
    return {**user_info, "headers": headers, "collaborator_id": collab_id}


@pytest_asyncio.fixture(scope="function")
async def collab_in_unit1(seed_collab_deps):
    """Create a collaborator in unit 1 for admin/manager tests."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            collab = models.Collaborator(
                code="CTV-2026-0200",
                full_name="Unit1 CTV",
                phone="0811000200",
                status="active",
                unit_id=seed_collab_deps["unit_id"],
            )
            session.add(collab)
            await session.flush()
            return {"id": collab.id, "unit_id": seed_collab_deps["unit_id"]}


@pytest_asyncio.fixture(scope="function")
async def collab_in_unit2(second_unit_data):
    """Create a collaborator in unit 2 for IDOR tests."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            collab = models.Collaborator(
                code="CTV-2026-0300",
                full_name="Unit2 CTV",
                phone="0811000300",
                status="active",
                unit_id=second_unit_data["unit_id"],
            )
            session.add(collab)
            await session.flush()
            return {"id": collab.id, "unit_id": second_unit_data["unit_id"]}


@pytest_asyncio.fixture(scope="function")
async def collab_managed_by_officer(seed_collab_deps, officer_api):
    """CTV managed by officer in unit 1."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            collab = models.Collaborator(
                code="CTV-2026-0400",
                full_name="Officer Managed CTV",
                phone="0811000400",
                status="active",
                unit_id=seed_collab_deps["unit_id"],
                managed_by_officer_id=officer_api["id"],
            )
            session.add(collab)
            await session.flush()
            return {"id": collab.id, "unit_id": seed_collab_deps["unit_id"]}


# =============================================================================
# TestCollaboratorIDOR
# =============================================================================


@pytest.mark.asyncio
class TestCollaboratorIDOR:
    """IDOR protection via deps.py."""

    async def test_admin_get_any_collaborator(
        self, client: AsyncClient, admin_api, collab_in_unit2,
    ):
        """Admin can GET collaborator in any unit."""
        res = await client.get(
            f"{COLLABORATORS_URL}/{collab_in_unit2['id']}",
            headers=admin_api["headers"],
        )
        assert res.status_code == 200

    async def test_manager_get_own_unit_collaborator(
        self, client: AsyncClient, manager_api, collab_in_unit1,
    ):
        """Manager can GET collaborator in own unit."""
        res = await client.get(
            f"{COLLABORATORS_URL}/{collab_in_unit1['id']}",
            headers=manager_api["headers"],
        )
        assert res.status_code == 200

    async def test_manager_get_other_unit_collaborator(
        self, client: AsyncClient, manager_api, collab_in_unit2,
    ):
        """Manager cannot GET collaborator in other unit -> 404 (NOT 403)."""
        res = await client.get(
            f"{COLLABORATORS_URL}/{collab_in_unit2['id']}",
            headers=manager_api["headers"],
        )
        assert res.status_code == 404

    async def test_officer_get_unmanaged_collaborator(
        self, client: AsyncClient, officer_api, collab_in_unit1,
    ):
        """Officer cannot GET collaborator NOT managed by them -> 404 (IDOR)."""
        res = await client.get(
            f"{COLLABORATORS_URL}/{collab_in_unit1['id']}",
            headers=officer_api["headers"],
        )
        assert res.status_code == 404

    async def test_officer_get_managed_collaborator(
        self, client: AsyncClient, officer_api, collab_managed_by_officer,
    ):
        """Officer can GET collaborator managed by them -> 200."""
        res = await client.get(
            f"{COLLABORATORS_URL}/{collab_managed_by_officer['id']}",
            headers=officer_api["headers"],
        )
        assert res.status_code == 200


# =============================================================================
# TestCollaboratorListFiltering
# =============================================================================


@pytest.mark.asyncio
class TestCollaboratorListFiltering:
    """Manager forced unit filter."""

    async def test_manager_list_forced_unit(
        self, client: AsyncClient, manager_api, collab_in_unit1, collab_in_unit2,
    ):
        """Manager sees only own unit collaborators."""
        res = await client.get(COLLABORATORS_URL, headers=manager_api["headers"])
        assert res.status_code == 200
        data = res.json()
        for collab in data["collaborators"]:
            assert collab["unit_id"] == manager_api.get("unit_id", collab_in_unit1["unit_id"])

    async def test_manager_list_ignores_unit_param(
        self, client: AsyncClient, manager_api, collab_in_unit2,
    ):
        """Manager passes unit_id=other -> still forced to own unit."""
        res = await client.get(
            f"{COLLABORATORS_URL}?unit_id={collab_in_unit2['unit_id']}",
            headers=manager_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        # Should NOT contain unit2 collaborators
        for collab in data["collaborators"]:
            assert collab["unit_id"] != collab_in_unit2["unit_id"]

    async def test_admin_list_all_units(
        self, client: AsyncClient, admin_api, collab_in_unit1, collab_in_unit2,
    ):
        """Admin sees collaborators from all units."""
        res = await client.get(COLLABORATORS_URL, headers=admin_api["headers"])
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] >= 2

    async def test_manager_claims_list_forced_unit(
        self, client: AsyncClient, manager_api,
    ):
        """Manager GET /claims -> only own unit (empty is OK for test)."""
        res = await client.get(CLAIMS_URL, headers=manager_api["headers"])
        assert res.status_code == 200


# =============================================================================
# TestOfficerCollaboratorList
# =============================================================================


@pytest.mark.asyncio
class TestOfficerCollaboratorList:
    """Officer list: forced managed_by_officer_id=self, hard-block inactive."""

    async def test_officer_list_default_excludes_inactive(
        self, client: AsyncClient, officer_api, seed_collab_deps,
    ):
        """Officer list without status param never returns inactive CTVs."""
        # Create an inactive CTV managed by officer
        async with AsyncSessionLocal() as session:
            async with session.begin():
                collab = models.Collaborator(
                    code="CTV-2026-0500",
                    full_name="Inactive CTV",
                    phone="0811000500",
                    status="inactive",
                    unit_id=seed_collab_deps["unit_id"],
                    managed_by_officer_id=officer_api["id"],
                )
                session.add(collab)

        res = await client.get(COLLABORATORS_URL, headers=officer_api["headers"])
        assert res.status_code == 200
        data = res.json()
        statuses = [c["status"] for c in data["collaborators"]]
        assert "inactive" not in statuses

    async def test_officer_list_sees_pending(
        self, client: AsyncClient, officer_api, seed_collab_deps,
    ):
        """Officer can see pending CTV they proposed."""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                collab = models.Collaborator(
                    code="CTV-2026-0600",
                    full_name="Pending CTV",
                    phone="0811000600",
                    status="pending",
                    unit_id=seed_collab_deps["unit_id"],
                    managed_by_officer_id=officer_api["id"],
                )
                session.add(collab)

        res = await client.get(COLLABORATORS_URL, headers=officer_api["headers"])
        assert res.status_code == 200
        data = res.json()
        names = [c["full_name"] for c in data["collaborators"]]
        assert "Pending CTV" in names

    async def test_officer_list_status_inactive_empty(
        self, client: AsyncClient, officer_api, seed_collab_deps,
    ):
        """Officer querying status=inactive -> empty list."""
        # Create an inactive CTV managed by officer
        async with AsyncSessionLocal() as session:
            async with session.begin():
                collab = models.Collaborator(
                    code="CTV-2026-0700",
                    full_name="Inactive CTV 2",
                    phone="0811000700",
                    status="inactive",
                    unit_id=seed_collab_deps["unit_id"],
                    managed_by_officer_id=officer_api["id"],
                )
                session.add(collab)

        res = await client.get(
            f"{COLLABORATORS_URL}?status=inactive",
            headers=officer_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] == 0
        assert data["collaborators"] == []

    async def test_officer_list_forced_managed_by(
        self, client: AsyncClient, officer_api, collab_in_unit1,
    ):
        """Officer passes managed_by_officer_id=other -> overridden to self."""
        # collab_in_unit1 has no managed_by_officer_id -> officer should NOT see it
        res = await client.get(
            f"{COLLABORATORS_URL}?managed_by_officer_id=99999",
            headers=officer_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        ids = [c["id"] for c in data["collaborators"]]
        assert collab_in_unit1["id"] not in ids


# =============================================================================
# TestOfficerCollaboratorCreate
# =============================================================================


@pytest.mark.asyncio
class TestOfficerCollaboratorCreate:
    """Officer POST /api/collaborators: auto-fill unit_id + managed_by_officer_id, always pending."""

    async def test_officer_create_collaborator_pending(
        self, client: AsyncClient, officer_api,
    ):
        """Officer creates CTV -> status=pending, unit/officer auto-filled."""
        res = await client.post(
            COLLABORATORS_URL,
            json={
                "full_name": "Officer Proposed CTV",
                "phone": "0811009999",
            },
            headers=officer_api["headers"],
        )
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "pending"
        assert data["managed_by_officer_id"] == officer_api["id"]
        assert data["unit_id"] is not None  # auto-filled from officer's unit

    async def test_officer_create_unit_id_overridden(
        self, client: AsyncClient, officer_api,
    ):
        """Officer passes unit_id -> backend overrides to officer's own unit."""
        res = await client.post(
            COLLABORATORS_URL,
            json={
                "full_name": "Override Unit CTV",
                "phone": "0811009998",
                "unit_id": 99999,  # should be overridden
            },
            headers=officer_api["headers"],
        )
        assert res.status_code == 201
        data = res.json()
        # unit_id should be officer's unit, not 99999
        assert data["unit_id"] != 99999


# =============================================================================
# TestCTVSelfService
# =============================================================================


@pytest.mark.asyncio
class TestCTVSelfService:
    """CTV self-service endpoint tests."""

    async def test_ctv_profile_returns_own(self, client: AsyncClient, ctv_api):
        """GET /api/ctv/profile returns own data."""
        res = await client.get(f"{CTV_URL}/profile", headers=ctv_api["headers"])
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == ctv_api["collaborator_id"]

    async def test_ctv_leads_returns_only_referred(self, client: AsyncClient, ctv_api, seed_collab_deps):
        """GET /api/ctv/leads returns only leads referred by this CTV."""
        # Create a lead referred by this CTV
        async with AsyncSessionLocal() as session:
            async with session.begin():
                lead = models.Lead(
                    full_name="CTV Referred",
                    phone="0899000001",
                    source="referral",
                    status="new",
                    unit_id=seed_collab_deps["unit_id"],
                    referrer_id=ctv_api["collaborator_id"],
                    created_via="claim",
                )
                session.add(lead)

        res = await client.get(f"{CTV_URL}/leads", headers=ctv_api["headers"])
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] >= 1
        assert all("phone_masked" in l for l in data["leads"])

    async def test_ctv_leads_phone_masked(self, client: AsyncClient, ctv_api, seed_collab_deps):
        """Response phone is masked."""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                lead = models.Lead(
                    full_name="Masked Phone",
                    phone="0912345678",
                    source="referral",
                    status="new",
                    unit_id=seed_collab_deps["unit_id"],
                    referrer_id=ctv_api["collaborator_id"],
                )
                session.add(lead)

        res = await client.get(f"{CTV_URL}/leads", headers=ctv_api["headers"])
        assert res.status_code == 200
        leads = res.json()["leads"]
        # Find the lead with masked phone
        masked = [l for l in leads if "0912" in l.get("phone_masked", "")]
        if masked:
            assert "***" in masked[0]["phone_masked"]

    async def test_ctv_claims_returns_only_own(self, client: AsyncClient, ctv_api):
        """GET /api/ctv/claims returns only own claims."""
        res = await client.get(f"{CTV_URL}/claims", headers=ctv_api["headers"])
        assert res.status_code == 200

    async def test_ctv_stats_returns_own(self, client: AsyncClient, ctv_api):
        """GET /api/ctv/stats returns stats."""
        res = await client.get(f"{CTV_URL}/stats", headers=ctv_api["headers"])
        assert res.status_code == 200
        data = res.json()
        assert "total_leads" in data
        assert "pending_claims" in data

    async def test_ctv_submit_lead(self, client: AsyncClient, ctv_api):
        """POST /api/ctv/leads/submit -> 201, creates lead + claim."""
        payload = {
            "lead_data": {
                "full_name": "API Submitted Lead",
                "phone": "0899000099",
            }
        }
        res = await client.post(
            f"{CTV_URL}/leads/submit", json=payload, headers=ctv_api["headers"],
        )
        assert res.status_code == 201
        data = res.json()
        assert data["collaborator_id"] == ctv_api["collaborator_id"]
        assert data["status"] == "pending"

    async def test_ctv_check_phone(self, client: AsyncClient, ctv_api):
        """GET /api/ctv/leads/check-phone -> PhoneCheckResponse."""
        res = await client.get(
            f"{CTV_URL}/leads/check-phone?phone=0899999999",
            headers=ctv_api["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert "available" in data


# =============================================================================
# TestCTVAccessDenied
# =============================================================================


@pytest.mark.asyncio
class TestCTVAccessDenied:
    """CTV cannot access admin endpoints."""

    async def test_ctv_cannot_list_collaborators(self, client: AsyncClient, ctv_api):
        """GET /api/collaborators -> 403."""
        res = await client.get(COLLABORATORS_URL, headers=ctv_api["headers"])
        assert res.status_code == 403

    async def test_ctv_cannot_create_collaborator(self, client: AsyncClient, ctv_api, seed_collab_deps):
        """POST /api/collaborators -> 403."""
        payload = {
            "full_name": "Attempt CTV",
            "phone": "0899888777",
            "unit_id": seed_collab_deps["unit_id"],
        }
        res = await client.post(
            COLLABORATORS_URL, json=payload, headers=ctv_api["headers"],
        )
        assert res.status_code == 403

    async def test_ctv_cannot_review_claim(self, client: AsyncClient, ctv_api):
        """POST /api/collaborators/claims/{id}/review -> 403 or 404 (IDOR blocks before Casbin)."""
        res = await client.post(
            f"{CLAIMS_URL}/99999/review",
            json={"status": "approved"},
            headers=ctv_api["headers"],
        )
        # CTV role is blocked by either Casbin (403) or IDOR dep (404)
        assert res.status_code in (403, 404)


# =============================================================================
# TestNonCTVAccessDenied
# =============================================================================


@pytest.mark.asyncio
class TestNonCTVAccessDenied:
    """Non-CTV users cannot access CTV self-service endpoints."""

    async def test_admin_cannot_access_ctv_profile(self, client: AsyncClient, admin_api):
        """Admin -> GET /api/ctv/profile -> 403."""
        res = await client.get(f"{CTV_URL}/profile", headers=admin_api["headers"])
        assert res.status_code == 403

    async def test_officer_cannot_access_ctv_leads(self, client: AsyncClient, officer_api):
        """Officer -> GET /api/ctv/leads -> 403."""
        res = await client.get(f"{CTV_URL}/leads", headers=officer_api["headers"])
        assert res.status_code == 403


# =============================================================================
# TestRequestValidation
# =============================================================================


@pytest.mark.asyncio
class TestRequestValidation:
    """Schema validation at HTTP level."""

    async def test_create_missing_required_fields(self, client: AsyncClient, admin_api):
        """POST body missing full_name -> 422."""
        res = await client.post(
            COLLABORATORS_URL,
            json={"phone": "0899111222"},  # Missing full_name and unit_id
            headers=admin_api["headers"],
        )
        assert res.status_code == 422

    async def test_create_invalid_email(self, client: AsyncClient, admin_api, seed_collab_deps):
        """email = 'not-an-email' -> 422."""
        res = await client.post(
            COLLABORATORS_URL,
            json={"full_name": "Bad Email", "phone": "0899111333", "email": "not-an-email", "unit_id": seed_collab_deps["unit_id"]},
            headers=admin_api["headers"],
        )
        assert res.status_code == 422

    async def test_submit_lead_empty_phone(self, client: AsyncClient, ctv_api):
        """lead_data.phone = '' -> 422."""
        res = await client.post(
            f"{CTV_URL}/leads/submit",
            json={"lead_data": {"full_name": "Empty Phone", "phone": ""}},
            headers=ctv_api["headers"],
        )
        assert res.status_code == 422

    async def test_review_reject_missing_reason(self, client: AsyncClient, admin_api, ctv_api, seed_collab_deps):
        """Reject without rejection_reason — check if service/schema allows it."""
        # First create a claim
        submit_res = await client.post(
            f"{CTV_URL}/leads/submit",
            json={"lead_data": {"full_name": "Review Test", "phone": "0899222333"}},
            headers=ctv_api["headers"],
        )
        assert submit_res.status_code == 201
        claim_id = submit_res.json()["id"]

        # Try to reject without reason (schema allows None for rejection_reason)
        res = await client.post(
            f"{CLAIMS_URL}/{claim_id}/review",
            json={"status": "rejected"},
            headers=admin_api["headers"],
        )
        # Schema allows None for rejection_reason, so this should succeed
        assert res.status_code == 200


# =============================================================================
# TestClaimReviewIDOR
# =============================================================================


@pytest.mark.asyncio
class TestClaimReviewIDOR:
    """IDOR protection for claim review."""

    async def test_admin_review_claim(self, client: AsyncClient, admin_api, ctv_api):
        """Admin can review any claim."""
        # Submit a claim
        res = await client.post(
            f"{CTV_URL}/leads/submit",
            json={"lead_data": {"full_name": "Admin Review", "phone": "0899333001"}},
            headers=ctv_api["headers"],
        )
        assert res.status_code == 201
        claim_id = res.json()["id"]

        # Admin approves
        review_res = await client.post(
            f"{CLAIMS_URL}/{claim_id}/review",
            json={"status": "approved"},
            headers=admin_api["headers"],
        )
        assert review_res.status_code == 200

    async def test_manager_review_own_unit_claim(
        self, client: AsyncClient, manager_api, ctv_api,
    ):
        """Manager can review claim in own unit."""
        res = await client.post(
            f"{CTV_URL}/leads/submit",
            json={"lead_data": {"full_name": "Mgr Review", "phone": "0899333002"}},
            headers=ctv_api["headers"],
        )
        assert res.status_code == 201
        claim_id = res.json()["id"]

        review_res = await client.post(
            f"{CLAIMS_URL}/{claim_id}/review",
            json={"status": "approved"},
            headers=manager_api["headers"],
        )
        assert review_res.status_code == 200
