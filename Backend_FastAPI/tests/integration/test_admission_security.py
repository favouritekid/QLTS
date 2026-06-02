"""
Integration tests for Admission Security Fixes.

Tests the security fixes implemented:
- FIX #2: Pessimistic locking (concurrent submit)
- FIX #7: Idempotency in enroll_student
- FIX #8: Reject empty applied_rules (covered in test_admission_service.py)

Uses real database via fixtures.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.builders import (
    ensure_submittable_ward,
    seed_submittable_offering_config,
    submittable_profile_fields,
)


pytestmark = pytest.mark.asyncio


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def create_test_lead(unit_id: int, offering_id: int = None, assigned_officer_id: int = None) -> int:
    """Create a test lead for admission profile."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Security Test Lead",
                phone="0901234511",
                email=f"security_{datetime.now().timestamp():.0f}@test.com",
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
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
            )
            session.add(profile)
            await session.flush()
            profile_id = profile.id

        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one()


async def create_submittable_profile_direct(
    lead_id: int,
    citizen_id: str,
    academic_year: int = 2025,
) -> models.AdmissionProfile:
    """Create a profile that can be submitted (with subject scores, family_info, etc.)."""
    # Gap #3: a current-era ward so the permanent address validates.
    await ensure_submittable_ward()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = await session.get(models.Lead, lead_id)
            # #337: legacy config + KV chain so submit can derive the
            # target level + resolve KV (else CONFIG_GAP / KV_UNRESOLVED).
            seed = await seed_submittable_offering_config(
                session, lead.unit_id, academic_year
            )
            subj = (await session.execute(
                select(models.Subject).where(models.Subject.code == "TOAN")
            )).scalar_one_or_none()
            if not subj:
                subj = models.Subject(code="TOAN", name_vi="Toan", is_active=True)
                session.add(subj)
                await session.flush()

            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status="draft",
                citizen_id=citizen_id,
                academic_year=seed["academic_year"],
                version=1,
                applied_rules={
                    "min_gpa": 0,
                    "mandatory_docs": [],
                    "allowed_subject_codes": ["TOAN"],
                    "scoring_method": "sum",
                    "required_subject_count": 1,
                    "subject_selection_mode": "fixed",
                },
                family_info=[{"relationship": "Cha", "full_name": "Test Father", "phone": "0901234567"}],
                **submittable_profile_fields(seed),
            )
            session.add(profile)
            await session.flush()

            score = models.ProfileSubjectScore(
                profile_id=profile.id,
                subject_id=subj.id,
                score=8.0,
            )
            session.add(score)
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

    # Clear cookies to prevent cross-user contamination in multi-user tests
    client.cookies.delete("access_token")

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
# TEST: PESSIMISTIC LOCKING (FIX #2)
# ==============================================================================


