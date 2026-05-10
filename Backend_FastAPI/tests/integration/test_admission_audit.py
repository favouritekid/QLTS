"""
Integration tests for Admission Profile Audit Trail.

Tests that audit logs are correctly created for admission profile operations:
- Create profile → action="created"
- Submit profile → action="status_changed" (draft → submitted)
- Approve profile → action="status_changed" (submitted → approved)
- Reject profile → action="status_changed" (submitted → rejected)
- Claim profile → action="claimed"
- Unclaim profile → action="unclaimed"
- Delete profile → action="deleted"

Uses real database via fixtures.
"""

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


async def seed_admission_pipeline_data():
    """Seed all pipeline stages and consultation statuses required by admission events.

    The admission service fires events (profile_created, profile_submitted, etc.)
    that sync lead pipeline status. Each event maps to a specific
    consultation_status_id + pipeline_stage_id that MUST exist in DB.
    """
    stages = [
        {"id": "stg01", "name": "Chua tu van", "order": 1001},
        {"id": "stg02", "name": "Dang tu van", "order": 1002},
        {"id": "stg03", "name": "Da nop ho so", "order": 1003},
        {"id": "stg04", "name": "Ket qua ho so", "order": 1004},
        {"id": "stg05", "name": "Xu ly hoc phi", "order": 1005},
        {"id": "stg06", "name": "Da nhap hoc", "order": 1006, "is_final_stage": True},
        {"id": "stg07", "name": "Khong di hoc", "order": 1007, "is_final_stage": True},
    ]
    statuses = [
        {"id": "sts00", "name": "Chua tiep can", "color_code": "#999999", "stage_id": "stg01"},
        {"id": "sts05", "name": "Hen lien he lai", "color_code": "#FFA500", "stage_id": "stg02"},
        {"id": "sts06", "name": "Dong y tu van", "color_code": "#00FF00", "stage_id": "stg02"},
        {"id": "sts07", "name": "Da tiep nhan ho so", "color_code": "#0088FF", "stage_id": "stg03"},
        {"id": "sts09", "name": "Du dieu kien nhap hoc", "color_code": "#00CC00", "stage_id": "stg04"},
        {"id": "sts10", "name": "Da hoan tat hoc phi", "color_code": "#008800", "stage_id": "stg05"},
        {"id": "sts11", "name": "Da nhap hoc", "color_code": "#006600", "stage_id": "stg06"},
        {"id": "sts12", "name": "Ngung theo hoc", "color_code": "#CC0000", "stage_id": "stg07"},
        {"id": "sts13", "name": "Da hoan tat le phi", "color_code": "#FFCC00", "stage_id": "stg03"},
        {"id": "sts14", "name": "Chua hoan tat hoc phi", "color_code": "#009900", "stage_id": "stg05"},
        {"id": "sts16", "name": "Ho so khong dat", "color_code": "#FF0000", "stage_id": "stg04"},
        {"id": "sts18", "name": "Da hoan hoc phi", "color_code": "#008888", "stage_id": "stg05"},
    ]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for s in stages:
                existing = (await session.execute(
                    select(models.PipelineStage).where(models.PipelineStage.id == s["id"])
                )).scalar_one_or_none()
                if not existing:
                    session.add(models.PipelineStage(**s))

            await session.flush()

            for s in statuses:
                existing = (await session.execute(
                    select(models.ConsultationStatus).where(models.ConsultationStatus.id == s["id"])
                )).scalar_one_or_none()
                if not existing:
                    session.add(models.ConsultationStatus(**s))


async def create_test_lead(
    unit_id: int,
    assigned_officer_id: int = None,
    offering_id: int = None,
) -> int:
    """Create a test lead for admission profile."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Audit Test Lead",
                phone="0901234111",
                email=f"audit_adm_{datetime.now().timestamp():.0f}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
                offering_id=offering_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def create_admission_profile(
    lead_id: int,
    status: str = "draft",
    citizen_id: str = None,
) -> models.AdmissionProfile:
    """Create an admission profile in specified state."""
    if citizen_id is None:
        citizen_id = f"0{datetime.now().timestamp():.0f}"[:12]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen_id,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
                academic_year=2025,
            )
            session.add(profile)
            await session.flush()
            profile_id = profile.id

        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one()


async def create_submittable_profile(
    lead_id: int,
    citizen_id: str = None,
) -> models.AdmissionProfile:
    """Create a profile with proper applied_rules and subject scores so it can be submitted."""
    import random
    if citizen_id is None:
        citizen_id = f"0{datetime.now().timestamp():.0f}"[:12]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Create a subject if not exists
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

    # Clear cookies to prevent session interference between different users
    client.cookies.delete("access_token")

    return {"Authorization": f"Bearer {access_token}"}


async def get_audit_logs_for_entity(entity_type: str, entity_id: int) -> list:
    """Fetch audit logs for a specific entity from the database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.EntityAuditLog)
            .where(
                models.EntityAuditLog.entity_type == entity_type,
                models.EntityAuditLog.entity_id == entity_id,
            )
            .order_by(models.EntityAuditLog.created_at.asc())
        )
        return result.scalars().all()


