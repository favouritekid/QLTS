# tests/repositories/conftest.py
"""
Fixtures for repository integration tests.

These fixtures provide real database sessions for testing repository methods directly.
"""
import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.security import get_password_hash
from app.config import settings
from app.core.constants import UserRole

log = logging.getLogger(__name__)


# =============================================================================
# DATABASE SESSION FIXTURE
# =============================================================================

@pytest_asyncio.fixture
async def db(setup_test_database) -> AsyncSession:
    """
    Provide a database session for repository integration tests.
    
    This fixture:
    1. Depends on setup_test_database to ensure schema is ready
    2. Creates a new AsyncSession for the test
    3. Yields the session for test use
    4. Closes the session after test completes
    """
    async with AsyncSessionLocal() as session:
        yield session


# =============================================================================
# USER FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def admin_user_in_db(db: AsyncSession) -> dict:
    """Create an admin user directly in database."""
    user = models.User(
        username="repo_test_admin",
        email="repo_admin@test.com",
        password_hash=get_password_hash("AdminPass123!"),
        role="admin",
        status="active",
        full_name="Repo Test Admin"
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}


@pytest_asyncio.fixture
async def officer_user_in_db(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """Create an officer user assigned to a unit."""
    user = models.User(
        username="repo_test_officer",
        email="repo_officer@test.com",
        password_hash=get_password_hash("OfficerPass123!"),
        role="officer",
        status="active",
        full_name="Repo Test Officer",
        unit_id=seeded_dependencies["unit_id"]
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}


@pytest_asyncio.fixture
async def manager_user_in_db(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """Create a manager user assigned to a unit."""
    user = models.User(
        username="repo_test_manager",
        email="repo_manager@test.com",
        password_hash=get_password_hash("ManagerPass123!"),
        role="manager",
        status="active",
        full_name="Repo Test Manager",
        unit_id=seeded_dependencies["unit_id"]
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return {"id": user.id, "username": user.username, "role": user.role}


# =============================================================================
# DEPENDENCIES FIXTURE
# =============================================================================

@pytest_asyncio.fixture
async def seeded_dependencies(db: AsyncSession) -> dict:
    """
    Seed required dependencies for repository tests.
    """
    # Organization Unit
    unit = models.OrganizationUnit(
        id=2001,
        name="Repo Test Unit",
        type="department"
    )
    db.add(unit)
    
    # Pipeline Stage
    stage = models.PipelineStage(
        id="REPO_TEST_STAGE",
        name="Repo Test Stage",
        order=10
    )
    db.add(stage)
    
    # Initial Status
    initial_status = models.ConsultationStatus(
        id=settings.DEFAULT_INITIAL_LEAD_STATUS_ID,
        name="New Lead (Repo Test)",
        color_code="#0000FF",
        stage_id="REPO_TEST_STAGE"
    )
    db.add(initial_status)
    
    await db.flush()
    
    return {
        "unit_id": unit.id,
        "stage_id": stage.id,
        "initial_status_id": initial_status.id,
    }


# =============================================================================
# LEAD FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def seeded_lead(
    db: AsyncSession, 
    seeded_dependencies: dict, 
    officer_user_in_db: dict
) -> models.Lead:
    """Create a lead assigned to the officer user."""
    lead = models.Lead(
        full_name="Repo Test Lead",
        phone="0909555666",
        email="repo_lead@test.com",
        source="Website",
        unit_id=seeded_dependencies["unit_id"],
        status=seeded_dependencies["initial_status_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
        assigned_officer_id=officer_user_in_db["id"],
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


@pytest_asyncio.fixture
async def unassigned_lead(
    db: AsyncSession, 
    seeded_dependencies: dict
) -> models.Lead:
    """Create an unassigned lead."""
    lead = models.Lead(
        full_name="Unassigned Repo Lead",
        phone="0909777888",
        email="unassigned_repo@test.com",
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
