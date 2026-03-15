"""
Integration tests for Academic Year constraint in Admission workflow.

Tests the multi-year admission support feature:
- UNIQUE(citizen_id, academic_year) constraint
- Same citizen allowed in different years
- Same citizen rejected in same year


Uses real database via fixtures.
"""

import uuid
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def create_test_lead(unit_id: int, offering_id: int = None, assigned_officer_id: int = None) -> int:
    """Create a test lead for admission profile."""
    unique = uuid.uuid4().hex[:12]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Test Lead {unique}",
                phone="0901234500",
                email=f"test_{unique}@example.com",
                source="website",
                unit_id=unit_id,
                offering_id=offering_id,
                assigned_officer_id=assigned_officer_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def create_admission_profile_direct(
    lead_id: int,
    citizen_id: str,
    academic_year: int,
    status: str = "draft",
) -> models.AdmissionProfile:
    """Create an admission profile directly in database."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen_id,
                academic_year=academic_year,
                version=1,
                applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
            )
            session.add(profile)
            await session.flush()
            profile_id = profile.id
        
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one()


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


async def reload_profile(profile_id: int) -> models.AdmissionProfile:
    """Reload profile from database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one_or_none()


# ==============================================================================
# TEST: ACADEMIC YEAR CONSTRAINT
# ==============================================================================


class TestAcademicYearConstraint:
    """Test UNIQUE(citizen_id, academic_year) constraint."""

    async def test_same_citizen_different_year_allowed(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Same citizen_id with DIFFERENT academic_year should be ALLOWED.
        
        Scenario:
        - Profile 1: citizen_id=123456789012, year=2025
        - Profile 2: citizen_id=123456789012, year=2026
        - Result: Both should exist (allowed)
        """
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "123456789012"
        
        # Create profile for 2025
        lead_id_2025 = await create_test_lead(unit_id)
        profile_2025 = await create_admission_profile_direct(
            lead_id=lead_id_2025,
            citizen_id=citizen_id,
            academic_year=2025,
        )
        
        # Create profile for 2026 with SAME citizen_id - should succeed
        lead_id_2026 = await create_test_lead(unit_id)
        profile_2026 = await create_admission_profile_direct(
            lead_id=lead_id_2026,
            citizen_id=citizen_id,
            academic_year=2026,
        )
        
        # Both profiles should exist
        assert profile_2025.id is not None
        assert profile_2026.id is not None
        assert profile_2025.citizen_id == profile_2026.citizen_id
        assert profile_2025.academic_year != profile_2026.academic_year

    async def test_same_citizen_same_year_rejected(
        self,
        client: AsyncClient,
        seed_lead_dependencies: dict,
    ):
        """
        Same citizen_id with SAME academic_year should be REJECTED.
        
        Scenario:
        - Profile 1: citizen_id=123456789012, year=2025
        - Profile 2: citizen_id=123456789012, year=2025 (DUPLICATE)
        - Result: IntegrityError
        """
        from sqlalchemy.exc import IntegrityError
        
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "987654321098"
        
        # Create first profile for 2025
        lead_id_1 = await create_test_lead(unit_id)
        await create_admission_profile_direct(
            lead_id=lead_id_1,
            citizen_id=citizen_id,
            academic_year=2025,
        )
        
        # Try to create second profile with SAME citizen_id SAME year
        lead_id_2 = await create_test_lead(unit_id)
        
        with pytest.raises(IntegrityError):
            await create_admission_profile_direct(
                lead_id=lead_id_2,
                citizen_id=citizen_id,
                academic_year=2025,  # Same year
            )

    async def test_academic_year_in_api_response(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        API response should include academic_year field.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        officer_id = officer_user_in_db["id"]

        # Create profile via direct insert (assign lead to officer for IDOR access)
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_id)
        profile = await create_admission_profile_direct(
            lead_id=lead_id,
            citizen_id="111122223333",
            academic_year=2025,
        )

        headers = await get_auth_headers(client, officer_user_in_db)
        
        # GET profile via API
        response = await client.get(
            f"/api/admissions/{profile.id}",
            headers=headers,
        )
        
        assert response.status_code == 200, f"GET failed: {response.text}"
        data = response.json()
        
        # Verify academic_year is in response
        assert "academic_year" in data, "Response should include academic_year"
        assert data["academic_year"] == 2025


# ==============================================================================
# TEST: CITIZEN ID VALIDATION PER YEAR
# ==============================================================================


class TestCitizenIdValidationPerYear:
    """Test citizen_id validation respects academic_year."""

    async def test_submit_duplicate_citizen_id_same_year_fails(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Creating two profiles with same citizen_id+year should raise IntegrityError.
        
        This test verifies the UNIQUE(citizen_id, academic_year) constraint works.
        """
        from sqlalchemy.exc import IntegrityError
        
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "444455556666"
        
        # Create and submit first profile for 2025
        lead_id_1 = await create_test_lead(unit_id)
        await create_admission_profile_direct(
            lead_id=lead_id_1,
            citizen_id=citizen_id,
            academic_year=2025,
            status="submitted",
        )
        
        # Try to create second profile with SAME citizen_id in SAME year
        # This should fail due to the UNIQUE constraint
        lead_id_2 = await create_test_lead(unit_id)
        
        with pytest.raises(IntegrityError) as exc_info:
            await create_admission_profile_direct(
                lead_id=lead_id_2,
                citizen_id=citizen_id,
                academic_year=2025,  # Same year = should fail
                status="draft",
            )
        
        # Verify it's the expected constraint violation
        assert "uq_citizen_academic_year" in str(exc_info.value)

    async def test_submit_same_citizen_id_different_year_ok(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Submit should succeed if citizen_id exists in DIFFERENT academic_year.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "777788889999"
        
        # Create profile for 2024 (already enrolled)
        lead_id_2024 = await create_test_lead(unit_id)
        await create_admission_profile_direct(
            lead_id=lead_id_2024,
            citizen_id=citizen_id,
            academic_year=2024,
            status="enrolled",
        )
        
        # Create new profile for 2025 with same citizen_id
        lead_id_2025 = await create_test_lead(unit_id)
        profile_2025 = await create_admission_profile_direct(
            lead_id=lead_id_2025,
            citizen_id=citizen_id,
            academic_year=2025,
            status="draft",
        )
        
        # Profile should be created successfully
        assert profile_2025.id is not None
        assert profile_2025.academic_year == 2025
        assert profile_2025.citizen_id == citizen_id
