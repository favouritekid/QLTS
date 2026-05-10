
import random
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import lead_service

pytestmark = pytest.mark.asyncio


async def get_auth_headers(client, user_info: dict) -> dict:
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post("/api/auth/login", data=login_data)
    assert res.status_code == 200, f"Login failed: {res.text}"
    access_token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {access_token}"}


async def setup_admission_api_data(major_id, unit_id, officer_id, academic_year=2026):
    """Set up full chain for admission profile creation via API."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            offering_type_config = models.ConfigOfferingType(
                code=f"sync_type_{random.randint(10000, 99999)}",
                name="Sync Test Offering Type",
                is_active=True,
            )
            session.add(offering_type_config)
            await session.flush()

            offering = models.ProgramOffering(
                offering_type=f"SyncTest_{random.randint(10000, 99999)}",
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
                code=f"sync_method_{random.randint(10000, 99999)}",
                name="Sync Test Method",
                is_active=True,
            )
            session.add(method)
            await session.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"sync_criteria_{random.randint(10000, 99999)}",
                name="Sync Test Criteria",
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
                full_name="Sync Test Lead",
                phone="0900000001",
                email="sync_test@example.com",
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
                notes="Sync test",
                officer_id=officer_id,
                consultation_status_id="sts06",
            )
            session.add(consultation)
            await session.flush()

    return {
        "lead_id": lead.id,
        "admission_method_id": method.id,
    }


class TestDataSyncGap:
    """
    Verify GAP #2: Data sync issues between Lead and Admission Profile.
    Reference: Backend_FastAPI/docs/LEAD_ADMISSION_AUDIT_REPORT.md
    """

    async def test_lead_update_does_not_sync_to_profile(
        self,
        client,
        officer_user_in_db,
        seed_lead_dependencies,
    ):
        """
        Scenario:
        1. Create Lead with Phone A.
        2. Create Admission Profile -> Copies Phone A.
        3. Update Lead to Phone B.
        4. Verify Admission Profile still has Phone A (Stale Data).
        """
        unit_id = seed_lead_dependencies["unit_id"]
        major_id = seed_lead_dependencies["major_program_id"]

        data = await setup_admission_api_data(
            major_id=major_id,
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
        )

        # 3. Create Admission Profile
        headers = await get_auth_headers(client, officer_user_in_db)
        create_res = await client.post(
            "/api/admissions",
            json={
                "lead_id": data["lead_id"],
                "admission_method_id": data["admission_method_id"],
            },
            headers=headers,
        )
        assert create_res.status_code == 201, f"Create failed: {create_res.text}"
        profile_id = create_res.json()["id"]

        # Verify initial sync (copy)
        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            assert profile.phone == "0900000001"
            assert profile.email == "sync_test@example.com"

        # 4. Update Lead Phone (Phone A -> Phone B)
        async with AsyncSessionLocal() as session:
            user = await session.get(models.User, officer_user_in_db["id"])

            from app.schemas.lead import LeadUpdate
            update_data = LeadUpdate(phone="0909999999", email="updated@example.com", version=1)

            await lead_service.update_lead(session, data["lead_id"], update_data, user)
            await session.commit()

        # 5. Verify Admission Profile is STALE
        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            lead = await session.get(models.Lead, data["lead_id"])

            # Lead is updated
            assert lead.phone == "0909999999"
            assert lead.email == "updated@example.com"

            # Profile is STALE (This is the GAP)
            assert profile.phone == "0900000001", "Gap verified: Profile phone should still be old value"
            assert profile.email == "sync_test@example.com", "Gap verified: Profile email should still be old value"

            print(f"\n[VERIFIED] Gap #2 Confirmed: Lead({lead.phone}) != Profile({profile.phone})")
