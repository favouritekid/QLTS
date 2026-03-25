# tests/api/test_notification_deliveries.py
"""
Phase B12: API tests for notification delivery ops endpoints.

Tests:
  GET /api/notification-deliveries       — list with filters
  GET /api/notification-deliveries/{id}  — single record
"""
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)

DELIVERIES_URL = "/api/notification-deliveries"


# ============================================
# FIXTURES
# ============================================

@pytest_asyncio.fixture
async def seeded_deliveries(client, admin_user_in_db):
    """
    Seed delivery records for API tests.

    Depends on `client` to ensure lifespan + casbin are initialized.
    Depends on `admin_user_in_db` for a valid user_id FK reference.
    Uses a separate session to insert data directly.
    """
    user_id = admin_user_in_db["id"]
    async with AsyncSessionLocal() as db:
        d1 = models.NotificationDelivery(
            event="lead_assigned",
            channel="browser",
            recipient_kind="internal",
            user_id=user_id,
            source_type="lead",
            source_id=1,
            status="sent",
        )
        d2 = models.NotificationDelivery(
            event="lead_assigned",
            channel="email",
            recipient_kind="internal",
            user_id=user_id,
            source_type="lead",
            source_id=1,
            status="failed",
            error_reason="SMTP timeout",
        )
        d3 = models.NotificationDelivery(
            event="profile_submitted",
            channel="browser",
            recipient_kind="internal",
            user_id=user_id,
            status="queued",
        )
        db.add_all([d1, d2, d3])
        await db.commit()
        await db.refresh(d1)
        await db.refresh(d2)
        await db.refresh(d3)
        return {"d1": d1.id, "d2": d2.id, "d3": d3.id}


# ============================================
# LIST DELIVERIES
# ============================================

@pytest.mark.asyncio
async def test_list_deliveries_admin_success(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_deliveries: dict,
):
    """Admin can list all delivery records."""
    response = await client.get(DELIVERIES_URL, headers=admin_token_headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_count" in data
    assert "deliveries" in data
    # At least our 3 seeded + possible login notification deliveries
    assert data["total_count"] >= 3


@pytest.mark.asyncio
async def test_list_deliveries_filter_by_channel(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_deliveries: dict,
):
    """Filter deliveries by channel."""
    response = await client.get(
        DELIVERIES_URL,
        headers=admin_token_headers,
        params={"channel": "email"},
    )
    assert response.status_code == 200
    data = response.json()
    for d in data["deliveries"]:
        assert d["channel"] == "email"


@pytest.mark.asyncio
async def test_list_deliveries_filter_by_status(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_deliveries: dict,
):
    """Filter deliveries by status."""
    response = await client.get(
        DELIVERIES_URL,
        headers=admin_token_headers,
        params={"status": "failed"},
    )
    assert response.status_code == 200
    data = response.json()
    for d in data["deliveries"]:
        assert d["status"] == "failed"
        assert d["error_reason"] is not None


@pytest.mark.asyncio
async def test_list_deliveries_filter_by_event(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_deliveries: dict,
):
    """Filter deliveries by event."""
    response = await client.get(
        DELIVERIES_URL,
        headers=admin_token_headers,
        params={"event": "lead_assigned"},
    )
    assert response.status_code == 200
    data = response.json()
    for d in data["deliveries"]:
        assert d["event"] == "lead_assigned"


@pytest.mark.asyncio
async def test_list_deliveries_unauthenticated(
    client: AsyncClient,
    setup_test_database,
):
    """Unauthenticated request should fail."""
    response = await client.get(DELIVERIES_URL)
    assert response.status_code in (401, 403)


# ============================================
# GET SINGLE DELIVERY
# ============================================

@pytest.mark.asyncio
async def test_get_delivery_detail(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_deliveries: dict,
):
    """Admin can get a single delivery record."""
    delivery_id = seeded_deliveries["d1"]
    response = await client.get(
        f"{DELIVERIES_URL}/{delivery_id}",
        headers=admin_token_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == delivery_id
    assert data["event"] == "lead_assigned"
    assert data["channel"] == "browser"
    assert data["status"] == "sent"


@pytest.mark.asyncio
async def test_get_delivery_not_found(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """Non-existent delivery returns 404."""
    response = await client.get(
        f"{DELIVERIES_URL}/999999",
        headers=admin_token_headers,
    )
    assert response.status_code == 404
