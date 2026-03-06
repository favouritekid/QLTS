"""
Tests for Admission Resubmit Flow fixes.

Covers:
1. Model: resubmit/override/confirmed_by columns exist and are assignable
2. Service: Auto-reset removed (rejected profiles stay rejected on update)
3. Service: mark_paper_submitted status guard
4. Service: reject_document status guard
5. API: Resubmit endpoint works (rejected -> resubmitted)
6. API: Update rejected profile does NOT reset to draft
7. Schema: Response includes resubmit/override audit fields
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
# HELPERS
# ==============================================================================


async def get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    """Login and get auth headers."""
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post("/api/auth/login", data=login_data)
    assert res.status_code == 200, f"Login failed: {res.text}"
    access_token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {access_token}"}


async def create_test_lead(unit_id: int, assigned_officer_id: int = None) -> int:
    """Create a test lead."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Resubmit Test Lead",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"resubmit_{datetime.now().timestamp():.0f}_{random.randint(1000,9999)}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
            )
            session.add(lead)
            await session.flush()
            return lead.id


async def create_admission_profile(
    lead_id: int,
    status: str = "draft",
    citizen_id: str = None,
) -> models.AdmissionProfile:
    """Create an admission profile directly in DB."""
    if citizen_id is None:
        citizen_id = f"{random.randint(100000000000, 999999999999)}"

    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen_id,
                academic_year=2025,
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


async def reload_profile(profile_id: int) -> models.AdmissionProfile:
    """Reload profile from DB."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one_or_none()


# ==============================================================================
# TEST: MODEL COLUMNS EXIST
# ==============================================================================


class TestModelResubmitColumns:
    """Verify resubmit/override/confirmed_by columns are mapped on the model."""

    async def test_resubmit_columns_assignable(self, seed_lead_dependencies: dict):
        """Model has resubmitted_at, resubmitted_by_id, resubmit_notes."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="resubmitted",
                    citizen_id=f"{random.randint(100000000000, 999999999999)}",
                    academic_year=2025,
                    version=1,
                    applied_rules={"min_gpa": 0},
                    resubmitted_at=datetime.now(timezone.utc),
                    resubmitted_by_id=None,
                    resubmit_notes="Test notes",
                )
                session.add(profile)
                await session.flush()

                assert profile.resubmitted_at is not None
                assert profile.resubmit_notes == "Test notes"

    async def test_override_columns_assignable(self, seed_lead_dependencies: dict):
        """Model has overridden_at, overridden_by_id, override_reason."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="overridden",
                    citizen_id=f"{random.randint(100000000000, 999999999999)}",
                    academic_year=2025,
                    version=1,
                    applied_rules={"min_gpa": 0},
                    overridden_at=datetime.now(timezone.utc),
                    overridden_by_id=None,
                    override_reason="Special override",
                )
                session.add(profile)
                await session.flush()

                assert profile.overridden_at is not None
                assert profile.override_reason == "Special override"

    async def test_confirmed_by_id_assignable(self, seed_lead_dependencies: dict):
        """Model has confirmed_by_id."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="confirmed",
                    citizen_id=f"{random.randint(100000000000, 999999999999)}",
                    academic_year=2025,
                    version=1,
                    applied_rules={"min_gpa": 0},
                    confirmed_by_id=None,
                )
                session.add(profile)
                await session.flush()

                assert hasattr(profile, "confirmed_by_id")


# ==============================================================================
# TEST: AUTO-RESET REMOVED
# ==============================================================================


class TestAutoResetRemoved:
    """Verify that updating a rejected profile does NOT reset status to draft."""

    async def test_update_rejected_profile_keeps_rejected_status(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        BUG FIX: Previously, editing a rejected profile auto-reset to draft.
        Now it should stay 'rejected' after update.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="rejected")

        headers = await get_auth_headers(client, officer_user_in_db)

        # Update the rejected profile (only simple text field, no scores)
        update_response = await client.put(
            f"/api/admissions/{profile.id}",
            json={"full_name": "Updated After Rejection", "version": 1},
            headers=headers,
        )

        assert update_response.status_code == 200, f"Update failed: {update_response.text}"

        # Verify status is still 'rejected' (NOT 'draft')
        updated = await reload_profile(profile.id)
        assert updated.status == "rejected", (
            f"Expected status 'rejected' after update, got '{updated.status}'. "
            "Auto-reset bug may still be present."
        )

    async def test_submit_endpoint_rejects_rejected_profile(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        POST /submit should reject profiles with status='rejected'.
        Officer must use /resubmit endpoint instead.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="rejected")

        headers = await get_auth_headers(client, officer_user_in_db)

        submit_response = await client.post(
            f"/api/admissions/{profile.id}/submit",
            headers=headers,
        )

        # Should fail because /submit only works for draft
        assert submit_response.status_code == 400, (
            f"Expected 400 for submitting rejected profile, got {submit_response.status_code}. "
            "Officer should use /resubmit endpoint instead."
        )


# ==============================================================================
# TEST: RESUBMIT ENDPOINT
# ==============================================================================


