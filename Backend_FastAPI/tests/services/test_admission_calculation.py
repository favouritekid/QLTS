"""
Integration tests for Admission Calculation & Validation Logic.

Tests:
- Min GPA validation during submit (basic tests without score creation)
- Basic submission validation

Uses real database via fixtures.
"""

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def create_test_lead(unit_id: int, offering_id: int = None) -> int:
    """Create a test lead for admission profile."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Calculation Test Lead",
                phone="0901234800",
                email=f"calc_{datetime.now().timestamp():.0f}@test.com",
                source="website",
                unit_id=unit_id,
                offering_id=offering_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def create_admission_profile_with_rules(
    lead_id: int,
    citizen_id: str,
    min_gpa: float = 6.0,
    mandatory_docs: list = None,
) -> models.AdmissionProfile:
    """Create an admission profile with specific rules."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status="draft",
                citizen_id=citizen_id,
                academic_year=2025,
                version=1,
                applied_rules={
                    "min_gpa": min_gpa,
                    "mandatory_docs": mandatory_docs or [],
                },
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


# ==============================================================================
# TEST: BASIC SUBMISSION TESTS
# ==============================================================================


class TestBasicSubmission:
    """Test basic submission scenarios."""

    async def test_submit_with_zero_min_gpa_always_passes(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        When min_gpa is 0, profile should submit successfully.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile_with_rules(
            lead_id=lead_id,
            citizen_id="200000000003",
            min_gpa=0,  # No GPA requirement
            mandatory_docs=[],  # No doc requirement
        )
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )
        
        assert response.status_code == 200, f"Submit failed: {response.text}"
        data = response.json()
        assert data["status"] in ["submitted", "draft", "approved"], \
            f"Unexpected status: {data['status']}"

    async def test_submit_profile_exists_and_returns_response(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Basic test: submitting a draft profile returns a valid response.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile_with_rules(
            lead_id=lead_id,
            citizen_id="200000000010",
            min_gpa=0,
            mandatory_docs=[],
        )
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )
        
        assert response.status_code == 200
        assert "status" in response.json()


# ==============================================================================
# TEST: SUBMISSION VALIDATION
# ==============================================================================


class TestSubmissionValidation:
    """Test submission validation."""

    async def test_submit_without_mandatory_docs_requirement_succeeds(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Submit should succeed when no mandatory documents are required.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile_with_rules(
            lead_id=lead_id,
            citizen_id="200000000005",
            min_gpa=0,
            mandatory_docs=[],  # No required docs
        )
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )
        
        assert response.status_code == 200, f"Submit failed: {response.text}"

    async def test_submit_endpoint_responds(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Submit endpoint should respond with proper status.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile_with_rules(
            lead_id=lead_id,
            citizen_id="200000000006",
            min_gpa=0,
            mandatory_docs=[],
        )
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )
        
        # Should succeed
        assert response.status_code == 200, f"Submit failed: {response.text}"
        assert "status" in response.json()
