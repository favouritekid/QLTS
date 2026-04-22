# tests/integration/services/conftest.py
"""
Fixtures for service layer integration tests.

These fixtures provide real database objects for testing service functions directly
without going through the API layer.
"""
import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.database import AsyncSessionLocal, engine
from app.security import get_password_hash
from tests._lead_status_test_ids import (
    INITIAL_LEAD_STATUS_ID,
    LOST_LEAD_STATUS_ID,
)

# Import shared constants
try:
    from tests.fixtures.constants import (
        TestUsers,
        TestOrgData,
        TestPipelineData,
        TestLeadData,
    )
except ImportError:
    logging.warning("Could not import constants from tests.fixtures.constants")

log = logging.getLogger(__name__)


# =============================================================================
# DATABASE SESSION FIXTURE
# =============================================================================

@pytest_asyncio.fixture
async def db(setup_test_database) -> AsyncSession:
    """
    Provide a database session for service integration tests.

    This fixture:
    1. Depends on setup_test_database to ensure schema is ready
    2. Creates a new AsyncSession for the test
    3. Yields the session for test use
    4. Closes the session after test completes
    """
    async def _has_core_tables(session: AsyncSession) -> bool:
        await session.execute(text("SET search_path TO public"))
        result = await session.execute(
            text(
                "SELECT COUNT(*) FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename IN ('user', 'organization_unit')"
            )
        )
        return result.scalar_one() == 2

    async with AsyncSessionLocal() as session:
        if await _has_core_tables(session):
            yield session
            return

    # Schema was recreated on a separate engine; if the first pooled connection
    # still doesn't see core tables, dispose and retry with a fresh connection.
    await engine.dispose()
    async with AsyncSessionLocal() as retry_session:
        assert await _has_core_tables(retry_session), "Core tables not visible after schema setup retry"
        yield retry_session


# =============================================================================
# USER FIXTURES FOR SERVICE TESTS
# =============================================================================

