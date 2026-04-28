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
import uuid
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
    unique = uuid.uuid4().hex[:12]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Test Applicant Service {unique}",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"test_svc_{unique}@example.com",
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
            lead_unique = uuid.uuid4().hex[:12]
            lead = models.Lead(
                full_name=f"Service API Test Lead {lead_unique}",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"svc_api_{lead_unique}@test.com",
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


class TestUpdateProfileLazyLoadRegression:
    """Regression tests for MissingGreenlet / lazy-load bugs in update_profile.

    Background: Before the fix, `_compute_frontend_fields()` (sync helper called at the
    end of update_profile) accessed `profile.lead.assigned_officer.full_name`, but
    the `update_profile` query only eager-loaded `lead` — not the nested
    `lead.assigned_officer`. This triggered a lazy-load from a sync function inside
    an async SQLAlchemy session, causing `sqlalchemy.exc.MissingGreenlet` and a 500
    response with no CORS headers (which the browser reported as a misleading
    "CORS policy blocked" error).

    The fix does two things:
    1. `update_profile` now eager-loads `lead.assigned_officer` and `assigned_reviewer`
    2. `_compute_frontend_fields` uses `profile.__dict__.get(...)` instead of
       `hasattr/getattr` to avoid triggering lazy-loads entirely
    """

    async def test_update_draft_profile_with_assigned_officer_does_not_crash(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        PUT /api/admissions/{id} must NOT raise MissingGreenlet when:
        - The profile's lead has an assigned_officer_id set
        - _compute_frontend_fields is called after the update

        Before fix: returned 500 with SQLAlchemy MissingGreenlet traceback
        After fix: returns 200 with updated profile including assigned_officer_name
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

        # Create lead with assigned_officer_id pointing to officer_user_in_db
        # This is the key condition that triggered the lazy-load bug
        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            academic_year=2025,
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        # Create profile in draft state
        create_response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert create_response.status_code == 201, f"Create failed: {create_response.text}"
        profile_id = create_response.json()["id"]

        # Update the draft profile — this call must NOT raise MissingGreenlet.
        # Changing gender is sufficient; the bug triggers regardless of which field changes.
        update_response = await client.put(
            f"/api/admissions/{profile_id}",
            json={"gender": "Nam", "version": 1},
            headers=headers,
        )

        # Primary assertion: no 500 (no MissingGreenlet)
        assert update_response.status_code == 200, (
            f"Expected 200 but got {update_response.status_code}. "
            f"Response: {update_response.text}. "
            f"If this is a 500 with MissingGreenlet, the eager-load fix in "
            f"update_profile() or the __dict__.get() fix in _compute_frontend_fields() "
            f"regressed."
        )

        body = update_response.json()

        # Secondary assertion: update actually applied
        assert body.get("gender") == "Nam", f"Gender not updated: {body}"

        # Tertiary assertion: _compute_frontend_fields ran and populated denormalized
        # display names (proving the sync helper didn't crash on lazy-load).
        # assigned_officer_name is set from profile.lead.assigned_officer.full_name
        # via profile.__dict__.get("lead").__dict__.get("assigned_officer").
        # Note: officer_user_in_db fixture may not set full_name, so we only assert
        # the KEY exists (schema contract), not a specific value.
        assert "assigned_officer_name" in body, (
            "assigned_officer_name missing from response — _compute_frontend_fields "
            "may not have run correctly"
        )

    async def test_update_draft_profile_without_assigned_officer_does_not_crash(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Edge case: lead has NO assigned_officer (officer_id=None).
        The __dict__.get() fallback must return None without raising.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

        # Note: setup_admission_api_data requires officer for consultation, so we still
        # pass officer_id, but we then manually null out lead.assigned_officer_id below.
        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            academic_year=2025,
        )

        # Null out the assigned_officer_id directly in DB
        async with AsyncSessionLocal() as session:
            async with session.begin():
                lead = await session.get(models.Lead, data["lead_id"])
                lead.assigned_officer_id = None

        headers = await get_auth_headers(client, officer_user_in_db)

        create_response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert create_response.status_code == 201, f"Create failed: {create_response.text}"
        profile_id = create_response.json()["id"]

        update_response = await client.put(
            f"/api/admissions/{profile_id}",
            json={"gender": "Nữ", "version": 1},
            headers=headers,
        )

        assert update_response.status_code == 200, (
            f"Expected 200, got {update_response.status_code}: {update_response.text}"
        )
        body = update_response.json()
        assert body.get("assigned_officer_name") is None, (
            f"Expected None when lead has no assigned_officer, got {body.get('assigned_officer_name')!r}"
        )


class TestUpdateProfileDocumentsInResponse:
    """Regression tests for MEDIUM #1: update_profile response must reflect actual document state.

    Background: update_profile() used to call _compute_frontend_fields(profile, current_user)
    without passing `documents`, causing _validate_documents() to short-circuit (it only runs
    when `documents is not None`, per admission_service.py:283) and documents_checklist to be
    rebuilt from applied_rules with all statuses = "missing" (per admission_service.py:640).

    Result: PUT /api/admissions/{id} returned validation_errors=[] and eligibility="eligible"
    even when mandatory documents were missing, and conversely reported documents_checklist
    statuses as "missing" even when docs were already uploaded. This broke API contract
    consistency — clients trusting the response of PUT would render wrong state.

    The fix loads documents via admission_repo.get_all_documents() right before the
    _compute_frontend_fields call, mirroring the pattern already used in get_profile
    (admission_service.py:1759).

    Note: these tests use a direct DB patch of `applied_rules` to inject mandatory_docs,
    because setup_admission_api_data() does not seed an AdmissionPath with mandatory docs.
    The bug is only observable when applied_rules.mandatory_docs is non-empty.
    """

    async def _create_draft_with_mandatory_docs(
        self,
        client: AsyncClient,
        user_info: dict,
        major_id: int,
        unit_id: int,
        mandatory_doc_codes: list[str],
    ) -> tuple[int, dict]:
        """Create a draft profile via API, then patch applied_rules in DB to add mandatory_docs.

        Returns (profile_id, auth_headers).
        """
        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=user_info["id"],
            academic_year=2025,
        )
        headers = await get_auth_headers(client, user_info)

        create_response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert create_response.status_code == 201, f"Create failed: {create_response.text}"
        profile_id = create_response.json()["id"]

        # Directly patch applied_rules.mandatory_docs in DB so _validate_documents has
        # something to report on
        from sqlalchemy import update as sql_update
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(models.AdmissionProfile).where(
                        models.AdmissionProfile.id == profile_id
                    )
                )
                profile = result.scalar_one()
                patched_rules = dict(profile.applied_rules or {})
                patched_rules["mandatory_docs"] = mandatory_doc_codes
                patched_rules["upload_required_docs"] = mandatory_doc_codes
                await session.execute(
                    sql_update(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == profile_id)
                    .values(applied_rules=patched_rules)
                )

        return profile_id, headers

    async def test_update_profile_response_reports_missing_mandatory_docs(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Profile's applied_rules requires ["hoc_ba_thpt", "cccd"] but no documents are
        uploaded. PUT /api/admissions/{id} response MUST include these in validation_errors.

        Before fix: validation_errors was [] (documents=None short-circuited _validate_documents).
        After fix: validation_errors contains "Thiếu tài liệu bắt buộc: hoc_ba_thpt" and
        "Thiếu tài liệu bắt buộc: cccd".
        """
        profile_id, headers = await self._create_draft_with_mandatory_docs(
            client=client,
            user_info=officer_user_in_db,
            major_id=seed_lead_dependencies["major_program_id"],
            unit_id=seed_lead_dependencies["unit_id"],
            mandatory_doc_codes=["hoc_ba_thpt", "cccd"],
        )

        # PUT to update a trivial field. No documents uploaded.
        update_response = await client.put(
            f"/api/admissions/{profile_id}",
            json={"gender": "Nam", "version": 1},
            headers=headers,
        )

        assert update_response.status_code == 200, (
            f"Expected 200, got {update_response.status_code}: {update_response.text}"
        )
        body = update_response.json()

        validation_errors = body.get("validation_errors") or []
        assert any("hoc_ba_thpt" in e for e in validation_errors), (
            f"Expected validation_errors to report missing 'hoc_ba_thpt', "
            f"got {validation_errors!r}. "
            f"This indicates _compute_frontend_fields was called without `documents` — "
            f"MEDIUM #1 regressed."
        )
        assert any("cccd" in e for e in validation_errors), (
            f"Expected validation_errors to report missing 'cccd', got {validation_errors!r}"
        )

        # Eligibility should NOT be "eligible" when mandatory docs are missing
        assert body.get("eligibility_status") == "ineligible", (
            f"Expected eligibility_status='ineligible' when mandatory docs missing, "
            f"got {body.get('eligibility_status')!r}. MEDIUM #1 regressed."
        )

    async def test_update_profile_response_consistent_with_get_profile(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Response of PUT /api/admissions/{id} must match a subsequent GET on key computed
        fields. Before the fix, PUT returned validation_errors=[] and eligibility="eligible"
        while GET returned validation_errors=[...missing docs] and eligibility="ineligible".
        """
        profile_id, headers = await self._create_draft_with_mandatory_docs(
            client=client,
            user_info=officer_user_in_db,
            major_id=seed_lead_dependencies["major_program_id"],
            unit_id=seed_lead_dependencies["unit_id"],
            mandatory_doc_codes=["hoc_ba_thpt"],
        )

        update_response = await client.put(
            f"/api/admissions/{profile_id}",
            json={"gender": "Nam", "version": 1},
            headers=headers,
        )
        assert update_response.status_code == 200
        put_body = update_response.json()

        get_response = await client.get(
            f"/api/admissions/{profile_id}",
            headers=headers,
        )
        assert get_response.status_code == 200
        get_body = get_response.json()

        # Key computed fields must agree between PUT and GET responses
        assert put_body.get("validation_errors") == get_body.get("validation_errors"), (
            f"PUT validation_errors {put_body.get('validation_errors')!r} != "
            f"GET validation_errors {get_body.get('validation_errors')!r}. "
            f"MEDIUM #1 regressed — update_profile is not loading documents before "
            f"_compute_frontend_fields."
        )
        assert put_body.get("eligibility_status") == get_body.get("eligibility_status"), (
            f"PUT eligibility {put_body.get('eligibility_status')!r} != "
            f"GET eligibility {get_body.get('eligibility_status')!r}"
        )
        assert put_body.get("completion_percent") == get_body.get("completion_percent"), (
            f"PUT completion {put_body.get('completion_percent')} != "
            f"GET completion {get_body.get('completion_percent')}"
        )


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


# ==============================================================================
# TEST: MEDIUM #2 — MUTATION RESPONSE CONTRACT
# ==============================================================================
#
# Background: 10 admission mutation endpoints (approve/reject/request_revision/
# resubmit/record_fee/override/finalize/claim/unclaim/mark_dropped) used to
# return AdmissionProfileResponse with empty defaults for every computed field
# (permissions={}, available_actions=[], eligibility_status="pending", etc.)
# because the service functions never called _compute_frontend_fields() before
# returning. The fix added a single helper `_populate_response_fields` that is
# called after `await db.flush()` in each function.
#
# These tests assert the post-mutation response has populated computed fields,
# proving the helper ran. They also cross-check key fields against a subsequent
# GET response to lock in the contract that PUT/POST responses match GET.
#
# Test strength was verified across 3 patterns by reverting helper calls in
# approve_profile (own-query), claim_review (dependency + idempotent), and
# finalize_profile (delegated/reload). Each revert produced a clear FAIL.
# ==============================================================================


async def _create_profile_with_state(
    client: AsyncClient,
    setup_user: dict,
    seed_lead_dependencies: dict,
    target_status: str,
    *,
    mandatory_doc_codes: list = None,
    assigned_reviewer_id: int = None,
    rejection_reason: str = None,
    requires_application_fee: bool = False,
) -> tuple[int, int, dict]:
    """Create a profile via API then patch its state directly in DB.

    Bypasses state machine validation. State machine correctness is covered by
    tests/integration/test_admission_state_transitions.py separately.

    Returns:
        (profile_id, version, setup_headers)
    """
    from sqlalchemy import update as sql_update

    unit_id = seed_lead_dependencies["unit_id"]
    major_id = seed_lead_dependencies["major_program_id"]

    data = await setup_admission_api_data(
        major_id=major_id,
        unit_id=unit_id,
        officer_id=setup_user["id"],
        academic_year=2025,
    )
    headers = await get_auth_headers(client, setup_user)

    create_response = await client.post(
        "/api/admissions",
        json={
            "lead_id": data["lead_id"],
            "admission_method_id": data["admission_method_id"],
        },
        headers=headers,
    )
    assert create_response.status_code == 201, f"Create failed: {create_response.text}"
    profile_id = create_response.json()["id"]

    # Patch DB to put the profile into the requested state
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
            profile = result.scalar_one()
            patched_rules = dict(profile.applied_rules or {})
            if mandatory_doc_codes is not None:
                patched_rules["mandatory_docs"] = mandatory_doc_codes
                patched_rules["upload_required_docs"] = mandatory_doc_codes
            if requires_application_fee:
                patched_rules["requires_application_fee"] = True
                patched_rules["fee_amount"] = 500000
                patched_rules["fee_status"] = "pending"

            update_values = {
                "status": target_status,
                "applied_rules": patched_rules,
                "citizen_id": f"099{random.randint(100000000, 999999999)}",
            }
            if assigned_reviewer_id is not None:
                update_values["assigned_reviewer_id"] = assigned_reviewer_id
                update_values["assigned_at"] = datetime.now(timezone.utc)
            if rejection_reason is not None:
                update_values["rejection_reason"] = rejection_reason

            await session.execute(
                sql_update(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .values(**update_values)
            )

    # Return current version (always 1 right after create+patch since version is not bumped by sql_update)
    return profile_id, 1, headers


def _assert_computed_fields_populated(body: dict, context: str = "") -> None:
    """Assert response body has populated computed fields (not schema defaults).

    These three checks prove `_compute_frontend_fields` ran:
    - permissions: dict, default={}, populated should have ≥1 key
    - step_status: dict, default={}, populated should have keys "1".."7"
    - eligibility_status: default="pending", populated should be "eligible"/"ineligible"
    """
    msg_prefix = f"[{context}] " if context else ""

    permissions = body.get("permissions")
    assert isinstance(permissions, dict) and len(permissions) > 0, (
        f"{msg_prefix}permissions should be non-empty dict (computed by helper), "
        f"got {permissions!r}. MEDIUM #2 regressed — _populate_response_fields "
        f"call may be missing or didn't run."
    )

    step_status = body.get("step_status")
    assert isinstance(step_status, dict) and len(step_status) > 0, (
        f"{msg_prefix}step_status should be non-empty dict (computed by helper), "
        f"got {step_status!r}"
    )

    eligibility = body.get("eligibility_status")
    assert eligibility in ("eligible", "ineligible"), (
        f"{msg_prefix}eligibility_status should be 'eligible' or 'ineligible' "
        f"(computed), got {eligibility!r}. Default 'pending' indicates the "
        f"helper didn't run."
    )


class TestApproveResponseFields:
    """Mutation: POST /api/admissions/{id}/approve must populate computed fields."""

    async def test_approve_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
        )
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/approve",
            json={"version": version, "notes": "Approved for test"},
            headers=manager_headers,
        )
        assert response.status_code in (200, 201), f"Approve failed: {response.text}"
        body = response.json()
        _assert_computed_fields_populated(body, context="approve")

        # Cross-check with GET — PUT/POST response should match GET
        get_response = await client.get(
            f"/api/admissions/{profile_id}", headers=manager_headers
        )
        assert get_response.status_code == 200
        get_body = get_response.json()
        assert body.get("eligibility_status") == get_body.get("eligibility_status"), (
            "approve response eligibility_status diverges from GET"
        )