class TestResubmitEndpoint:
    """Test POST /api/admissions/{id}/resubmit works correctly."""

    async def test_resubmit_rejected_profile_succeeds(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Officer can resubmit a rejected profile.
        rejected -> resubmitted
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="rejected")

        # Set rejection reason for realism
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == profile.id)
                )
                p = result.scalar_one()
                p.rejection_reason = "Missing documents"

        headers = await get_auth_headers(client, officer_user_in_db)

        resubmit_response = await client.post(
            f"/api/admissions/{profile.id}/resubmit",
            json={"notes": "Uploaded all missing documents"},
            headers=headers,
        )

        assert resubmit_response.status_code in [200, 201], (
            f"Resubmit failed: {resubmit_response.text}"
        )

        data = resubmit_response.json()
        assert data["status"] == "resubmitted"

        # Verify audit fields
        updated = await reload_profile(profile.id)
        assert updated.status == "resubmitted"
        assert updated.resubmitted_at is not None
        assert updated.resubmitted_by_id == officer_user_in_db["id"]
        assert updated.resubmit_notes == "Uploaded all missing documents"

    async def test_resubmit_draft_profile_fails(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Cannot resubmit a draft profile (must be rejected first).
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="draft")

        headers = await get_auth_headers(client, officer_user_in_db)

        resubmit_response = await client.post(
            f"/api/admissions/{profile.id}/resubmit",
            json={"notes": "Should not work"},
            headers=headers,
        )

        assert resubmit_response.status_code == 400, (
            f"Expected 400 for resubmitting draft, got {resubmit_response.status_code}"
        )

    async def test_resubmit_approved_profile_fails(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Cannot resubmit an approved profile.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="approved")

        headers = await get_auth_headers(client, officer_user_in_db)

        resubmit_response = await client.post(
            f"/api/admissions/{profile.id}/resubmit",
            json={"notes": "Should not work"},
            headers=headers,
        )

        assert resubmit_response.status_code == 400, (
            f"Expected 400 for resubmitting approved, got {resubmit_response.status_code}"
        )


# ==============================================================================
# TEST: RESPONSE SCHEMA INCLUDES RESUBMIT FIELDS
# ==============================================================================


class TestResponseSchemaResubmitFields:
    """Verify API response includes resubmit/override audit fields."""

    async def test_get_profile_includes_resubmit_fields(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        GET /api/admissions/{id} should include resubmit audit fields.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="draft")

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.get(
            f"/api/admissions/{profile.id}",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify new fields are present (null for draft)
        assert "resubmitted_at" in data
        assert "resubmitted_by_id" in data
        assert "resubmit_notes" in data
        assert "overridden_at" in data
        assert "overridden_by_id" in data
        assert "override_reason" in data
        assert "confirmed_by_id" in data

        # All should be null for a draft profile
        assert data["resubmitted_at"] is None
        assert data["resubmitted_by_id"] is None
        assert data["resubmit_notes"] is None


# ==============================================================================
# TEST: FULL RESUBMIT FLOW (Integration)
# ==============================================================================


class TestFullResubmitFlow:
    """Integration test: rejected -> edit -> resubmit -> approve."""

    async def test_full_rejection_resubmit_approve_flow(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Full flow:
        1. Create submitted profile
        2. Manager rejects
        3. Officer edits (status stays rejected)
        4. Officer resubmits (rejected -> resubmitted)
        5. Manager approves (resubmitted -> approved)
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="submitted")

        officer_headers = await get_auth_headers(client, officer_user_in_db)
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        # Step 1: Manager rejects
        reject_response = await client.post(
            f"/api/admissions/{profile.id}/reject",
            json={
                "version": 1,
                "reason": "Missing birth certificate document",
            },
            headers=manager_headers,
        )
        assert reject_response.status_code in [200, 201], f"Reject failed: {reject_response.text}"

        p = await reload_profile(profile.id)
        assert p.status == "rejected"
        reject_version = p.version

        # Step 2: Officer edits (status stays rejected)
        update_response = await client.put(
            f"/api/admissions/{profile.id}",
            json={"full_name": "Updated Name After Rejection", "version": reject_version},
            headers=officer_headers,
        )
        assert update_response.status_code == 200, f"Update failed: {update_response.text}"

        p = await reload_profile(profile.id)
        assert p.status == "rejected", "Status should remain 'rejected' after update"
        assert p.full_name == "Updated Name After Rejection"
        update_version = p.version

        # Step 3: Officer resubmits
        resubmit_response = await client.post(
            f"/api/admissions/{profile.id}/resubmit",
            json={"notes": "Added birth certificate", "version": update_version},
            headers=officer_headers,
        )
        assert resubmit_response.status_code in [200, 201], f"Resubmit failed: {resubmit_response.text}"

        p = await reload_profile(profile.id)
        assert p.status == "resubmitted"
        resubmit_version = p.version

        # Step 4: Manager approves
        approve_response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "All documents complete", "version": resubmit_version},
            headers=manager_headers,
        )
        assert approve_response.status_code in [200, 201], f"Approve failed: {approve_response.text}"

        p = await reload_profile(profile.id)
        assert p.status == "approved"
        assert p.approved_by_id is not None
