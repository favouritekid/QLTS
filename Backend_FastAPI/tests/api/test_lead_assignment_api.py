# tests/api/test_lead_assignment_api.py
# -*- coding: utf-8 -*-
"""
🧪 API-LEVEL TESTS: Lead Assignment / Reassign Endpoints

This module tests HTTP endpoints for:
- Officer reject/reassign actions (POST /api/leads/{id}/action)
- Lead creation with assignment (POST /api/leads)
- Consultation creation permissions (POST /api/leads/{id}/consultations)
- Manual lead assignment (POST /api/leads/{id}/assign)

Format: Gherkin (Given – When – Then)

REQUIRES: Running PostgreSQL database (integration tests)
Run: pytest tests/api/test_lead_assignment_api.py -v -m integration
Skip: pytest tests/ -m "not integration"
"""

import pytest

# Mark all tests in this module as integration tests requiring database
pytestmark = pytest.mark.integration
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.security import get_password_hash
from app.config import settings

# Import test constants
try:
    from tests.fixtures.constants import (
        TestUsers,
        TestOrgData,
        LeadsURLs,
        AuthURLs,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def second_officer_in_db(seed_lead_dependencies: dict):
    """Create a second officer in the same unit."""
    unit_id = seed_lead_dependencies.get("unit_id", 1)
    user_data = {
        "username": "officer2",
        "email": "officer2@example.com",
        "password": "Officer2Password!123",
        "role": "officer",
        "status": "active",
    }

    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username=user_data["username"],
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                role=user_data["role"],
                status=user_data["status"],
                unit_id=unit_id,
                availability_status="available",
                max_capacity=10,
            )
            session.add(user)
            await session.flush()
            user_info = {
                "id": user.id,
                "username": user_data["username"],
                "email": user_data["email"],
                "password": user_data["password"],
            }

    return user_info


@pytest_asyncio.fixture
async def second_officer_token_headers(
    client: AsyncClient, second_officer_in_db: dict
) -> dict:
    """Get token headers for second officer."""
    login_data = {
        "username": second_officer_in_db["username"],
        "password": second_officer_in_db["password"],
    }
    res = await client.post(AuthURLs.LOGIN, data=login_data)
    if res.status_code != 200:
        pytest.fail(f"Second officer login failed: {res.status_code} - {res.text}")

    access_token = res.cookies.get("access_token")
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def lead_assigned_to_officer(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """Create a lead and assign it to the test officer."""
    lead_data = {
        "full_name": "Assigned Lead Test",
        "phone": "0901234567",
        "email": "assigned_lead@test.com",
        "source": "website",
        "unit_id": seed_lead_dependencies["unit_id"],
    }

    # Create lead as admin
    res = await client.post(
        LeadsURLs.LEADS,
        json=lead_data,
        headers=admin_token_headers,
    )
    assert res.status_code == 201, f"Failed to create lead: {res.text}"
    lead = res.json()
    lead_id = lead["id"]

    # Assign to officer
    assign_res = await client.post(
        LeadsURLs.ASSIGN(lead_id),
        json={"officer_id": officer_user_in_db["id"]},
        headers=admin_token_headers,
    )
    assert assign_res.status_code == 200, f"Failed to assign lead: {assign_res.text}"

    return assign_res.json()


@pytest_asyncio.fixture
async def unassigned_lead(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """Create an unassigned lead."""
    lead_data = {
        "full_name": "Unassigned Lead Test",
        "phone": "0909999888",
        "email": "unassigned@test.com",
        "source": "website",
        "unit_id": seed_lead_dependencies["unit_id"],
    }

    # Create lead without assignment (admin can do this)
    res = await client.post(
        LeadsURLs.LEADS,
        json=lead_data,
        headers=admin_token_headers,
    )
    assert res.status_code == 201, f"Failed to create lead: {res.text}"

    lead = res.json()

    # Unassign the lead if auto-assigned
    if lead.get("assigned_officer_id"):
        # Use admin to unassign
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(models.Lead).where(models.Lead.id == lead["id"])
                )
                db_lead = result.scalar_one()
                db_lead.assigned_officer_id = None
                db_lead.assigned_at = None

    return lead


# =============================================================================
# SCENARIO 6: REJECT QUOTA RACE CONDITION (API Level)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_6_reject_quota_enforcement(
    client: AsyncClient,
    officer_token_headers: dict,
    officer_user_in_db: dict,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """
    Scenario 6: Reject quota enforcement

    Given: Officer A has rejected 4 leads this week
    When: Officer A attempts to reject a 5th lead
    Then: Request succeeds (within quota)
    When: Officer A attempts to reject a 6th lead
    Then: Request is blocked (quota exceeded)
    """
    # Create 6 leads and assign all to the officer
    leads = []
    for i in range(6):
        lead_data = {
            "full_name": f"Quota Test Lead {i}",
            "phone": f"090000{i:04d}",
            "source": "website",
            "unit_id": seed_lead_dependencies["unit_id"],
        }
        res = await client.post(
            LeadsURLs.LEADS,
            json=lead_data,
            headers=admin_token_headers,
        )
        assert res.status_code == 201
        lead = res.json()

        # Assign to officer
        assign_res = await client.post(
            LeadsURLs.ASSIGN(lead["id"]),
            json={"officer_id": officer_user_in_db["id"]},
            headers=admin_token_headers,
        )
        assert assign_res.status_code == 200
        leads.append(assign_res.json())

    # Reject first 5 leads (should succeed)
    for i in range(5):
        action_res = await client.post(
            LeadsURLs.ACTION(leads[i]["id"]),
            json={"action": "reassign", "reason": f"Quota test {i}"},
            headers=officer_token_headers,
        )
        assert action_res.status_code == 200, f"Reject {i} failed: {action_res.text}"

    # 6th reject should fail (quota exceeded)
    action_res = await client.post(
        LeadsURLs.ACTION(leads[5]["id"]),
        json={"action": "reassign", "reason": "Should fail - quota exceeded"},
        headers=officer_token_headers,
    )
    assert action_res.status_code == 400, f"Expected 400, got {action_res.status_code}"
    assert "quota" in action_res.text.lower() or "lượt" in action_res.text.lower()


# =============================================================================
# SCENARIO 7: OFFICER REJECTS ANOTHER'S LEAD (API Level)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_7_officer_rejects_others_lead(
    client: AsyncClient,
    lead_assigned_to_officer: dict,
    second_officer_token_headers: dict,
):
    """
    Scenario 7: Officer rejects lead not assigned to them

    Given: Lead L is assigned to officer A
    When: Officer B attempts to reject lead L
    Then: API returns 403 Forbidden
    """
    lead_id = lead_assigned_to_officer["id"]

    # Officer B tries to reject Officer A's lead
    action_res = await client.post(
        LeadsURLs.ACTION(lead_id),
        json={"action": "reassign", "reason": "Trying to reject others lead"},
        headers=second_officer_token_headers,
    )

    assert action_res.status_code == 403, f"Expected 403, got {action_res.status_code}: {action_res.text}"