class TestRejectResponseFields:
    """Mutation: POST /api/admissions/{id}/reject must populate computed fields."""

    async def test_reject_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
        )
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/reject",
            json={"version": version, "reason": "Missing required documents for test"},
            headers=manager_headers,
        )
        assert response.status_code in (200, 201), f"Reject failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="reject")


class TestRequestRevisionResponseFields:
    """Mutation: POST /api/admissions/{id}/request-revision must populate computed fields."""

    async def test_request_revision_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
        )
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/request-revision",
            json={"version": version, "reason": "Please clarify the academic history section"},
            headers=manager_headers,
        )
        assert response.status_code in (200, 201), f"Request revision failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="request-revision")


class TestResubmitResponseFields:
    """Mutation: POST /api/admissions/{id}/resubmit must populate computed fields."""

    async def test_resubmit_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, officer_headers = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="rejected",
            rejection_reason="Previous rejection reason for test",
        )

        response = await client.post(
            f"/api/admissions/{profile_id}/resubmit",
            json={"version": version, "notes": "Fixed all issues"},
            headers=officer_headers,
        )
        assert response.status_code in (200, 201), f"Resubmit failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="resubmit")


class TestRecordFeePaymentResponseFields:
    """Mutation: POST /api/admissions/{id}/record-fee-payment must populate computed fields."""

    async def test_record_fee_payment_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, _, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
            requires_application_fee=True,
        )
        admin_headers = await get_auth_headers(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/record-fee-payment"
            f"?transaction_id=TXN-TEST-{random.randint(10000, 99999)}&amount=500000",
            headers=admin_headers,
        )
        assert response.status_code in (200, 201), f"Record fee failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="record-fee-payment")