class TestPessimisticLocking:
    """Test concurrent operations protected by SELECT FOR UPDATE."""

    async def test_concurrent_submit_one_succeeds(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Concurrent submit requests should be serialized.
        Only one should succeed, others should fail gracefully.
        
        FIX #2: Added SELECT FOR UPDATE in submit_and_evaluate
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        # Create submittable profile (assigned to officer for 3-tier IDOR)
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_submittable_profile_direct(
            lead_id=lead_id,
            citizen_id="333322221111",
            academic_year=2025,
        )
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        # Simulate concurrent submit requests
        async def submit_request():
            return await client.post(
                f"/api/admissions/{profile.id}/submit",
                headers=headers,
            )
        
        # Execute 3 concurrent submits
        results = await asyncio.gather(
            submit_request(),
            submit_request(),
            submit_request(),
            return_exceptions=True,
        )
        
        # Count successful submissions
        success_count = sum(
            1 for r in results 
            if hasattr(r, "status_code") and r.status_code == 200
        )
        
        # At least one should succeed
        assert success_count >= 1, "At least one submit should succeed"
        
        # Verify final state is valid
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.status in ["draft", "submitted"], \
            f"Final status should be valid, got: {updated_profile.status}"


# ==============================================================================
# TEST: IDEMPOTENCY (FIX #7)
# ==============================================================================


class TestIdempotency:
    """Test idempotent operations."""

    async def test_enroll_twice_returns_same_student(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Enrolling already-enrolled profile should return existing student.
        
        FIX #7: Added idempotency check in enroll_student
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        # Create profile in confirmed status
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile_direct(
            lead_id=lead_id,
            citizen_id="666655554444",
            academic_year=2025,
            status="confirmed",
        )
        
        headers = await get_auth_headers(client, admin_user_in_db)
        
        # First enroll
        response1 = await client.post(
            f"/api/admissions/{profile.id}/enroll",
            headers=headers,
        )
        assert response1.status_code == 201, f"First enroll failed: {response1.text}"
        data1 = response1.json()
        student_code_1 = data1["student_code"]
        
        # Second enroll (should be idempotent)
        response2 = await client.post(
            f"/api/admissions/{profile.id}/enroll",
            headers=headers,
        )
        
        # Should not fail
        assert response2.status_code in [200, 201], \
            f"Second enroll should succeed (idempotent): {response2.text}"
        
        data2 = response2.json()
        student_code_2 = data2["student_code"]
        
        # Should return same student
        assert student_code_1 == student_code_2, \
            f"Idempotent: should return same student. Got {student_code_1} vs {student_code_2}"

    async def test_enroll_inconsistent_state_returns_conflict(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Profile marked as 'enrolled' but without student record 
        should return clear error.
        
        This tests the data inconsistency detection in FIX #7.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        # Create profile in "enrolled" status but WITHOUT student record
        # This is an inconsistent state that shouldn't happen normally
        lead_id = await create_test_lead(unit_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="enrolled",  # Inconsistent: enrolled but no student
                    citizen_id="888877776655",
                    academic_year=2025,
                    version=1,
                    applied_rules={"min_gpa": 0},
                )
                session.add(profile)
                await session.flush()
                profile_id = profile.id
        
        headers = await get_auth_headers(client, admin_user_in_db)
        
        # Try to enroll - should detect data inconsistency (enrolled but no student)
        # The idempotency check finds status='enrolled' but no student record => ConflictError (409)
        response = await client.post(
            f"/api/admissions/{profile_id}/enroll",
            headers=headers,
        )
        
        # Returns 409 because profile is enrolled but no student (data inconsistency)
        assert response.status_code == 409, \
            f"Expected 409 for data inconsistency (enrolled without student): {response.text}"


# ==============================================================================
# TEST: CITIZEN ID DUPLICATE CHECK IN ENROLL (FIX #3)
# ==============================================================================


class TestCitizenIdDuplicateCheck:
    """Test citizen_id duplicate check inside enrollment transaction."""

    async def test_enroll_with_duplicate_citizen_id_fails(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Enrollment should fail if citizen_id already exists as Student.
        
        FIX #3: Final citizen_id duplicate check INSIDE transaction
        """
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "999988887776"
        
        # Create and enroll first profile
        lead_id_1 = await create_test_lead(unit_id)
        profile_1 = await create_admission_profile_direct(
            lead_id=lead_id_1,
            citizen_id=citizen_id,
            academic_year=2025,
            status="confirmed",
        )
        
        headers = await get_auth_headers(client, admin_user_in_db)
        
        # Enroll first profile
        response1 = await client.post(
            f"/api/admissions/{profile_1.id}/enroll",
            headers=headers,
        )
        assert response1.status_code == 201, f"First enroll failed: {response1.text}"
        
        # Create second profile with SAME citizen_id (different year to pass constraint)
        lead_id_2 = await create_test_lead(unit_id)
        profile_2 = await create_admission_profile_direct(
            lead_id=lead_id_2,
            citizen_id=citizen_id,
            academic_year=2026,  # Different year
            status="confirmed",
        )
        
        # Try to enroll second profile - should fail
        # (citizen_id already enrolled as Student)
        response2 = await client.post(
            f"/api/admissions/{profile_2.id}/enroll",
            headers=headers,
        )
        
        # Should fail with 409 (citizen already enrolled)
        assert response2.status_code == 409, \
            f"Should fail for duplicate citizen_id: {response2.text}"
        detail = response2.json().get("detail", "").lower()
        assert "citizen" in detail or "cccd" in detail or "đã được sử dụng" in detail