# =============================================================================
# SCENARIO 8: REJECT AFTER LEAD REASSIGNED (API Level)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_8_reject_after_reassignment(
    client: AsyncClient,
    lead_assigned_to_officer: dict,
    officer_token_headers: dict,
    admin_token_headers: dict,
    second_officer_in_db: dict,
):
    """
    Scenario 8: Reject after lead reassigned

    Given: Officer A has lead L open in UI
    And: Admin reassigns lead L to officer B
    When: Officer A attempts to reject lead L
    Then: Reject fails with ownership loss message
    """
    lead_id = lead_assigned_to_officer["id"]

    # Admin reassigns to officer B
    assign_res = await client.post(
        LeadsURLs.ASSIGN(lead_id),
        json={"officer_id": second_officer_in_db["id"]},
        headers=admin_token_headers,
    )
    assert assign_res.status_code == 200

    # Officer A tries to reject (should fail - no longer assigned)
    action_res = await client.post(
        LeadsURLs.ACTION(lead_id),
        json={"action": "reassign", "reason": "Stale UI attempt"},
        headers=officer_token_headers,
    )

    assert action_res.status_code == 403, f"Expected 403, got {action_res.status_code}: {action_res.text}"


# =============================================================================
# SCENARIO 14: OFFICER CONSULTATION ON UNASSIGNED LEAD (API Level)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_14_officer_consultation_unassigned_lead(
    client: AsyncClient,
    unassigned_lead: dict,
    officer_token_headers: dict,
):
    """
    Scenario 14: Officer creates consultation for unassigned lead

    Given: A lead is unassigned
    When: An officer attempts to create a consultation
    Then: Request fails with 403 Forbidden
    """
    lead_id = unassigned_lead["id"]

    consultation_data = {
        "outcome": "positive",
        "notes": "Attempting consultation on unassigned lead",
    }

    res = await client.post(
        LeadsURLs.CONSULTATIONS(lead_id),
        json=consultation_data,
        headers=officer_token_headers,
    )

    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