@pytest_asyncio.fixture
async def admin_user(db: AsyncSession) -> models.User:
    """Create an admin user directly in database."""
    user = models.User(
        username="service_test_admin",
        email="service_admin@test.com",
        password_hash=get_password_hash("AdminPass123!"),
        role="admin",
        status="active",
        full_name="Service Test Admin"
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def officer_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create an officer user assigned to a unit."""
    user = models.User(
        username="service_test_officer",
        email="service_officer@test.com",
        password_hash=get_password_hash("OfficerPass123!"),
        role="officer",
        status="active",
        full_name="Service Test Officer",
        unit_id=seeded_dependencies["unit_id"]
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def manager_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create a manager user assigned to a unit."""
    user = models.User(
        username="service_test_manager",
        email="service_manager@test.com",
        password_hash=get_password_hash("ManagerPass123!"),
        role="manager",
        status="active",
        full_name="Service Test Manager",
        unit_id=seeded_dependencies["unit_id"]
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def regular_user(db: AsyncSession) -> models.User:
    """Create a regular user without special role."""
    user = models.User(
        username="service_test_user",
        email="service_user@test.com",
        password_hash=get_password_hash("UserPass123!"),
        role="user",
        status="active",
        full_name="Service Test User"
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# =============================================================================
# LEAD DEPENDENCIES FIXTURE
# =============================================================================

@pytest_asyncio.fixture
async def seeded_dependencies(db: AsyncSession) -> dict:
    """
    Seed required dependencies for Lead tests: Unit, Pipeline Stages, Statuses.
    
    This is a lighter version that uses the same db session as the test.
    """
    # Organization Unit - use correct field names
    unit = models.OrganizationUnit(
        id=1001,
        name="Service Test Unit",
        type="department"  # Field is 'type', not 'code' or 'unit_type'
    )
    db.add(unit)
    
    # Pipeline Stages — use real IDs that phase_manager recognizes
    # PHASE_STAGES[CONSULTATION] expects stg01/stg02
    stage = models.PipelineStage(
        id="stg01",
        name="Tư vấn (Test)",
        order=10
    )
    db.add(stage)

    # Initial Status (system default) — must be in PHASE_STATUSES[CONSULTATION]
    initial_status = models.ConsultationStatus(
        id=INITIAL_LEAD_STATUS_ID,
        name="New Lead (Test)",
        color_code="#0000FF",
        stage_id="stg01"
    )
    db.add(initial_status)

    # Additional status for transitions — use sts02 (in CONSULTATION phase whitelist)
    status_contacted = models.ConsultationStatus(
        id="sts02",
        name="Contacted (Test)",
        color_code="#00FF00",
        stage_id="stg01",
        updates_pipeline=True
    )
    db.add(status_contacted)

    # Lost status — use stg02 (also in CONSULTATION phase)
    lost_stage = models.PipelineStage(
        id="stg02",
        name="Lost Stage (Test)",
        order=999
    )
    db.add(lost_stage)

    lost_status = models.ConsultationStatus(
        id=LOST_LEAD_STATUS_ID,
        name="Lost (Test)",
        color_code="#FF0000",
        stage_id="stg02"
    )
    db.add(lost_status)
    
    await db.flush()
    
    return {
        "unit_id": unit.id,
        "stage_id": stage.id,
        "initial_status_id": initial_status.id,
        "contacted_status_id": status_contacted.id,
        "lost_status_id": lost_status.id,
    }


# =============================================================================
# LEAD FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def seeded_lead(
    db: AsyncSession, 
    seeded_dependencies: dict, 
    officer_user: models.User
) -> models.Lead:
    """Create a lead assigned to the officer user."""
    lead = models.Lead(
        full_name="Service Test Lead",
        phone="0909111222",
        email="service_lead@test.com",
        source="Website",
        unit_id=seeded_dependencies["unit_id"],
        status=seeded_dependencies["initial_status_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
        assigned_officer_id=officer_user.id,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    
    # Add assignment log
    assignment_log = models.AssignmentLog(
        lead_id=lead.id,
        officer_id=officer_user.id,
        method="fixture_setup",
        reason="Assigned during test setup",
        timestamp=datetime.now(timezone.utc)
    )
    db.add(assignment_log)
    await db.flush()
    
    return lead


@pytest_asyncio.fixture
async def unassigned_lead(
    db: AsyncSession, 
    seeded_dependencies: dict
) -> models.Lead:
    """Create an unassigned lead."""
    lead = models.Lead(
        full_name="Unassigned Test Lead",
        phone="0909333444",
        email="unassigned_lead@test.com",
        source="Facebook",
        unit_id=seeded_dependencies["unit_id"],
        status=seeded_dependencies["initial_status_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
        assigned_officer_id=None,
        assigned_at=None,
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


# =============================================================================
# HELPER FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def multiple_leads(
    db: AsyncSession,
    seeded_dependencies: dict,
    officer_user: models.User
) -> list:
    """Create multiple leads for bulk operation tests."""
    leads = []
    for i in range(5):
        lead = models.Lead(
            full_name=f"Bulk Test Lead {i+1}",
            phone=f"090900000{i}",
            email=f"bulk_lead_{i}@test.com",
            source="Import",
            unit_id=seeded_dependencies["unit_id"],
            status=seeded_dependencies["initial_status_id"],
            consultation_status_id=seeded_dependencies["initial_status_id"],
            pipeline_stage_id=seeded_dependencies["stage_id"],
        )
        db.add(lead)
        leads.append(lead)
    
    await db.flush()
    for lead in leads:
        await db.refresh(lead)

    return leads


# =============================================================================
# COLLABORATOR FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def collaborator_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """User with collaborator role, linked to a Collaborator record."""
    user = models.User(
        username="ctv_user_1",
        email="ctv1@test.com",
        password_hash=get_password_hash("CTVPass123!"),
        role=UserRole.COLLABORATOR,
        status="active",
        full_name="CTV User 1",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def collaborator_user_2(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Second collaborator user for concurrent/cross-CTV tests."""
    user = models.User(
        username="ctv_user_2",
        email="ctv2@test.com",
        password_hash=get_password_hash("CTVPass456!"),
        role=UserRole.COLLABORATOR,
        status="active",
        full_name="CTV User 2",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def officer_user_2(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Second officer for EC-1 reassignment tests."""
    user = models.User(
        username="officer_2",
        email="officer2@test.com",
        password_hash=get_password_hash("Officer2Pass123!"),
        role=UserRole.OFFICER,
        status="active",
        full_name="Officer User 2",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def active_collaborator(
    db: AsyncSession,
    seeded_dependencies: dict,
    collaborator_user: models.User,
    officer_user: models.User,
) -> models.Collaborator:
    """Active collaborator managed by officer."""
    collab = models.Collaborator(
        code="CTV-2026-0001",
        full_name="Active CTV",
        phone="0911000001",
        email="active_ctv@test.com",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
        user_id=collaborator_user.id,
        managed_by_officer_id=officer_user.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()
    await db.refresh(collab)
    return collab


@pytest_asyncio.fixture
async def independent_collaborator(
    db: AsyncSession,
    seeded_dependencies: dict,
    collaborator_user_2: models.User,
) -> models.Collaborator:
    """Independent collaborator (no officer)."""
    collab = models.Collaborator(
        code="CTV-2026-0002",
        full_name="Independent CTV",
        phone="0911000002",
        email="independent_ctv@test.com",
        status="active",
        unit_id=seeded_dependencies["unit_id"],
        user_id=collaborator_user_2.id,
        managed_by_officer_id=None,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()
    await db.refresh(collab)
    return collab


@pytest_asyncio.fixture
async def pending_collaborator(
    db: AsyncSession,
    seeded_dependencies: dict,
) -> models.Collaborator:
    """Pending collaborator (not yet approved)."""
    collab = models.Collaborator(
        code="CTV-2026-0003",
        full_name="Pending CTV",
        phone="0911000003",
        email="pending_ctv@test.com",
        status="pending",
        unit_id=seeded_dependencies["unit_id"],
    )
    db.add(collab)
    await db.flush()
    await db.refresh(collab)
    return collab


@pytest_asyncio.fixture
async def second_unit(db: AsyncSession) -> models.OrganizationUnit:
    """Second organization unit for cross-unit IDOR tests."""
    unit = models.OrganizationUnit(
        id=2001,
        name="Second Test Unit",
        type="department",
    )
    db.add(unit)
    await db.flush()
    await db.refresh(unit)
    return unit


@pytest_asyncio.fixture
async def collaborator_in_second_unit(
    db: AsyncSession,
    second_unit: models.OrganizationUnit,
) -> models.Collaborator:
    """Collaborator in a different unit for IDOR tests."""
    collab = models.Collaborator(
        code="CTV-2026-0010",
        full_name="Other Unit CTV",
        phone="0911000010",
        email="other_unit_ctv@test.com",
        status="active",
        unit_id=second_unit.id,
        approved_at=datetime.now(timezone.utc),
    )
    db.add(collab)
    await db.flush()
    await db.refresh(collab)
    return collab


@pytest_asyncio.fixture
async def referred_leads(
    db: AsyncSession,
    seeded_dependencies: dict,
    active_collaborator: models.Collaborator,
    officer_user: models.User,
) -> list[models.Lead]:
    """
    Leads referred by active_collaborator. Mix of statuses:
    - 2x status="new", validity_status="raw"
    - 1x status="contacted", validity_status="raw"
    - 1x status="new", validity_status="valid"
    """
    leads_data = [
        {"full_name": "Referred Lead 1", "phone": "0922000001", "status": "new", "validity_status": "raw"},
        {"full_name": "Referred Lead 2", "phone": "0922000002", "status": "new", "validity_status": "raw"},
        {"full_name": "Referred Lead 3", "phone": "0922000003", "status": "contacted", "validity_status": "raw"},
        {"full_name": "Referred Lead 4", "phone": "0922000004", "status": "new", "validity_status": "valid"},
    ]
    leads = []
    for ld in leads_data:
        lead = models.Lead(
            full_name=ld["full_name"],
            phone=ld["phone"],
            source="referral",
            status=ld["status"],
            validity_status=ld["validity_status"],
            unit_id=seeded_dependencies["unit_id"],
            referrer_id=active_collaborator.id,
            assigned_officer_id=officer_user.id,
            assignment_status="assigned",
            created_via="claim",
        )
        db.add(lead)
        leads.append(lead)
    await db.flush()
    for lead in leads:
        await db.refresh(lead)
    return leads


# =============================================================================
# COMMISSION FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def commission_policy(
    db: AsyncSession,
    seeded_dependencies: dict,
    admin_user: models.User,
) -> "models.CommissionPolicy":
    """Active fixed commission policy linked to the contacted status (sts02)."""
    from app.models.commission import CommissionPolicy
    from datetime import date
    from decimal import Decimal

    policy = CommissionPolicy(
        name="Test Fixed Policy",
        description="500k per contacted lead",
        trigger_status_id=seeded_dependencies["contacted_status_id"],
        calculation_type="fixed",
        fixed_amount=Decimal("500000"),
        effective_from=date(2025, 1, 1),
        is_active=True,
        created_by_id=admin_user.id,
    )
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    return policy


@pytest_asyncio.fixture
async def commission_record(
    db: AsyncSession,
    active_collaborator: "models.Collaborator",
    seeded_lead: models.Lead,
    commission_policy: "models.CommissionPolicy",
) -> "models.CommissionRecord":
    """Pending commission record for testing approve/reject/pay flows."""
    from app.models.commission import CommissionRecord
    from decimal import Decimal

    record = CommissionRecord(
        collaborator_id=active_collaborator.id,
        lead_id=seeded_lead.id,
        policy_id=commission_policy.id,
        amount=commission_policy.fixed_amount,
        calculation_detail={
            "type": "fixed",
            "fixed_amount": str(commission_policy.fixed_amount),
            "policy_name": commission_policy.name,
            "policy_id": commission_policy.id,
        },
        status="pending",
        trigger_status_id=commission_policy.trigger_status_id,
        triggered_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


@pytest_asyncio.fixture
async def deleted_lead_with_phone(
    db: AsyncSession,
    seeded_dependencies: dict,
) -> models.Lead:
    """Soft-deleted lead for testing soft-delete filtering."""
    lead = models.Lead(
        full_name="Deleted Lead",
        phone="0933000001",
        source="website",
        status="new",
        unit_id=seeded_dependencies["unit_id"],
        deleted_at=datetime.now(timezone.utc),
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead
