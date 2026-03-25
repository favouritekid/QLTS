# tests/api/test_notification_consents.py
"""
Phase B12: API tests for notification consent endpoints.

Tests:
  GET  /api/notification-consents           — list with filters
  POST /api/notification-consents/upsert    — single upsert
  POST /api/notification-consents/bulk-import — CSV bulk import
"""
import io
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)

CONSENTS_URL = "/api/notification-consents"


# ============================================
# FIXTURES
# ============================================

@pytest_asyncio.fixture
async def seeded_consents(client, admin_user_in_db):
    """
    Seed consent records for API tests.

    Depends on `client` to ensure lifespan + casbin are initialized.
    """
    user_id = admin_user_in_db["id"]
    async with AsyncSessionLocal() as db:
        c1 = models.NotificationConsent(
            channel="zalo",
            source_type="lead",
            source_id=1,
            consent_status="granted",
            consent_source="manual",
            normalized_phone="84901234567",
            granted_by=user_id,
        )
        c2 = models.NotificationConsent(
            channel="email",
            source_type="lead",
            source_id=2,
            consent_status="revoked",
            consent_source="csv_import",
            normalized_email="test@example.com",
            granted_by=user_id,
        )
        db.add_all([c1, c2])
        await db.commit()
        await db.refresh(c1)
        await db.refresh(c2)
        return {"c1": c1.id, "c2": c2.id}


# ============================================
# LIST CONSENTS
# ============================================

@pytest.mark.asyncio
async def test_list_consents_admin_success(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_consents: dict,
):
    """Admin can list all consent records."""
    response = await client.get(CONSENTS_URL, headers=admin_token_headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_count" in data
    assert "consents" in data
    assert data["total_count"] >= 2


@pytest.mark.asyncio
async def test_list_consents_filter_by_channel(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_consents: dict,
):
    """Filter consents by channel."""
    response = await client.get(
        CONSENTS_URL,
        headers=admin_token_headers,
        params={"channel": "zalo"},
    )
    assert response.status_code == 200
    data = response.json()
    for c in data["consents"]:
        assert c["channel"] == "zalo"


@pytest.mark.asyncio
async def test_list_consents_filter_by_status(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_consents: dict,
):
    """Filter consents by consent_status."""
    response = await client.get(
        CONSENTS_URL,
        headers=admin_token_headers,
        params={"consent_status": "granted"},
    )
    assert response.status_code == 200
    data = response.json()
    for c in data["consents"]:
        assert c["consent_status"] == "granted"


# ============================================
# UPSERT CONSENT
# ============================================

@pytest.mark.asyncio
async def test_upsert_consent_create_new(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """Create a new consent via upsert."""
    response = await client.post(
        f"{CONSENTS_URL}/upsert",
        headers=admin_token_headers,
        json={
            "channel": "sms",
            "source_type": "lead",
            "source_id": 100,
            "consent_status": "granted",
            "normalized_phone": "84909999999",
            "consent_source": "manual",
            "notes": "Test consent",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["channel"] == "sms"
    assert data["source_type"] == "lead"
    assert data["source_id"] == 100
    assert data["consent_status"] == "granted"
    assert data["normalized_phone"] == "84909999999"


@pytest.mark.asyncio
async def test_upsert_consent_update_existing(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_consents: dict,
):
    """Upsert updates existing consent (granted -> revoked)."""
    response = await client.post(
        f"{CONSENTS_URL}/upsert",
        headers=admin_token_headers,
        json={
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 1,
            "consent_status": "revoked",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["consent_status"] == "revoked"
    assert data["revoked_at"] is not None


@pytest.mark.asyncio
async def test_upsert_consent_unauthenticated(
    client: AsyncClient,
):
    """Unauthenticated request should fail."""
    response = await client.post(
        f"{CONSENTS_URL}/upsert",
        json={
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 1,
            "consent_status": "granted",
        },
    )
    assert response.status_code in (401, 403)


# ============================================
# BULK IMPORT
# ============================================

@pytest.mark.asyncio
async def test_bulk_import_success(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """CSV bulk import creates consent records."""
    csv_content = (
        "channel,source_type,source_id,consent_status,normalized_phone\n"
        "zalo,lead,10,granted,84901111111\n"
        "zalo,lead,11,granted,84902222222\n"
        "email,lead,12,revoked,\n"
    )

    response = await client.post(
        f"{CONSENTS_URL}/bulk-import",
        headers=admin_token_headers,
        files={"file": ("consents.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 3
    assert data["granted"] == 2
    assert data["revoked"] == 1
    assert data["skipped"] == 0
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_bulk_import_with_errors(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """CSV with invalid rows reports line-by-line errors."""
    csv_content = (
        "channel,source_type,source_id,consent_status\n"
        "zalo,lead,abc,granted\n"  # invalid source_id
        "zalo,lead,20,invalid_status\n"  # invalid consent_status
        "zalo,lead,21,granted\n"  # valid
    )

    response = await client.post(
        f"{CONSENTS_URL}/bulk-import",
        headers=admin_token_headers,
        files={"file": ("consents.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 1  # only the valid row
    assert data["skipped"] >= 2
    assert len(data["errors"]) >= 2


@pytest.mark.asyncio
async def test_bulk_import_missing_columns(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """CSV missing required columns returns error."""
    csv_content = "channel,source_type\nzalo,lead\n"

    response = await client.post(
        f"{CONSENTS_URL}/bulk-import",
        headers=admin_token_headers,
        files={"file": ("consents.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 0
    assert len(data["errors"]) > 0
    assert "Missing required columns" in data["errors"][0]["message"]