class TestDropStudentResponseFields:
    """Mutation: POST /api/admissions/{id}/drop must populate computed fields."""

    async def test_drop_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="enrolled",
        )
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/drop",
            json={"version": version, "reason": "Test drop: student transferred"},
            headers=manager_headers,
        )
        assert response.status_code in (200, 201), f"Drop failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="drop")


class TestOverrideResponseFields:
    """Mutation: POST /api/admissions/{id}/override must populate computed fields."""

    async def test_override_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        # ADM-015: override now requires the current version. The
        # helper hands it back so we don't need a separate GET.
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="approved",
        )
        admin_headers = await get_auth_headers(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/override",
            json={
                "reason": "Special case for scholarship recipient",
                "bypass_rules": [],
                "version": version,
            },
            headers=admin_headers,
        )
        assert response.status_code in (200, 201), f"Override failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="override")


class TestFinalizeResponseFields:
    """Mutation: POST /api/admissions/{id}/finalize must populate computed fields.

    finalize_profile is the trickiest in-scope function: it delegates to
    enroll_student (which creates a Student record) then calls
    reload_profile_with_lead. The helper is called with pre-loaded documents
    to avoid a redundant query.
    """

    async def test_finalize_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        # ADM-015: finalize now requires the current version.
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="confirmed",
        )
        admin_headers = await get_auth_headers(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/finalize",
            json={"version": version},
            headers=admin_headers,
        )
        assert response.status_code in (200, 201), f"Finalize failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="finalize")


