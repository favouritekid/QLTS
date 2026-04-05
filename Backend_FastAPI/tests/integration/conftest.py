# tests/integration/conftest.py
"""
Fixtures for integration tests.

Provides database sessions and model fixtures for end-to-end integration testing.
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

log = logging.getLogger(__name__)


# =============================================================================
# DATABASE SESSION FIXTURE
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def db(setup_test_database) -> AsyncSession:
    """
    Provide a database session for integration tests.
    Depends on setup_test_database from main conftest.py
    """
    log.info("--- [INTEGRATION] Creating database session ---")
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # Rollback any uncommitted changes at end of test
            await session.rollback()
        except Exception as e:
            log.error(f"DB session error: {e}")
            await session.rollback()
            raise
    log.info("--- [INTEGRATION] Database session closed ---")


# =============================================================================
# USER FIXTURES
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def admin_user(db: AsyncSession) -> models.User:
    """Create an admin user directly in database."""
    user = models.User(
        username="integration_test_admin",
        email="integration_admin@test.com",
        password_hash=get_password_hash("AdminPass123!"),
        role="admin",
        status="active",
        full_name="Integration Test Admin"
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def officer_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create an officer user assigned to a unit."""
    user = models.User(
        username="integration_test_officer",
        email="integration_officer@test.com",
        password_hash=get_password_hash("OfficerPass123!"),
        role="officer",
        status="active",
        full_name="Integration Test Officer",
        unit_id=seeded_dependencies["unit_id"]
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def manager_user(db: AsyncSession, seeded_dependencies: dict) -> models.User:
    """Create a manager user assigned to a unit."""
    user = models.User(
        username="integration_test_manager",
        email="integration_manager@test.com",
        password_hash=get_password_hash("ManagerPass123!"),
        role="manager",
        status="active",
        full_name="Integration Test Manager",
        unit_id=seeded_dependencies["unit_id"]
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# =============================================================================
# DEPENDENCIES FIXTURE
# =============================================================================

@pytest_asyncio.fixture(scope="function")
async def seeded_dependencies(db: AsyncSession) -> dict:
    """
    Seed required dependencies for integration tests.
    """
    # Organization Unit
    unit = models.OrganizationUnit(
        id=3001,
        name="Integration Test Unit",
        type="department"
    )
    db.add(unit)
    
    # Pipeline Stage
    stage = models.PipelineStage(
        id="INTEGRATION_TEST_STAGE",
        name="Integration Test Stage",
        order=10
    )
    db.add(stage)
    
    # Initial Status
    initial_status = models.ConsultationStatus(
        id=settings.DEFAULT_INITIAL_LEAD_STATUS_ID,
        name="New Lead (Integration Test)",
        color_code="#0000FF",
        stage_id="INTEGRATION_TEST_STAGE"
    )
    db.add(initial_status)
    
    await db.flush()

    # PR1: Seed notification rules from catalog (dispatcher requires DB rules)
    from app.scripts.sync_notification_rules import sync_notification_rules
    await sync_notification_rules(db)

    return {
        "unit_id": unit.id,
        "stage_id": stage.id,
        "initial_status_id": initial_status.id,
    }
