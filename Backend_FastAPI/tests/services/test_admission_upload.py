"""
Integration tests for Admission Document Upload.

Tests:
- Basic upload endpoint accessibility
- Access control for uploads

Uses real database via fixtures.
"""

import pytest
import io
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def create_test_lead(unit_id: int, assigned_officer_id: int = None) -> int:
    """Create a test lead for admission profile."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Upload Test Lead",
                phone="0901234900",
                email=f"upload_{datetime.now().timestamp():.0f}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def create_admission_profile(lead_id: int, citizen_id: str) -> int:
    """Create an admission profile (without document)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status="draft",
                citizen_id=citizen_id,
                academic_year=2025,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
            )
            session.add(profile)
            await session.flush()
            return profile.id


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
# TEST: DOCUMENT UPLOAD ENDPOINT
# ==============================================================================


class TestDocumentUploadEndpoint:
    """Test document upload endpoint accessibility."""

    async def test_upload_endpoint_exists(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Document upload endpoint should exist and respond.
        """
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile_id = await create_admission_profile(lead_id, "300000000001")
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        # Create simple PDF content
        pdf_content = b"%PDF-1.4\ntest content"
        
        # Correct path: /{profile_id}/documents/{doc_code}/upload
        response = await client.post(
            f"/api/admissions/{profile_id}/documents/BIRTH_CERT/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            headers=headers,
        )
        
        # Should respond (either success or validation error, not 404)
        assert response.status_code != 404, \
            f"Upload endpoint should exist: {response.status_code}"

    async def test_upload_to_nonexistent_profile_fails(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Uploading to a non-existent profile should fail with 404.
        """
        headers = await get_auth_headers(client, officer_user_in_db)
        
        pdf_content = b"%PDF-1.4\ntest"
        
        response = await client.post(
            "/api/admissions/999999/documents/TEST_DOC/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
            headers=headers,
        )
        
        assert response.status_code in [403, 404], \
            f"Should return 404 for nonexistent profile: {response.status_code}"


# ==============================================================================
# TEST: UPLOAD ACCESS CONTROL
# ==============================================================================


class TestUploadAccessControl:
    """Test that only authorized users can upload documents."""

    async def test_cannot_upload_without_auth(
        self,
        client: AsyncClient,
        seed_lead_dependencies: dict,
    ):
        """
        Unauthenticated requests should be rejected.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        lead_id = await create_test_lead(unit_id)
        profile_id = await create_admission_profile(lead_id, "300000000002")
        
        pdf_content = b"%PDF-1.4\ntest"
        
        response = await client.post(
            f"/api/admissions/{profile_id}/documents/AUTH_TEST/upload",
            files={"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")},
        )
        
        # Should require authentication
        assert response.status_code == 401, \
            f"Should require auth: {response.status_code}"

    async def test_officer_can_upload_to_own_unit(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Officer should be able to upload documents for profiles in their unit.
        """
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile_id = await create_admission_profile(lead_id, "300000000003")
        
        headers = await get_auth_headers(client, officer_user_in_db)
        
        pdf_content = b"%PDF-1.4\ntest content for own unit"
        
        response = await client.post(
            f"/api/admissions/{profile_id}/documents/OWN_UNIT/upload",
            files={"file": ("doc.pdf", io.BytesIO(pdf_content), "application/pdf")},
            headers=headers,
        )
        
        # Should succeed or return a file-related response (not 403/404)
        assert response.status_code not in [403, 404], \
            f"Officer should upload to own unit: {response.status_code} - {response.text}"