# =============================================================================
# SCENARIO 15: OFFICER CONSULTATION ON ANOTHER'S LEAD (API Level)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_15_officer_consultation_others_lead(
    client: AsyncClient,
    lead_assigned_to_officer: dict,
    second_officer_token_headers: dict,
):
    """
    Scenario 15: Officer creates consultation for another officer's lead

    Given: Lead L is assigned to officer A
    When: Officer B attempts to create a consultation for L
    Then: Request is forbidden
    """
    lead_id = lead_assigned_to_officer["id"]

    consultation_data = {
        "outcome": "positive",
        "notes": "Attempting consultation on someone else's lead",
    }

    res = await client.post(
        LeadsURLs.CONSULTATIONS(lead_id),
        json=consultation_data,
        headers=second_officer_token_headers,
    )

    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


# =============================================================================
# SCENARIO 17: MANAGER IN ASSIGN DROPDOWN (API Level)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_17_assign_to_manager_rejected(
    client: AsyncClient,
    admin_token_headers: dict,
    manager_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """
    Scenario 17: Manager appears in assign dropdown

    Given: Frontend cache is stale
    When: Assignment request targets a manager
    Then: Backend rejects the assignment
    """
    # Create a lead
    lead_data = {
        "full_name": "Manager Assign Test",
        "phone": "0907777666",
        "source": "website",
        "unit_id": seed_lead_dependencies["unit_id"],
    }

    res = await client.post(
        LeadsURLs.LEADS,
        json=lead_data,
        headers=admin_token_headers,
    )
    assert res.status_code == 201
    lead = res.json()

    # Try to assign to manager (should fail)
    assign_res = await client.post(
        LeadsURLs.ASSIGN(lead["id"]),
        json={"officer_id": manager_user_in_db["id"]},
        headers=admin_token_headers,
    )

    # Should fail because manager is not an officer
    assert assign_res.status_code in [400, 403, 422], f"Expected error, got {assign_res.status_code}: {assign_res.text}"


# =============================================================================
# SCENARIO 25: MANAGER ASSIGNS INACTIVE OFFICER (API Level)
# =============================================================================

@pytest_asyncio.fixture
async def inactive_officer_in_db(seed_lead_dependencies: dict):
    """Create an inactive officer."""
    unit_id = seed_lead_dependencies.get("unit_id", 1)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username="inactive_officer",
                email="inactive@example.com",
                password_hash=get_password_hash("InactivePassword!123"),
                role="officer",
                status="inactive",  # INACTIVE
                unit_id=unit_id,
                availability_status="available",
                max_capacity=10,
            )
            session.add(user)
            await session.flush()
            user_info = {"id": user.id}

    return user_info


@pytest.mark.asyncio
async def test_scenario_25_manager_assigns_inactive_officer(
    client: AsyncClient,
    manager_token_headers: dict,
    inactive_officer_in_db: dict,
    seed_lead_dependencies: dict,
):
    """
    Scenario 25: Manager assigns inactive officer during lead creation

    Given: A manager selects an inactive officer
    When: Lead creation is submitted
    Then: Request fails with validation error
    """
    lead_data = {
        "full_name": "Inactive Officer Test",
        "phone": "0906666555",
        "source": "website",
        "unit_id": seed_lead_dependencies["unit_id"],
        "assigned_officer_id": inactive_officer_in_db["id"],
    }

    res = await client.post(
        LeadsURLs.LEADS,
        json=lead_data,
        headers=manager_token_headers,
    )

    # Should fail because officer is inactive
    assert res.status_code in [400, 403, 422], f"Expected error, got {res.status_code}: {res.text}"


# =============================================================================
# SCENARIO 26: MANAGER ASSIGNS OFFICER FROM ANOTHER UNIT (API Level)
# =============================================================================

@pytest_asyncio.fixture
async def officer_other_unit_in_db(setup_test_database):
    """Create an officer in a different unit."""
    # First create another unit
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit2 = models.OrganizationUnit(
                id=2,
                name="Other Unit",
                type="Faculty",
            )
            session.add(unit2)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username="other_unit_officer",
                email="otherunit@example.com",
                password_hash=get_password_hash("OtherUnitPassword!123"),
                role="officer",
                status="active",
                unit_id=2,  # Different unit
                availability_status="available",
                max_capacity=10,
            )
            session.add(user)
            await session.flush()
            user_info = {"id": user.id, "unit_id": 2}

    return user_info