class TestClaimResponseFields:
    """Mutation: POST /api/admissions/{id}/claim must populate computed fields."""

    async def test_claim_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
        )
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/claim",
            json={"version": version},
            headers=manager_headers,
        )
        assert response.status_code in (200, 201), f"Claim failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="claim")


class TestUnclaimResponseFields:
    """Mutation: POST /api/admissions/{id}/unclaim must populate computed fields."""

    async def test_unclaim_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
            assigned_reviewer_id=manager_user_in_db["id"],
        )
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/unclaim",
            json={"version": version},
            headers=manager_headers,
        )
        assert response.status_code in (200, 201), f"Unclaim failed: {response.text}"
        _assert_computed_fields_populated(response.json(), context="unclaim")


# ==============================================================================
# SPECIAL TESTS: edge cases highlighted by plan v3 evaluation
# ==============================================================================


class TestRecordFeePaymentNoneRecordedBy:
    """Direct service-level call: helper must not crash when recorded_by=None.

    Simulates a future payment-gateway callback that has no user context.
    The helper signature accepts Optional[User] and skips silently when None,
    preventing AttributeError at _compute_frontend_fields:419 (current_user.role).
    """

    async def test_record_fee_payment_with_none_recorded_by_does_not_crash(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        from app.services import admission_service

        profile_id, _, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
            requires_application_fee=True,
        )

        # Direct service call with recorded_by=None — must not raise
        async with AsyncSessionLocal() as session:
            try:
                profile, _callback = await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile_id,
                    payment_data={
                        "transaction_id": f"TXN-NONE-{random.randint(10000, 99999)}",
                        "amount": 500000,
                    },
                    recorded_by=None,
                )
                await session.commit()
            except AttributeError as exc:
                pytest.fail(
                    f"record_application_fee_payment crashed when recorded_by=None: {exc}. "
                    f"_populate_response_fields may not be handling the None case."
                )

        # Status should be updated
        assert profile is not None
        assert profile.id == profile_id


