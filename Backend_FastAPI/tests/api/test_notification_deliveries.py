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
async def seeded_deliveries(admin_token_headers, client):
    """
    Seed delivery records for API tests.

    Depends on `admin_token_headers` which guarantees:
      - setup_test_database ran (schema ready)
      - client is up (lifespan + casbin initialized)
      - admin user exists and is committed

    Uses user_id=None (nullable FK) to avoid cross-session FK timing issues.
    Delivery rows only need to exist so the API can filter/return them.
    """
    async with AsyncSessionLocal() as db:
        d1 = models.NotificationDelivery(
            event="lead_assigned",
            channel="browser",
            recipient_kind="internal",
            source_type="lead",
            source_id=1,
            status="sent",
        )
        d2 = models.NotificationDelivery(
            event="lead_assigned",
            channel="email",
            recipient_kind="internal",
            source_type="lead",
            source_id=1,
            status="failed",
            error_reason="SMTP timeout",
        )
        d3 = models.NotificationDelivery(
            event="profile_submitted",
            channel="browser",
            recipient_kind="internal",
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
async def test_list_deliveries_filter_by_zalo_bot_channel(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """
    Regression: ``channel=zalo_bot`` must be accepted by the Pydantic
    regex on the list endpoint. Pre-fix the pattern was
    ``^(browser|email|zalo|sms)$`` so the FE filter dropdown — which
    has had a "Zalo Bot" option since v5 Step 24 — produced 422 from
    the BE and operators saw an empty / errored Delivery Ops table
    even though zalo_bot rows were being written normally.

    Seed one zalo_bot delivery and assert the filter returns it (and
    only it).
    """
    async with AsyncSessionLocal() as db:
        zb = models.NotificationDelivery(
            event="lead_assigned",
            channel="zalo_bot",
            recipient_kind="internal",
            source_type="lead",
            source_id=999,
            status="sent",
        )
        db.add(zb)
        await db.commit()
        await db.refresh(zb)
        zb_id = zb.id

    response = await client.get(
        DELIVERIES_URL,
        headers=admin_token_headers,
        params={"channel": "zalo_bot"},
    )
    assert response.status_code == 200, (
        f"channel=zalo_bot must not 422 — got {response.status_code} "
        f"body={response.text[:200]}"
    )
    data = response.json()
    assert data["total_count"] >= 1
    # Filter must be exact: every row in the response is a zalo_bot row.
    assert all(d["channel"] == "zalo_bot" for d in data["deliveries"]), (
        "Filter leaked non-zalo_bot rows: "
        f"{[d['channel'] for d in data['deliveries']]}"
    )
    # Specifically the row we seeded must be present.
    returned_ids = {d["id"] for d in data["deliveries"]}
    assert zb_id in returned_ids


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
