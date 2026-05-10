"""
Strict backend contract compliance tests (Tickets #1-4).
Verifies that fields required by 'Thin Client' architecture are always present.
"""

import random
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.schemas.admission import DEFAULT_UPLOAD_CONFIG


pytestmark = pytest.mark.asyncio


async def get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post("/api/auth/login", data=login_data)
    assert res.status_code == 200, f"Login failed: {res.text}"
    access_token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {access_token}"}


async def setup_admission_api_data(
    major_id: int,
    unit_id: int,
    officer_id: int,
    academic_year: int = 2026,
) -> dict:
    """Set up full chain for admission profile creation via API."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            offering_type_config = models.ConfigOfferingType(
                code=f"strict_type_{random.randint(10000, 99999)}",
                name="Strict Test Offering Type",
                is_active=True,
            )
            session.add(offering_type_config)
            await session.flush()

            offering = models.ProgramOffering(
                offering_type=f"StrictTest_{random.randint(10000, 99999)}",
                program_id=major_id,
                offering_type_id=offering_type_config.id,
            )
            session.add(offering)
            await session.flush()

            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=academic_year,
                is_published=True,
            )
            session.add(academic_info)
            await session.flush()

            method = models.AdmissionMethod(
                code=f"strict_method_{random.randint(10000, 99999)}",
                name="Strict Test Method",
                is_active=True,
            )
            session.add(method)
            await session.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"strict_criteria_{random.randint(10000, 99999)}",
                name="Strict Test Criteria",
                min_gpa=0,
                is_active=True,
            )
            session.add(criteria)
            await session.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                session, academic_year=academic_info.academic_year,
            )
            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                criteria_id=criteria.id,
                status="active",
            )
            session.add(path)
            await session.flush()

            lead = models.Lead(
                full_name="Strict Test Applicant",
                phone=f"098{random.randint(1000000, 9999999)}",
                email=f"strict_{datetime.now().timestamp():.0f}@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                offering_id=offering.id,
            )
            session.add(lead)
            await session.flush()

            consultation = models.Consultation(
                lead_id=lead.id,
                consultation_date=datetime.now(timezone.utc),
                method="phone",
                notes="Strict test consultation",
                officer_id=officer_id,
                consultation_status_id="sts06",
            )
            session.add(consultation)
            await session.flush()

    return {
        "lead_id": lead.id,
        "admission_method_id": method.id,
        "offering_id": offering.id,
    }


class TestStrictAdmissionCompliance:
    """
    Test suite for strict backend contract compliance (Tickets #1-4).
    Verifies that fields required by 'Thin Client' architecture are always present.
    """

    async def test_applied_rules_has_method_type_and_upload_config(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Verify that creating a profile populates `applied_rules` with:
        - `method_type`: Derived from criteria logic (Ticket #3)
        - `upload_config`: Injected with default values (Ticket #4)
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

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
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert response.status_code == 201, f"Create failed: {response.text}"
        result = response.json()

        applied_rules = result["applied_rules"]

        # Check Ticket #3: method_type
        assert "method_type" in applied_rules
        assert applied_rules["method_type"] in ["gpa_only", "subject_based"]

        # Check Ticket #4: upload_config
        assert "upload_config" in applied_rules
        assert applied_rules["upload_config"] == DEFAULT_UPLOAD_CONFIG

        # Check doc_configs
        assert "doc_configs" in applied_rules
        assert isinstance(applied_rules["doc_configs"], dict)

    async def test_is_qualified_logic(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Verify `is_qualified` field logic (Ticket #2).
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        res_create = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert res_create.status_code == 201, f"Create failed: {res_create.text}"
        result = res_create.json()

        # Verify is_qualified field exists
        assert "is_qualified" in result