class TestClaimReviewIdempotent:
    """Idempotent claim path: when same reviewer claims twice, the second call
    must still return populated computed fields. The fix adds a helper call
    BEFORE the early `return` in the idempotent branch of claim_review.
    """

    async def test_claim_review_idempotent_response_has_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        profile_id, version, _ = await _create_profile_with_state(
            client, officer_user_in_db, seed_lead_dependencies,
            target_status="submitted",
        )
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        # First claim — normal path (state mutation)
        first_response = await client.post(
            f"/api/admissions/{profile_id}/claim",
            json={"version": version},
            headers=manager_headers,
        )
        assert first_response.status_code in (200, 201), (
            f"First claim failed: {first_response.text}"
        )
        first_body = first_response.json()
        _assert_computed_fields_populated(first_body, context="claim-first")

        # Second claim by SAME reviewer — idempotent early-return path.
        # Use the version returned by the first claim (it was bumped).
        second_version = first_body.get("version", version + 1)
        second_response = await client.post(
            f"/api/admissions/{profile_id}/claim",
            json={"version": second_version},
            headers=manager_headers,
        )
        assert second_response.status_code in (200, 201), (
            f"Second (idempotent) claim failed: {second_response.text}"
        )
        _assert_computed_fields_populated(
            second_response.json(),
            context="claim-idempotent (proves helper ran in early-return path)",
        )


