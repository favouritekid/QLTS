"""
Service layer tests for Admission workflow.

Tests:
- create_profile: academic_year snapshotting, empty rules rejection
- update_profile: citizen_id validation per year
- submit_and_evaluate: validation errors, status transitions
- enroll_student: idempotency, data consistency

Uses real database via fixtures (no mocking).
"""

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


async def create_test_lead(
    unit_id: int, 
    offering_id: int = None,
    assigned_officer_id: int = None,
) -> int:
    """Create a test lead for admission profile."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Test Applicant Service",
                phone="0901234599",
                email="test_service@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
                offering_id=offering_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def create_program_offering(
    major_id: int,
    admission_rules: dict = None,
) -> int:
    """Create a program offering with admission rules.
    
    Args:
        major_id: Existing MajorProgram ID from seed_lead_dependencies fixture
        admission_rules: Admission rules dict
        
    Returns:
        ProgramOffering ID
    """
    import random
    async with AsyncSessionLocal() as session:
        async with session.begin():
            offering = models.ProgramOffering(
                offering_type=f"Test_{random.randint(1000, 9999)}",
                program_id=major_id,
                # Use if None check, not `or`, so empty {} is preserved for testing
                admission_rules=admission_rules if admission_rules is not None else {"min_gpa": 6.0, "mandatory_docs": []},
            )
            session.add(offering)
            await session.flush()
            offering_id = offering.id
    return offering_id


async def create_offering_academic_info(offering_id: int, academic_year: int) -> int:
    """Create academic info for the offering."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            info = models.OfferingAcademicInfo(
                offering_id=offering_id,
                academic_year=academic_year,
                is_published=True,
                admission_criteria=[],
            )
            session.add(info)
            await session.flush()
            return info.id


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
# TEST: CREATE PROFILE
# ==============================================================================