async def setup_admission_api_data(
    major_id: int,
    unit_id: int,
    officer_id: int,
    consultation_status_id: str,
    academic_year: int = 2025,
) -> dict:
    """Set up all data required to create an admission profile via API.

    Creates: OfferingTypeConfig, ProgramOffering, OfferingAcademicInfo,
    AdmissionMethod, AdmissionCriteria, AdmissionPath, Lead (with consultation).

    Returns dict with lead_id and admission_method_id for the API call.
    """
    import random

    # Seed pipeline data first (needed for admission events)
    await seed_admission_pipeline_data()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # 0. OfferingTypeConfig (required by service validation)
            offering_type_config = models.ConfigOfferingType(
                code=f"audit_type_{random.randint(1000, 9999)}",
                name="Audit Test Offering Type",
                is_active=True,
            )
            session.add(offering_type_config)
            await session.flush()

            # 1. ProgramOffering
            offering = models.ProgramOffering(
                offering_type=f"AuditAPI_{random.randint(1000, 9999)}",
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
                code=f"audit_method_{random.randint(1000, 9999)}",
                name="Audit Test Method",
                is_active=True,
            )
            session.add(method)
            await session.flush()

            # 4. AdmissionCriteria
            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"audit_criteria_{random.randint(1000, 9999)}",
                name="Audit Test Criteria",
                min_gpa=0,
                is_active=True,
            )
            session.add(criteria)
            await session.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                session, academic_year=academic_info.academic_year,
            )
            # 5. AdmissionPath (links academic_info + method + criteria + round)
            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                criteria_id=criteria.id,
                status="active",
            )
            session.add(path)
            await session.flush()

            # 6. Lead with offering_id
            lead = models.Lead(
                full_name="Audit API Test Lead",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"audit_api_{datetime.now().timestamp():.0f}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                offering_id=offering.id,
            )
            session.add(lead)
            await session.flush()

            # 7. Consultation with valid status (not universal)
            consultation = models.Consultation(
                lead_id=lead.id,
                consultation_date=datetime.now(timezone.utc),
                method="phone",
                notes="Audit test consultation",
                officer_id=officer_id,
                consultation_status_id=consultation_status_id,
            )
            session.add(consultation)
            await session.flush()

    return {
        "lead_id": lead.id,
        "admission_method_id": method.id,
        "offering_id": offering.id,
    }


# ==============================================================================
# TEST: CREATE PROFILE AUDIT
# ==============================================================================


class TestCreateProfileAudit:
    """Test that creating an admission profile creates an audit log."""

    async def test_create_profile_audit(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """POST /api/admissions → audit action="created"."""
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]
        status_id = seed_lead_dependencies["status_a1_id"]

        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            consultation_status_id=status_id,
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
        profile_id = response.json()["id"]

        # Check audit log
        logs = await get_audit_logs_for_entity("AdmissionProfile", profile_id)
        created_log = next((l for l in logs if l.action == "created"), None)

        assert created_log is not None, \
            f"No 'created' audit log found. Actions: {[l.action for l in logs]}"
        assert created_log.entity_type == "AdmissionProfile"
        assert created_log.entity_id == profile_id
        assert created_log.actor_user_id == officer_user_in_db["id"]
        assert created_log.source == "api"


# ==============================================================================
# TEST: SUBMIT PROFILE AUDIT
# ==============================================================================


class TestSubmitProfileAudit:
    """Test that submitting a profile creates a status_changed audit log."""

    async def test_submit_profile_audit(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """POST /api/admissions/{id}/submit → audit action="status_changed", old="draft"."""
        unit_id = seed_lead_dependencies["unit_id"]

        await seed_admission_pipeline_data()

        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_submittable_profile(lead_id)

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )
        assert response.status_code == 200, f"Submit failed: {response.text}"

        # Check audit log
        logs = await get_audit_logs_for_entity("AdmissionProfile", profile.id)
        status_log = next((l for l in logs if l.action == "status_changed"), None)

        assert status_log is not None, \
            f"No 'status_changed' audit log found after submit. Actions: {[l.action for l in logs]}"
        assert status_log.field_name == "status"
        assert status_log.old_value == "draft"
        assert status_log.new_value in ["submitted", "approved"]
        assert status_log.actor_user_id == officer_user_in_db["id"]


# ==============================================================================
# TEST: APPROVE PROFILE AUDIT
# ==============================================================================


