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
    import random
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Calculation Test Lead",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"calc_{datetime.now().timestamp():.0f}@test.com",
                source="website",
                unit_id=unit_id,
                offering_id=offering_id,
                assigned_officer_id=assigned_officer_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def create_submittable_profile(
    lead_id: int,
    citizen_id: str = None,
    min_gpa: float = 0,
    mandatory_docs: list = None,
    academic_year: int = 2025,
) -> models.AdmissionProfile:
    """Create a profile that can be submitted (with subject scores, family_info, etc.).

    #337: hồ sơ phải có chuỗi config hợp lệ thì ``submit_and_evaluate`` mới suy
    ra được bậc đào tạo. Đường legacy (``uses_choice_engine=False``) đọc
    ``offering_admission_config_id`` → academic_info → offering →
    ``MajorProgram.degree_level_id``; thiếu nó thì submit fail-closed với
    ``CONFIG_GAP_TARGET_LEVEL``. Bản trước dựng hồ sơ trần nên cả 4 ca trong
    tệp này nhận 400 — cổng sản phẩm chặn ĐÚNG, chỉ fixture là lạc hậu.

    Dùng builder dùng chung thay vì tự dựng chuỗi: đây là cùng một công thức
    ``tests/services/test_admission_workflow.py`` đã chuyển sang, nên hai tệp
    không trôi khỏi nhau lần nữa.
    """
    if citizen_id is None:
        citizen_id = f"0{datetime.now().timestamp():.0f}"[:12]

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
                # Lấy TỪ seed: `OfferingAcademicInfo` mang cùng năm, lệch năm là
                # vi phạm UNIQUE(lead_id/citizen_id, academic_year) một cách âm thầm.
                academic_year=seed["academic_year"],
                version=1,
                applied_rules={
                    "min_gpa": min_gpa,
                    "mandatory_docs": mandatory_docs or [],
                    "allowed_subject_codes": ["TOAN"],
                    "scoring_method": "sum",
                    "required_subject_count": 1,
                    "subject_selection_mode": "fixed",
                },
                family_info=[{"relationship": "Cha", "full_name": "Test Father", "phone": "0901234567"}],
                # `academic_history` do builder cấp — mục THPT của nó có
                # `school_id` để engine giải được KV. ĐO ĐƯỢC khi bỏ nó ra:
                # submit vẫn trả 200 nhưng hồ sơ ĐỨNG NGUYÊN `draft`, và chỉ
                # `test_submit_with_zero_min_gpa_always_passes` bắt được vì nó
                # là ca DUY NHẤT khẳng định trạng thái sau submit. Ba ca còn
                # lại chỉ kiểm mã 200 nên xanh trên một hồ sơ không hề tiến —
                # nợ đã ghi trong thông điệp commit, không nới ở đây.
                **submittable_profile_fields(seed),
            )
            session.add(profile)
            await session.flush()

            # Add passing subject score
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

    client.cookies.delete("access_token")
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

        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_submittable_profile(
            lead_id=lead_id,
            min_gpa=0,
            mandatory_docs=[],
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )

        assert response.status_code == 200, f"Submit failed: {response.text}"
        data = response.json()
        assert data["status"] in ["submitted", "approved"], \
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

        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_submittable_profile(
            lead_id=lead_id,
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

        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_submittable_profile(
            lead_id=lead_id,
            min_gpa=0,
            mandatory_docs=[],
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

        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_submittable_profile(
            lead_id=lead_id,
            min_gpa=0,
            mandatory_docs=[],
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )

        assert response.status_code == 200, f"Submit failed: {response.text}"
        assert "status" in response.json()