class TestCreateProfile:
    """Test create_profile service with academic_year snapshotting."""

    async def test_create_profile_sets_academic_year_from_offering(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        When creating a profile, academic_year should be snapshotted 
        from OfferingAcademicInfo.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        
        # Create offering with academic info for specific year
        offering_id = await create_program_offering(major_id, {"min_gpa": 6.0, "mandatory_docs": []})
        await create_offering_academic_info(offering_id, academic_year=2026)
        
        # Create lead linked to offering
        lead_id = await create_test_lead(unit_id, offering_id=offering_id)
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        # Create profile via API
        response = await client.post(
            "/api/admissions",
            json={"lead_id": lead_id},
            headers=headers,
        )
        
        assert response.status_code == 201, f"Create failed: {response.text}"
        data = response.json()
        
        # Verify academic_year was snapshotted
        assert data["academic_year"] == 2026, f"Expected 2026, got {data['academic_year']}"

    async def test_create_profile_fallback_to_current_year(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        When offering has no academic info, academic_year should fallback to current year.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        current_year = datetime.now(timezone.utc).year
        
        # Create offering WITHOUT academic info
        offering_id = await create_program_offering(major_id, {"min_gpa": 5.0, "mandatory_docs": []})
        # Note: No call to create_offering_academic_info
        
        lead_id = await create_test_lead(unit_id, offering_id=offering_id)
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.post(
            "/api/admissions",
            json={"lead_id": lead_id},
            headers=headers,
        )
        
        assert response.status_code == 201, f"Create failed: {response.text}"
        data = response.json()
        
        # Fallback to current year
        assert data["academic_year"] == current_year

    async def test_create_profile_rejects_empty_applied_rules(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Profile creation should fail if offering has no admission rules.
        (FIX #8: Reject empty applied_rules)
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        
        # Create offering with EMPTY rules
        offering_id = await create_program_offering(major_id, admission_rules={})
        
        lead_id = await create_test_lead(unit_id, offering_id=offering_id)
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        response = await client.post(
            "/api/admissions",
            json={"lead_id": lead_id},
            headers=headers,
        )
        
        # Should fail with 400
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        assert "no admission rules" in response.json()["detail"].lower()


# ==============================================================================
# TEST: UPDATE PROFILE (CITIZEN_ID VALIDATION)
# ==============================================================================


class TestUpdateProfileCitizenId:
    """Test update_profile citizen_id validation per academic year."""

    async def test_update_citizen_id_to_duplicate_same_year_fails(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Updating citizen_id to one already used in the same academic year should fail.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        
        # Create offering
        offering_id = await create_program_offering(major_id)
        await create_offering_academic_info(offering_id, academic_year=2025)
        
        # Create two leads
        lead_id_1 = await create_test_lead(unit_id, offering_id=offering_id)
        lead_id_2 = await create_test_lead(unit_id, offering_id=offering_id)
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        # Create profile 1 with citizen_id
        response1 = await client.post("/api/admissions", json={"lead_id": lead_id_1}, headers=headers)
        assert response1.status_code == 201
        profile1_id = response1.json()["id"]
        
        # Update profile 1 with citizen_id
        await client.put(
            f"/api/admissions/{profile1_id}",
            json={"citizen_id": "111122223333", "version": 1},
            headers=headers,
        )
        
        # Create profile 2
        response2 = await client.post("/api/admissions", json={"lead_id": lead_id_2}, headers=headers)
        assert response2.status_code == 201
        profile2_id = response2.json()["id"]
        
        # Try to update profile 2 with SAME citizen_id - should fail
        update_response = await client.put(
            f"/api/admissions/{profile2_id}",
            json={"citizen_id": "111122223333", "version": 1},
            headers=headers,
        )
        
        assert update_response.status_code == 409, f"Expected 409 Conflict: {update_response.text}"
        assert "đã được sử dụng" in update_response.json()["detail"]


# ==============================================================================
# TEST: SUBMIT AND EVALUATE
# ==============================================================================


class TestSubmitAndEvaluate:
    """Test submit_and_evaluate service."""

    async def test_submit_transitions_to_submitted_not_approved(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Submit should transition to SUBMITTED status (not auto-approve).
        (FIX #1)
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        
        offering_id = await create_program_offering(major_id, {"min_gpa": 0, "mandatory_docs": []})
        await create_offering_academic_info(offering_id, 2025)
        
        lead_id = await create_test_lead(unit_id, offering_id=offering_id)
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        # Create profile
        create_response = await client.post("/api/admissions", json={"lead_id": lead_id}, headers=headers)
        assert create_response.status_code == 201
        profile_id = create_response.json()["id"]
        
        # Update with required fields (citizen_id)
        await client.put(
            f"/api/admissions/{profile_id}",
            json={"citizen_id": "999988887777", "version": 1},
            headers=headers,
        )
        
        # Submit
        submit_response = await client.post(
            f"/api/admissions/{profile_id}/submit",
            headers=headers,
        )
        
        assert submit_response.status_code == 200, f"Submit failed: {submit_response.text}"
        data = submit_response.json()
        
        # Status should be "submitted", NOT "approved"
        assert data["status"] == "submitted", f"Expected 'submitted', got '{data['status']}'"

    async def test_submit_with_validation_errors_stays_draft(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Submit with validation errors should keep status in DRAFT.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        
        offering_id = await create_program_offering(major_id, {"min_gpa": 9.0, "mandatory_docs": []})
        await create_offering_academic_info(offering_id, 2025)
        
        lead_id = await create_test_lead(unit_id, offering_id=offering_id)
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        # Create profile
        create_response = await client.post("/api/admissions", json={"lead_id": lead_id}, headers=headers)
        profile_id = create_response.json()["id"]
        
        # Update with citizen_id but NO scores (will fail min_gpa check)
        await client.put(
            f"/api/admissions/{profile_id}",
            json={"citizen_id": "888877776666", "version": 1},
            headers=headers,
        )
        
        # Submit - should return validation errors and stay in draft
        submit_response = await client.post(
            f"/api/admissions/{profile_id}/submit",
            headers=headers,
        )
        
        # Response should indicate validation failed
        data = submit_response.json()
        # Status should be DRAFT (not submitted)
        assert data.get("status") in ["draft", None], f"Should stay draft: {data}"
        # Should have validation errors
        assert data.get("validation_errors") is not None or "validation" in str(data).lower()


# ==============================================================================
# TEST: ENROLL STUDENT (IDEMPOTENCY)
# ==============================================================================


class TestEnrollStudentIdempotency:
    """Test enroll_student idempotency (FIX #7)."""

    async def test_enroll_twice_returns_same_student(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Calling enroll twice on same profile should return existing student.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        # Setup: Create profile in CONFIRMED status (ready to enroll)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                lead = models.Lead(
                    full_name="Enroll Test",
                    phone="0909090909",
                    email="enroll@test.com",
                    source="website",
                    unit_id=unit_id,
                )
                session.add(lead)
                await session.flush()
                lead_id = lead.id
                
                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="confirmed",  # Ready to enroll
                    citizen_id="555544443333",
                    academic_year=2025,
                    version=1,
                    applied_rules={"min_gpa": 0},
                )
                session.add(profile)
                await session.flush()
                profile_id = profile.id
        
        headers = await get_auth_headers(client, admin_user_in_db)
        
        # First enroll
        response1 = await client.post(
            f"/api/admissions/{profile_id}/enroll",
            headers=headers,
        )
        assert response1.status_code == 201, f"First enroll failed: {response1.text}"
        student_code_1 = response1.json()["student_code"]
        
        # Second enroll (idempotent - should return same student)
        response2 = await client.post(
            f"/api/admissions/{profile_id}/enroll",
            headers=headers,
        )
        
        # Should succeed (200 or 201) and return same student
        assert response2.status_code in [200, 201], f"Second enroll failed: {response2.text}"
        student_code_2 = response2.json()["student_code"]
        
        # Same student code
        assert student_code_1 == student_code_2, "Idempotent enroll should return same student"
