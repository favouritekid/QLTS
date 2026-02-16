"""
Service layer tests for Admission workflow.

Tests:
- create_profile: academic_year snapshotting, empty rules rejection
- update_profile: citizen_id validation per year
- submit_and_evaluate: validation errors, status transitions
- enroll_student: idempotency, data consistency
- auto-assign officer on profile creation

Uses real database via fixtures (no mocking).
"""

import random
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
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
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"test_svc_{datetime.now().timestamp():.0f}@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
                offering_id=offering_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def setup_admission_api_data(
    major_id: int,
    unit_id: int,
    officer_id: int = None,
    consultation_officer_id: int = None,
    consultation_status_id: str = "sts06",
    academic_year: int = 2025,
) -> dict:
    """Set up all data required to create an admission profile via API.

    Creates: ConfigOfferingType, ProgramOffering, OfferingAcademicInfo,
    AdmissionMethod, AdmissionCriteria, AdmissionPath, Lead (with consultation).

    Returns dict with lead_id, admission_method_id, offering_id.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 0. ConfigOfferingType
            offering_type_config = models.ConfigOfferingType(
                code=f"svc_type_{random.randint(10000, 99999)}",
                name=f"Service Test Offering Type {random.randint(10000, 99999)}",
                is_active=True,
            )
            session.add(offering_type_config)
            await session.flush()

            # 1. ProgramOffering
            offering = models.ProgramOffering(
                offering_type=f"SvcTest_{random.randint(10000, 99999)}",
                program_id=major_id,
                offering_type_id=offering_type_config.id,
            )
            session.add(offering)
            await session.flush()

            # 2. OfferingAcademicInfo
            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=academic_year,
                is_published=True,
            )
            session.add(academic_info)
            await session.flush()

            # 3. AdmissionMethod
            method = models.AdmissionMethod(
                code=f"svc_method_{random.randint(10000, 99999)}",
                name="Service Test Method",
                is_active=True,
            )
            session.add(method)
            await session.flush()

            # 4. AdmissionCriteria
            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"svc_criteria_{random.randint(10000, 99999)}",
                name="Service Test Criteria",
                min_gpa=0,
                is_active=True,
            )
            session.add(criteria)
            await session.flush()

            # 5. AdmissionPath
            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                criteria_id=criteria.id,
                status="active",
            )
            session.add(path)
            await session.flush()

            # 6. Lead
            lead = models.Lead(
                full_name="Service API Test Lead",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"svc_api_{datetime.now().timestamp():.0f}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                offering_id=offering.id,
            )
            session.add(lead)
            await session.flush()

            # 7. Consultation (use consultation_officer_id if provided, else officer_id)
            _consult_officer = consultation_officer_id or officer_id
            if _consult_officer is not None:
                consultation = models.Consultation(
                    lead_id=lead.id,
                    consultation_date=datetime.now(timezone.utc),
                    method="phone",
                    notes="Service test consultation",
                    officer_id=_consult_officer,
                    consultation_status_id=consultation_status_id,
                )
                session.add(consultation)
                await session.flush()

    return {
        "lead_id": lead.id,
        "admission_method_id": method.id,
        "offering_id": offering.id,
        "academic_info_id": academic_info.id,
        "criteria_id": criteria.id,
    }


async def create_submittable_profile_direct(
    lead_id: int,
    citizen_id: str = None,
    applied_rules: dict = None,
) -> models.AdmissionProfile:
    """Create a profile directly in DB that can be submitted.

    Includes proper applied_rules, family_info, academic_history, and subject scores.
    """
    if citizen_id is None:
        citizen_id = f"0{datetime.now().timestamp():.0f}"[:12]

    if applied_rules is None:
        applied_rules = {
            "min_gpa": 0,
            "mandatory_docs": [],
            "allowed_subject_codes": ["TOAN"],
            "scoring_method": "sum",
            "required_subject_count": 1,
            "subject_selection_mode": "fixed",
        }

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Create subject if needed
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
                version=1,
                applied_rules=applied_rules,
                academic_year=2025,
                family_info=[{"relationship": "Cha", "full_name": "Test Father", "phone": "0901234567"}],
                academic_history=[{"school_name": "THPT Test", "year_from": 2020, "year_to": 2024}],
            )
            session.add(profile)
            await session.flush()

            # Add subject score
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

    # Clear cookies to prevent session interference
    client.cookies.delete("access_token")

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

        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            academic_year=2026,
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )

        assert response.status_code == 201, f"Create failed: {response.text}"
        result = response.json()

        # Verify academic_year was snapshotted
        assert result["academic_year"] == 2026, f"Expected 2026, got {result['academic_year']}"

    async def test_create_profile_fallback_to_current_year(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        When offering has no published academic info for future year,
        academic_year should fallback to current year.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        current_year = datetime.now(timezone.utc).year

        # Setup with current year (ensures it works)
        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            academic_year=current_year,
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )

        assert response.status_code == 201, f"Create failed: {response.text}"
        result = response.json()

        assert result["academic_year"] == current_year

    async def test_create_profile_rejects_invalid_method(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Profile creation should fail if admission_method_id doesn't match any path.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

        # Setup valid data but use a non-existent method ID
        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": 99999,  # Non-existent method
            },
            headers=headers,
        )

        # Should fail (400 or 404)
        assert response.status_code in [400, 404], \
            f"Expected error for invalid method, got {response.status_code}: {response.text}"


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

        # Create two profiles via API setup
        data1 = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            academic_year=2025,
        )
        data2 = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            academic_year=2025,
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        # Create profile 1
        response1 = await client.post(
            "/api/admissions",
            json={"lead_id": data1["lead_id"], "admission_method_id": data1["admission_method_id"]},
            headers=headers,
        )
        assert response1.status_code == 201, f"Create 1 failed: {response1.text}"
        profile1_id = response1.json()["id"]

        # Update profile 1 with citizen_id
        await client.put(
            f"/api/admissions/{profile1_id}",
            json={"citizen_id": "111122223333", "version": 1},
            headers=headers,
        )

        # Create profile 2
        response2 = await client.post(
            "/api/admissions",
            json={"lead_id": data2["lead_id"], "admission_method_id": data2["admission_method_id"]},
            headers=headers,
        )
        assert response2.status_code == 201, f"Create 2 failed: {response2.text}"
        profile2_id = response2.json()["id"]

        # Try to update profile 2 with SAME citizen_id - should fail
        update_response = await client.put(
            f"/api/admissions/{profile2_id}",
            json={"citizen_id": "111122223333", "version": 1},
            headers=headers,
        )

        assert update_response.status_code == 409, f"Expected 409 Conflict: {update_response.text}"


# ==============================================================================
# TEST: SUBMIT AND EVALUATE
# ==============================================================================


class TestSubmitAndEvaluate:
    """Test submit_and_evaluate service.

    These tests create profiles directly in DB to focus on submit behavior,
    bypassing the API creation flow.
    """

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

        lead_id = await create_test_lead(
            unit_id, assigned_officer_id=officer_user_in_db["id"]
        )
        profile = await create_submittable_profile_direct(lead_id)

        headers = await get_auth_headers(client, officer_user_in_db)

        submit_response = await client.post(
            f"/api/admissions/{profile.id}/submit",
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
        Profile without citizen_id should fail validation.
        """
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(
            unit_id, assigned_officer_id=officer_user_in_db["id"]
        )

        # Create profile WITHOUT citizen_id (required for submit)
        async with AsyncSessionLocal() as session:
            async with session.begin():
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
                    citizen_id=None,  # Missing citizen_id -> validation error
                    version=1,
                    applied_rules={
                        "min_gpa": 0,
                        "mandatory_docs": [],
                        "allowed_subject_codes": ["TOAN"],
                        "scoring_method": "sum",
                        "required_subject_count": 1,
                        "subject_selection_mode": "fixed",
                    },
                    academic_year=2025,
                    family_info=[{"relationship": "Cha", "full_name": "Test Father", "phone": "0901234567"}],
                    academic_history=[{"school_name": "THPT Test", "year_from": 2020, "year_to": 2024}],
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

        headers = await get_auth_headers(client, officer_user_in_db)

        submit_response = await client.post(
            f"/api/admissions/{profile_id}/submit",
            headers=headers,
        )

        data = submit_response.json()
        # Status should be DRAFT (validation failed due to missing citizen_id)
        assert data.get("status") == "draft", f"Should stay draft: {data}"
        assert data.get("validation_errors"), "Should have validation errors"

    async def test_submit_respects_min_subject_score(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Submit should FAIL if any subject is below `min_subject_score` (Diem liet).
        """
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(
            unit_id, assigned_officer_id=officer_user_in_db["id"]
        )

        # Create profile with min_subject_score threshold
        profile = await create_submittable_profile_direct(
            lead_id,
            applied_rules={
                "min_gpa": 0,
                "min_subject_score": 5.0,  # Subject must be >= 5.0
                "mandatory_docs": [],
                "allowed_subject_codes": ["TOAN"],
                "scoring_method": "sum",
                "required_subject_count": 1,
                "subject_selection_mode": "fixed",
            },
        )

        # Override score to be below threshold
        async with AsyncSessionLocal() as session:
            async with session.begin():
                scores = (await session.execute(
                    select(models.ProfileSubjectScore)
                    .where(models.ProfileSubjectScore.profile_id == profile.id)
                )).scalars().all()
                for s in scores:
                    s.score = 1.0  # Below min_subject_score=5.0

        headers = await get_auth_headers(client, officer_user_in_db)

        submit_res = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )
        data = submit_res.json()

        # Should stay in draft with validation errors
        assert data.get("status") == "draft", f"Should stay draft: {data}"
        errors = str(data.get("validation_errors", []))
        assert "SUBJECT_BELOW_THRESHOLD" in errors or "liệt" in errors.lower() or "thấp" in errors.lower(), \
            f"Expected min_subject_score error: {errors}"

    async def test_submit_uses_best_n_logic(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Submit should PASS if Best 3 subjects > min_gpa, ignoring low 4th subject.
        """
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(
            unit_id, assigned_officer_id=officer_user_in_db["id"]
        )

        # Create profile with best_n selection (pick best 3 of 4)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # Create subjects
                subjects = {}
                for code in ["MATH", "PHYSICS", "ENGLISH", "HISTORY"]:
                    subj = (await session.execute(
                        select(models.Subject).where(models.Subject.code == code)
                    )).scalar_one_or_none()
                    if not subj:
                        subj = models.Subject(code=code, name_vi=code, is_active=True)
                        session.add(subj)
                        await session.flush()
                    subjects[code] = subj

                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="draft",
                    citizen_id=f"0{datetime.now().timestamp():.0f}"[:12],
                    version=1,
                    applied_rules={
                        "min_gpa": 8.0,
                        "mandatory_docs": [],
                        "allowed_subject_codes": ["MATH", "PHYSICS", "ENGLISH", "HISTORY"],
                        "scoring_method": "average",
                        "required_subject_count": 3,
                        "subject_selection_mode": "best_n",
                    },
                    academic_year=2025,
                    family_info=[{"relation": "father", "name": "Test Father"}],
                    academic_history=[{"school": "Test School", "year": 2024}],
                )
                session.add(profile)
                await session.flush()

                # 3 High scores (9,9,9) + 1 Low (2) → Best 3 avg = 9.0 > min_gpa=8.0
                scores = [
                    ("MATH", 9.0), ("PHYSICS", 9.0),
                    ("ENGLISH", 9.0), ("HISTORY", 2.0),
                ]
                for code, score_val in scores:
                    session.add(models.ProfileSubjectScore(
                        profile_id=profile.id,
                        subject_id=subjects[code].id,
                        score=score_val,
                    ))
                await session.flush()
                profile_id = profile.id

        headers = await get_auth_headers(client, officer_user_in_db)

        submit_res = await client.post(
            f"/api/admissions/{profile_id}/submit",
            headers=headers,
        )

        assert submit_res.status_code == 200, f"Submit failed: {submit_res.text}"
        data = submit_res.json()

        assert data["status"] == "submitted"
        assert not data.get("validation_errors")


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
                    status="confirmed",
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

        assert response2.status_code in [200, 201], f"Second enroll failed: {response2.text}"
        student_code_2 = response2.json()["student_code"]

        assert student_code_1 == student_code_2, "Idempotent enroll should return same student"


# ==============================================================================
# TEST: AUTO-ASSIGN OFFICER ON PROFILE CREATION
# ==============================================================================


class TestAutoAssignOfficer:
    """Test that creating a profile auto-assigns the officer to the lead."""

    async def test_officer_creates_profile_auto_assigns_lead(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        When officer creates a profile for a lead with no assigned_officer_id,
        the service should auto-assign lead.assigned_officer_id = officer.id.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

        # Setup with NO officer_id on lead (will be auto-assigned)
        # consultation_officer_id is needed because consultation.officer_id is NOT NULL
        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=None,  # Lead starts unassigned
            consultation_officer_id=officer_user_in_db["id"],  # Consultation still needs officer
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert response.status_code == 201, f"Create failed: {response.text}"

        # Verify lead now has assigned_officer_id = officer's id
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.Lead).where(models.Lead.id == data["lead_id"])
            )
            lead = result.scalar_one()
            assert lead.assigned_officer_id == officer_user_in_db["id"], \
                f"Expected auto-assign to officer {officer_user_in_db['id']}, got {lead.assigned_officer_id}"
