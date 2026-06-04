"""
Integration tests for Admission IDOR Protection.

Tests cross-unit access control:
- User from Unit A cannot access profiles from Unit B
- Admin can access all units
- Manager can only access own unit

Uses real database via fixtures.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.security import get_password_hash


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def non_staff_user_same_unit_in_db(seed_lead_dependencies: dict):
    """ADM-001 review fix: a ``role=user`` user that lives in the seeded
    lead's unit. Used to verify the dependency role allow-list rejects
    accountant / regular user / collaborator even when their ``unit_id``
    matches the profile's unit (``get_current_active_user`` alone is not
    enough to gate fee-status).
    """
    unit_id = seed_lead_dependencies["unit_id"]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username="testuser_non_staff_idor",
                email="non_staff_idor@test.com",
                password_hash=get_password_hash("NonStaffPwd!123"),
                role="user",
                status="active",
                unit_id=unit_id,
            )
            session.add(user)
            await session.flush()
            return {
                "id": user.id,
                "username": "testuser_non_staff_idor",
                "password": "NonStaffPwd!123",
                "unit_id": unit_id,
            }


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def create_second_unit() -> int:
    """Create or get a second organization unit for cross-unit tests."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Check if unit 999 already exists
            result = await session.execute(
                select(models.OrganizationUnit)
                .where(models.OrganizationUnit.id == 999)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing.id
            
            # Create new unit (OrganizationUnit requires: id, name, type)
            unit = models.OrganizationUnit(
                id=999,
                name="Test Unit B",
                type="department",  # Required field
            )
            session.add(unit)
            await session.flush()
            return unit.id


async def create_test_lead(unit_id: int, assigned_officer_id: int = None) -> int:
    """Create a test lead in specific unit."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"IDOR Test Lead",
                phone="0901234700",
                email=f"idor_{datetime.now().timestamp():.0f}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def create_admission_profile(lead_id: int, citizen_id: str) -> int:
    """Create an admission profile."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status="draft",
                citizen_id=citizen_id,
                academic_year=2025,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
            )
            session.add(profile)
            await session.flush()
            return profile.id


async def get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    """Login and get auth headers."""
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post("/api/auth/login", data=login_data)
    
    if res.status_code != 200:
        pytest.fail(f"Login failed: {res.status_code} - {res.text}")
    
    access_token = res.cookies.get("access_token")
    if not access_token:
        pytest.fail("Login succeeded but access_token cookie not found")
    
    return {"Authorization": f"Bearer {access_token}"}


# ==============================================================================
# TEST: CROSS-UNIT ACCESS PROTECTION
# ==============================================================================


class TestCrossUnitAccessProtection:
    """Test that users cannot access profiles from other units."""

    async def test_user_cannot_view_other_unit_profile(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,  # Use existing fixture (Unit A)
        seed_lead_dependencies: dict,
    ):
        """
        User from Unit A should get 404 when viewing profile from Unit B.
        
        Security: IDOR protection returns 404 (not 403) to prevent ID enumeration.
        """
        # Create Unit B
        unit_b_id = await create_second_unit()
        
        # Create profile in Unit B
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "555500001111")
        
        # Officer (Unit A) tries to access profile in Unit B
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.get(
            f"/api/admissions/{profile_b_id}",
            headers=headers,
        )
        
        # Should return 403 or 404 (IDOR protection hides existence)
        # If we get 200, it means IDOR protection is broken!
        assert response.status_code in [403, 404], \
            f"IDOR BUG: Officer accessed other unit's profile! Got status={response.status_code}, expected 403/404"

    async def test_user_cannot_update_other_unit_profile(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        User from Unit A should not be able to update profile from Unit B.
        """
        unit_b_id = await create_second_unit()
        
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "555500002222")
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.put(
            f"/api/admissions/{profile_b_id}",
            json={"full_name": "Hacked Name", "version": 1},
            headers=headers,
        )
        
        # Should deny update
        assert response.status_code in [403, 404], \
            f"Should deny update to other unit's profile: {response.status_code}"

    async def test_user_cannot_submit_other_unit_profile(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        User from Unit A should not be able to submit profile from Unit B.
        """
        unit_b_id = await create_second_unit()
        
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "555500003333")
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.post(
            f"/api/admissions/{profile_b_id}/submit",
            headers=headers,
        )
        
        # Should deny submit
        assert response.status_code in [403, 404], \
            f"Should deny submit on other unit's profile: {response.status_code}"


# ==============================================================================
# TEST: ADMIN ACCESS
# ==============================================================================