class TestApproveProfileAudit:
    """Test that approving a profile creates a status_changed audit log."""

    async def test_approve_profile_audit(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """POST /api/admissions/{id}/approve → audit action="status_changed", new="approved"."""
        unit_id = seed_lead_dependencies["unit_id"]

        await seed_admission_pipeline_data()

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Approved for audit test", "version": profile.version},
            headers=headers,
        )
        assert response.status_code == 200, f"Approve failed: {response.text}"

        # Check audit log
        logs = await get_audit_logs_for_entity("AdmissionProfile", profile.id)
        approve_log = next(
            (l for l in logs if l.action == "status_changed" and l.new_value == "approved"),
            None,
        )

        assert approve_log is not None, \
            f"No 'status_changed -> approved' audit log found. Actions: {[(l.action, getattr(l, 'new_value', None)) for l in logs]}"
        assert approve_log.field_name == "status"
        assert approve_log.actor_user_id == manager_user_in_db["id"]


# ==============================================================================
# TEST: REJECT PROFILE AUDIT
# ==============================================================================


class TestRejectProfileAudit:
    """Test that rejecting a profile creates a status_changed audit log with reason."""

    async def test_reject_profile_audit(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """POST /api/admissions/{id}/reject → audit action="status_changed", reason populated."""
        unit_id = seed_lead_dependencies["unit_id"]
        rejection_reason = "Missing required documents for audit test"

        await seed_admission_pipeline_data()

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/reject",
            json={"reason": rejection_reason, "version": profile.version},
            headers=headers,
        )
        assert response.status_code == 200, f"Reject failed: {response.text}"

        # Check audit log
        logs = await get_audit_logs_for_entity("AdmissionProfile", profile.id)
        reject_log = next(
            (l for l in logs if l.action == "status_changed" and l.new_value == "rejected"),
            None,
        )

        assert reject_log is not None, \
            f"No 'status_changed -> rejected' audit log found. Actions: {[(l.action, getattr(l, 'new_value', None)) for l in logs]}"
        assert reject_log.field_name == "status"
        assert reject_log.reason == rejection_reason
        assert reject_log.actor_user_id == manager_user_in_db["id"]


# ==============================================================================
# TEST: CLAIM PROFILE AUDIT
# ==============================================================================


class TestClaimProfileAudit:
    """Test that claiming a profile creates a 'claimed' audit log."""

    async def test_claim_profile_audit(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """POST /api/admissions/{id}/claim → audit action="claimed", changes has reviewer_id."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=headers,
        )
        assert response.status_code == 200, f"Claim failed: {response.text}"

        # Check audit log
        logs = await get_audit_logs_for_entity("AdmissionProfile", profile.id)
        claim_log = next((l for l in logs if l.action == "claimed"), None)

        assert claim_log is not None, \
            f"No 'claimed' audit log found. Actions: {[l.action for l in logs]}"
        assert claim_log.actor_user_id == manager_user_in_db["id"]
        assert claim_log.changes is not None
        assert "assigned_reviewer_id" in claim_log.changes


# ==============================================================================
# TEST: UNCLAIM PROFILE AUDIT
# ==============================================================================


class TestUnclaimProfileAudit:
    """Test that unclaiming a profile creates an 'unclaimed' audit log."""

    async def test_unclaim_profile_audit(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """POST /api/admissions/{id}/unclaim → audit action="unclaimed"."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        # First claim
        claim_resp = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=headers,
        )
        assert claim_resp.status_code == 200
        claimed_version = claim_resp.json()["version"]

        # Then unclaim
        unclaim_resp = await client.post(
            f"/api/admissions/{profile.id}/unclaim",
            json={"version": claimed_version},
            headers=headers,
        )
        assert unclaim_resp.status_code == 200, f"Unclaim failed: {unclaim_resp.text}"

        # Check audit log
        logs = await get_audit_logs_for_entity("AdmissionProfile", profile.id)
        unclaim_log = next((l for l in logs if l.action == "unclaimed"), None)

        assert unclaim_log is not None, \
            f"No 'unclaimed' audit log found. Actions: {[l.action for l in logs]}"
        assert unclaim_log.actor_user_id == manager_user_in_db["id"]
        assert unclaim_log.changes is not None
        assert "assigned_reviewer_id" in unclaim_log.changes


# ==============================================================================
# TEST: DELETE PROFILE AUDIT
# ==============================================================================


class TestDeleteProfileAudit:
    """Test that deleting a draft profile creates a 'deleted' audit log."""

    async def test_delete_draft_profile_audit(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """DELETE /api/admissions/{id} (draft) → audit action="deleted".

        Uses admin user since officer role doesn't have DELETE permission.
        """
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="draft")

        headers = await get_auth_headers(client, admin_user_in_db)

        response = await client.delete(
            f"/api/admissions/{profile.id}",
            headers=headers,
        )
        assert response.status_code == 204, \
            f"Delete failed: {response.status_code} - {response.text}"

        # Check audit log
        logs = await get_audit_logs_for_entity("AdmissionProfile", profile.id)
        delete_log = next((l for l in logs if l.action == "deleted"), None)

        assert delete_log is not None, \
            f"No 'deleted' audit log found. Actions: {[l.action for l in logs]}"
        assert delete_log.entity_type == "AdmissionProfile"
        assert delete_log.entity_id == profile.id
        assert delete_log.actor_user_id == admin_user_in_db["id"]