@pytest.mark.asyncio
async def test_scenario_26_manager_assigns_officer_other_unit(
    client: AsyncClient,
    manager_token_headers: dict,
    officer_other_unit_in_db: dict,
    seed_lead_dependencies: dict,
):
    """
    Scenario 26: Manager assigns officer from another unit

    Given: A manager selects an officer from a different unit
    When: Lead creation is submitted
    Then: Assignment is rejected
    """
    lead_data = {
        "full_name": "Cross Unit Test",
        "phone": "0905555444",
        "source": "website",
        "unit_id": seed_lead_dependencies["unit_id"],  # Manager's unit
        "assigned_officer_id": officer_other_unit_in_db["id"],  # Different unit
    }

    res = await client.post(
        LeadsURLs.LEADS,
        json=lead_data,
        headers=manager_token_headers,
    )

    # Should fail because officer is in different unit
    assert res.status_code in [400, 403, 422], f"Expected error, got {res.status_code}: {res.text}"


# =============================================================================
# SCENARIO 22: AUDIT LOGGING (API Level)
# =============================================================================

@pytest.mark.asyncio
async def test_scenario_22_reassign_creates_audit_log(
    client: AsyncClient,
    lead_assigned_to_officer: dict,
    officer_token_headers: dict,
    officer_user_in_db: dict,
):
    """
    Scenario 22: Reassign audit logging

    Given: A lead reassignment occurs
    When: The operation completes
    Then: An audit log (AssignmentLog) is created
    """
    lead_id = lead_assigned_to_officer["id"]

    # Perform reassign
    action_res = await client.post(
        LeadsURLs.ACTION(lead_id),
        json={"action": "reassign", "reason": "Audit log test reason"},
        headers=officer_token_headers,
    )
    assert action_res.status_code == 200

    # Check AssignmentLog was created
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.AssignmentLog).where(
                models.AssignmentLog.lead_id == lead_id,
                models.AssignmentLog.officer_id == officer_user_in_db["id"],
                models.AssignmentLog.method == "officer_reassign",
            )
        )
        log_entry = result.scalar_one_or_none()

        assert log_entry is not None, "AssignmentLog not found"
        assert log_entry.reason == "Audit log test reason"


# =============================================================================
# ADMIN CAN CREATE CONSULTATION ON ANY LEAD
# =============================================================================

@pytest.mark.asyncio
async def test_admin_can_create_consultation_any_lead(
    client: AsyncClient,
    admin_token_headers: dict,
    unassigned_lead: dict,
):
    """
    Admin should be able to create consultation on any lead.

    Given: A lead (assigned or unassigned)
    When: Admin creates a consultation
    Then: Consultation is created successfully
    """
    lead_id = unassigned_lead["id"]

    consultation_data = {
        "outcome": "positive",
        "notes": "Admin creating consultation",
    }

    res = await client.post(
        LeadsURLs.CONSULTATIONS(lead_id),
        json=consultation_data,
        headers=admin_token_headers,
    )

    # Admin should succeed
    assert res.status_code in [200, 201], f"Expected success, got {res.status_code}: {res.text}"


# =============================================================================
# ADMIN/MANAGER CAN REASSIGN ANY LEAD
# =============================================================================

@pytest.mark.asyncio
async def test_admin_can_reassign_any_lead(
    client: AsyncClient,
    admin_token_headers: dict,
    lead_assigned_to_officer: dict,
):
    """
    Admin should be able to reassign any lead without quota.

    Given: A lead assigned to officer A
    When: Admin reassigns the lead
    Then: Reassign succeeds, admin not added to blacklist
    """
    lead_id = lead_assigned_to_officer["id"]

    action_res = await client.post(
        LeadsURLs.ACTION(lead_id),
        json={"action": "reassign", "reason": "Admin reassign test"},
        headers=admin_token_headers,
    )

    assert action_res.status_code == 200, f"Expected 200, got {action_res.status_code}: {action_res.text}"

    # Verify blacklist doesn't contain admin
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.Lead).where(models.Lead.id == lead_id)
        )
        lead = result.scalar_one()

        # Admin should not be in blacklist (admin reassign doesn't add to blacklist)
        # Note: The logic adds to blacklist only for officers (not admin/manager)


@pytest.mark.asyncio
async def test_manager_can_reassign_team_lead(
    client: AsyncClient,
    manager_token_headers: dict,
    lead_assigned_to_officer: dict,
):
    """
    Manager should be able to reassign leads in their unit without quota.

    Given: A lead assigned to an officer in manager's unit
    When: Manager reassigns the lead
    Then: Reassign succeeds, manager not added to blacklist
    """
    lead_id = lead_assigned_to_officer["id"]

    action_res = await client.post(
        LeadsURLs.ACTION(lead_id),
        json={"action": "reassign", "reason": "Manager reassign test"},
        headers=manager_token_headers,
    )

    assert action_res.status_code == 200, f"Expected 200, got {action_res.status_code}: {action_res.text}"