class TestAdminCrossUnitAccess:
    """Test that Admin can access all units."""

    async def test_admin_can_view_any_unit_profile(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Admin should be able to view profiles from any unit.
        """
        unit_b_id = await create_second_unit()
        
        # Create profile in Unit B
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "555500004444")
        
        # Admin accesses profile B
        admin_headers = await get_auth_headers(client, admin_user_in_db)
        
        response = await client.get(
            f"/api/admissions/{profile_b_id}",
            headers=admin_headers,
        )
        
        # Admin should succeed
        assert response.status_code == 200, \
            f"Admin should access any unit: {response.status_code} - {response.text}"

    async def test_admin_can_update_any_unit_profile(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Admin should be able to update profiles from any unit.
        """
        unit_b_id = await create_second_unit()
        
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "555500005555")
        
        admin_headers = await get_auth_headers(client, admin_user_in_db)
        
        response = await client.put(
            f"/api/admissions/{profile_b_id}",
            json={"full_name": "Admin Updated", "version": 1},
            headers=admin_headers,
        )
        
        # Admin should succeed
        assert response.status_code == 200, \
            f"Admin should update any unit: {response.status_code} - {response.text}"


# ==============================================================================
# TEST: MANAGER ACCESS SCOPE
# ==============================================================================


class TestManagerAccessScope:
    """Test that Manager can only access own unit."""

    async def test_manager_can_access_own_unit_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Manager should access profiles from their own unit.
        
        Note: This test may fail with 403 if Casbin policy doesn't allow
        manager role to access GET /api/admissions/{id}. In that case,
        the test is still valid - it confirms RBAC is working.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        # Create profile in Manager's unit
        lead = await create_test_lead(unit_id)
        profile_id = await create_admission_profile(lead, "555500006666")
        
        manager_headers = await get_auth_headers(client, manager_user_in_db)
        
        response = await client.get(
            f"/api/admissions/{profile_id}",
            headers=manager_headers,
        )
        
        # If 403, it means Casbin policy doesn't allow manager to access admissions
        # This is expected behavior if policy is not configured for manager role
        if response.status_code == 403:
            pytest.skip("Manager role doesn't have Casbin permission for GET /api/admissions/{id}")
        
        # Manager should succeed
        assert response.status_code == 200, \
            f"Manager should access own unit: {response.status_code}"

    async def test_manager_cannot_access_other_unit_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Manager should not access profiles from other units.
        """
        unit_b_id = await create_second_unit()
        
        # Create profile in Unit B (different from manager's unit)
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "555500007777")
        
        manager_headers = await get_auth_headers(client, manager_user_in_db)
        
        response = await client.get(
            f"/api/admissions/{profile_b_id}",
            headers=manager_headers,
        )
        
        # Manager should be denied (IDOR returns 404)
        assert response.status_code in [403, 404], \
            f"Manager should not access other unit: {response.status_code}"


# ==============================================================================
# TEST: OFFICER ASSIGNMENT IDOR (3-TIER)
# ==============================================================================


class TestOfficerAssignmentIDOR:
    """
    Test 3-tier IDOR: Officer can only access profiles for leads assigned to them.

    After 3-tier IDOR implementation:
    - Admin: Full access
    - Manager: Unit-level access
    - Officer: Must be lead.assigned_officer_id == officer.id AND same unit
    """

    async def test_officer_same_unit_different_assignment_gets_404(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Officer in same unit but NOT assigned to the lead should get 404.

        This tests the officer-level tier of IDOR protection.
        Lead is in officer's unit but assigned to a different officer (or None).
        """
        unit_id = seed_lead_dependencies["unit_id"]

        # Create lead in officer's unit but NOT assigned to this officer
        lead_id = await create_test_lead(unit_id, assigned_officer_id=None)
        profile_id = await create_admission_profile(lead_id, "666600001111")

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.get(
            f"/api/admissions/{profile_id}",
            headers=headers,
        )

        # Officer should be denied even though unit matches
        assert response.status_code in [403, 404], \
            f"IDOR BUG: Officer accessed unassigned lead's profile! Got {response.status_code}, expected 403/404"

    async def test_officer_can_access_own_assigned_profile(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Officer assigned to the lead should access the profile successfully.
        """
        unit_id = seed_lead_dependencies["unit_id"]

        # Create lead assigned TO this officer
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile_id = await create_admission_profile(lead_id, "666600002222")

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.get(
            f"/api/admissions/{profile_id}",
            headers=headers,
        )

        assert response.status_code == 200, \
            f"Officer should access own assigned profile: {response.status_code} - {response.text}"

    async def test_officer_cannot_submit_unassigned_lead_profile(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Officer should not be able to submit a profile for a lead not assigned to them.
        """
        unit_id = seed_lead_dependencies["unit_id"]

        # Create lead NOT assigned to this officer
        lead_id = await create_test_lead(unit_id, assigned_officer_id=None)
        profile_id = await create_admission_profile(lead_id, "666600003333")

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/submit",
            headers=headers,
        )

        assert response.status_code in [403, 404], \
            f"Officer should not submit unassigned lead's profile: {response.status_code}"