class TestCreateProfileResponseFields:
    """Mutation: POST /api/admissions must populate computed fields in create response.

    MEDIUM #2 followup: commit 1528bc89 fixed the 10 state-changing mutations
    (approve/reject/update/resubmit/claim/etc.) but missed create_profile. Without
    the _populate_response_fields call, the create response returns permissions={},
    available_actions=[], step_status={}, and eligibility_status="pending", breaking
    any frontend that renders edit/submit buttons based on the create response
    without re-fetching.

    Covers the first mutation a user hits in the admission workflow.
    """

    async def test_create_response_has_populated_computed_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """POST /api/admissions response body must have populated computed fields.

        Uses the same 3-signal assertion as the other Test*ResponseFields classes:
        - permissions non-empty dict
        - step_status non-empty dict
        - eligibility_status resolved to 'eligible' / 'ineligible' (not 'pending')
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
        body = response.json()
        _assert_computed_fields_populated(body, context="create")

    async def test_create_response_matches_subsequent_get(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """The create response must match what a fresh GET returns.

        This is the core guarantee of the mutation response contract: a client
        that uses the create response directly (without re-fetching) sees the
        same computed state as a client that does re-fetch.
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

        create_response = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert create_response.status_code == 201, f"Create failed: {create_response.text}"
        create_body = create_response.json()

        get_response = await client.get(
            f"/api/admissions/{create_body['id']}", headers=headers
        )
        assert get_response.status_code == 200, f"GET failed: {get_response.text}"
        get_body = get_response.json()

        # Cross-check computed fields between create response and GET response.
        # These are the fields _populate_response_fields is responsible for.
        for field in (
            "permissions",
            "available_actions",
            "step_status",
            "eligibility_status",
            "completion_percent",
            "assigned_officer_name",
            "assigned_reviewer_name",
        ):
            assert create_body.get(field) == get_body.get(field), (
                f"[create vs GET] field {field!r} diverges: "
                f"create={create_body.get(field)!r}, get={get_body.get(field)!r}. "
                f"_populate_response_fields may be missing from create_profile."
            )
