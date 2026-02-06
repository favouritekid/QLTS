
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import lead_service, admission_service
from .test_admission_service import create_test_lead, create_program_offering, create_offering_academic_info, get_auth_headers

pytestmark = pytest.mark.asyncio

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
        
        # 1. Setup Offering
        offering_id = await create_program_offering(major_id, {"min_gpa": 6.0, "mandatory_docs": []})
        await create_offering_academic_info(offering_id, 2026)
        
        # 2. Create Lead
        async with AsyncSessionLocal() as session:
            async with session.begin():
                lead = models.Lead(
                    full_name="Sync Test Lead",
                    phone="0900000001",
                    email="sync_test@example.com",
                    source="website",
                    unit_id=unit_id,
                    offering_id=offering_id,
                )
                session.add(lead)
                await session.flush()
                lead_id = lead.id

        # 3. Create Admission Profile
        headers = await get_auth_headers(client, officer_user_in_db)
        create_res = await client.post(
            "/api/admissions",
            json={"lead_id": lead_id},
            headers=headers,
        )
        assert create_res.status_code == 201
        profile_id = create_res.json()["id"]
        
        # Verify initial sync (copy)
        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            assert profile.phone == "0900000001"
            assert profile.email == "sync_test@example.com"

        # 4. Update Lead Phone (Phone A -> Phone B)
        # We use lead_service.update_lead via API or Service. Using service to strictly test service logic.
        async with AsyncSessionLocal() as session:
            # Need a user for update context
            user = await session.get(models.User, officer_user_in_db["id"])
            
            from app.schemas.lead import LeadUpdate
            update_data = LeadUpdate(phone="0909999999", email="updated@example.com", version=1)
            
            # Call service
            await lead_service.update_lead(session, lead_id, update_data, user)
            await session.commit()

        # 5. Verify Admission Profile is STALE
        async with AsyncSessionLocal() as session:
            profile = await session.get(models.AdmissionProfile, profile_id)
            lead = await session.get(models.Lead, lead_id)
            
            # Lead is updated
            assert lead.phone == "0909999999"
            assert lead.email == "updated@example.com"
            
            # Profile is STALE (This is the GAP)
            # If this assertion PASSES, it means the bug/gap IS present.
            assert profile.phone == "0900000001", "Gap verified: Profile phone should still be old value"
            assert profile.email == "sync_test@example.com", "Gap verified: Profile email should still be old value"
            
            print(f"\n[VERIFIED] Gap #2 Confirmed: Lead({lead.phone}) != Profile({profile.phone})")