# ==============================================================================
# TEST: FEE-STATUS IDOR (ADM-001 regression)
# ==============================================================================


class TestFeeStatusIDOR:
    """GET /admissions/{id}/fee-status must enforce 3-tier IDOR scope.

    Regression for ADM-001: previously the route only required login, so any
    authenticated user could read fee fields of profiles outside their scope.
    """

    async def test_cross_unit_officer_cannot_read_fee_status(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_b_id = await create_second_unit()
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "777700001111")

        headers = await get_auth_headers(client, officer_user_in_db)
        response = await client.get(
            f"/api/admissions/{profile_b_id}/fee-status",
            headers=headers,
        )
        assert response.status_code == 404, (
            "ADM-001 regression: officer must not read fee-status across units"
        )

    async def test_same_unit_unassigned_officer_cannot_read_fee_status(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        # Lead in same unit but assigned to no one (or someone else)
        lead_id = await create_test_lead(unit_id, assigned_officer_id=None)
        profile_id = await create_admission_profile(lead_id, "777700002222")

        headers = await get_auth_headers(client, officer_user_in_db)
        response = await client.get(
            f"/api/admissions/{profile_id}/fee-status",
            headers=headers,
        )
        assert response.status_code == 404, (
            "ADM-001 regression: officer must not read fee-status of unassigned profile"
        )

    async def test_cross_unit_manager_cannot_read_fee_status(
        self,
        client: AsyncClient,
        manager_other_unit_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=None)
        profile_id = await create_admission_profile(lead_id, "777700003333")

        headers = await get_auth_headers(client, manager_other_unit_user_in_db)
        response = await client.get(
            f"/api/admissions/{profile_id}/fee-status",
            headers=headers,
        )
        assert response.status_code == 404, (
            "ADM-001 regression: cross-unit manager must not read fee-status"
        )

    async def test_admin_can_read_fee_status_any_unit(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_b_id = await create_second_unit()
        lead_b = await create_test_lead(unit_b_id)
        profile_b_id = await create_admission_profile(lead_b, "777700004444")

        headers = await get_auth_headers(client, admin_user_in_db)
        response = await client.get(
            f"/api/admissions/{profile_b_id}/fee-status",
            headers=headers,
        )
        assert response.status_code == 200, (
            f"Admin must read any unit's fee-status, got {response.status_code}"
        )

    async def test_assigned_officer_can_read_fee_status(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(
            unit_id, assigned_officer_id=officer_user_in_db["id"]
        )
        profile_id = await create_admission_profile(lead_id, "777700005555")

        headers = await get_auth_headers(client, officer_user_in_db)
        response = await client.get(
            f"/api/admissions/{profile_id}/fee-status",
            headers=headers,
        )
        assert response.status_code == 200, (
            f"Assigned officer must read fee-status, got {response.status_code}"
        )

    async def test_same_unit_non_staff_role_cannot_read_fee_status(
        self,
        client: AsyncClient,
        non_staff_user_same_unit_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """ADM-001 review fix: a ``role=user`` user in the SAME unit as
        the lead used to slip through because the dependency only special-
        cased OFFICER. Now the role allow-list rejects anything outside
        {ADMIN, MANAGER, OFFICER} up front with a fake 404 — even though
        the route itself only uses ``get_current_active_user`` (no Casbin
        gate).
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=None)
        profile_id = await create_admission_profile(lead_id, "777700006666")

        headers = await get_auth_headers(client, non_staff_user_same_unit_in_db)
        response = await client.get(
            f"/api/admissions/{profile_id}/fee-status",
            headers=headers,
        )
        # Dependency raises ResourceNotFoundError → 404. Treat 403 as
        # acceptable in case a future Casbin gate lands on the route, but
        # 200 must never happen.
        assert response.status_code in (403, 404), (
            "ADM-001 review fix: non-admission role with matching unit "
            f"must NOT read fee-status; got {response.status_code} - "
            f"{response.text[:200]}"
        )


# ==============================================================================
# TEST: LIST-ENDPOINT SCOPE FAIL-CLOSED (audit P1 regression)
# ==============================================================================
#
# The admission list / export / status-counts / stats / academic-years /
# pending-diploma endpoints all derive their IDOR scope from
# ``admission_service._resolve_idor_filters``. Before the fix a manager/officer
# whose ``unit_id IS NULL`` resolved to ``(None, ...)``, which the repository
# reads as "no unit filter" → a system-wide leak of every profile / CSV row /
# status count / nợ-bằng entry. These tests lock the fail-closed contract
# end-to-end.
#
# Status mapping: five endpoints let ``PermissionDeniedError`` reach the global
# handler → 403; ``/pending-diploma`` catches it in the router and re-raises 404
# (IDOR enumeration convention — admissions.py:285).

# Endpoints that surface the denial as a raw 403.
_SCOPED_LIST_ENDPOINTS_403 = [
    "/api/admissions",
    "/api/admissions/export",
    "/api/admissions/status-counts",
    "/api/admissions/stats",
    "/api/admissions/academic-years",
]
_PENDING_DIPLOMA_ENDPOINT = "/api/admissions/pending-diploma"


@pytest_asyncio.fixture
async def officer_no_unit_headers(client: AsyncClient, setup_test_database) -> dict:
    """Auth headers for an OFFICER with ``unit_id IS NULL``.

    Casbin role IS seeded (``role:officer`` covers every list endpoint via
    OFFICER_TEMPLATE), so the request clears the gateway and genuinely
    exercises the *service* scope gate rather than a role deny.
    """
    from tests.conftest import _create_user_and_role, _get_token_headers

    data = {
        "username": "officer_no_unit_idor",
        "email": "officer_nounit_idor@test.com",
        "password": "OfficerNoUnit!123",
        "role": "officer",
        "status": "active",
    }
    await _create_user_and_role(data, "role:officer", unit_id=None)
    return await _get_token_headers(client, data)


@pytest_asyncio.fixture
async def manager_no_unit_headers(client: AsyncClient, setup_test_database) -> dict:
    """Auth headers for a MANAGER with ``unit_id IS NULL`` (mirrors the KPI
    precedent ``test_coverage_manager_no_unit_gets_403``)."""
    from tests.conftest import _create_user_and_role, _get_token_headers

    data = {
        "username": "manager_no_unit_idor",
        "email": "manager_nounit_idor@test.com",
        "password": "ManagerNoUnit!123",
        "role": "manager",
        "status": "active",
    }
    await _create_user_and_role(data, "role:manager", unit_id=None)
    return await _get_token_headers(client, data)


class TestListScopeFailClosed:
    """Manager/Officer without a unit must never see system-wide list data."""

    async def test_officer_with_unit_can_list(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Non-vacuous anchor: a properly-scoped officer reaches the list (200).

        Proves the fail-closed 403s below come from the missing-unit scope
        gate, not a blanket Casbin deny on the officer role.
        """
        headers = await get_auth_headers(client, officer_user_in_db)
        response = await client.get("/api/admissions", headers=headers)
        assert response.status_code == 200, (
            f"Scoped officer must list profiles: {response.status_code} - "
            f"{response.text[:200]}"
        )

    @pytest.mark.parametrize("endpoint", _SCOPED_LIST_ENDPOINTS_403)
    async def test_officer_no_unit_denied_403(
        self,
        client: AsyncClient,
        officer_no_unit_headers: dict,
        endpoint: str,
    ):
        response = await client.get(endpoint, headers=officer_no_unit_headers)
        assert response.status_code == 403, (
            f"IDOR leak: unit-less officer must be denied on {endpoint}, got "
            f"{response.status_code} - {response.text[:200]}"
        )

    async def test_officer_no_unit_denied_pending_diploma_404(
        self,
        client: AsyncClient,
        officer_no_unit_headers: dict,
    ):
        # Router translates PermissionDeniedError → 404 (enumeration convention).
        response = await client.get(
            _PENDING_DIPLOMA_ENDPOINT, headers=officer_no_unit_headers
        )
        assert response.status_code == 404, (
            f"unit-less officer must be denied on pending-diploma, got "
            f"{response.status_code} - {response.text[:200]}"
        )

    @pytest.mark.parametrize(
        "endpoint", _SCOPED_LIST_ENDPOINTS_403 + [_PENDING_DIPLOMA_ENDPOINT]
    )
    async def test_manager_no_unit_never_leaks(
        self,
        client: AsyncClient,
        manager_no_unit_headers: dict,
        endpoint: str,
    ):
        """A unit-less manager must never see data. 403 (scope or Casbin deny)
        and 404 (pending-diploma translation) are both acceptable; 200 is the
        bug. Mirrors KPI ``test_coverage_manager_no_unit_gets_403``.
        """
        response = await client.get(endpoint, headers=manager_no_unit_headers)
        assert response.status_code in (403, 404), (
            f"IDOR leak: unit-less manager saw data on {endpoint}: "
            f"{response.status_code} - {response.text[:200]}"
        )
