# tests/api/test_notification_delivery_idor.py
"""
E2E Phase 2: IDOR scope enforcement for notification delivery ops.

Tests: admin=all, manager=unit scope, officer=self scope.
Admin-only endpoints: latency, health, quotas, breakers return 403 for non-admin.
d_other is officer's zalo delivery (not external) to avoid FK issues with non-existent user IDs.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal

URL = "/api/notification-deliveries"


@pytest_asyncio.fixture
async def idor_data(
    admin_token_headers, manager_token_headers, officer_token_headers,
    admin_user_in_db, manager_user_in_db, officer_user_in_db,
    client, seed_lead_dependencies,
):
    """Seed deliveries with known user_ids for IDOR testing."""
    admin_id = admin_user_in_db["id"]
    manager_id = manager_user_in_db["id"]
    officer_id = officer_user_in_db["id"]

    async with AsyncSessionLocal() as db:
        d_admin = models.NotificationDelivery(
            event="system_alert", channel="browser", recipient_kind="internal",
            user_id=admin_id, status="sent",
        )
        d_manager = models.NotificationDelivery(
            event="lead_assigned", channel="browser", recipient_kind="internal",
            user_id=manager_id, status="sent",
        )
        d_officer = models.NotificationDelivery(
            event="lead_assigned", channel="email", recipient_kind="internal",
            user_id=officer_id, status="failed", error_reason="test",
        )
        d_other = models.NotificationDelivery(
            event="lead_assigned", channel="zalo", recipient_kind="internal",
            user_id=officer_id, status="queued",
        )
        db.add_all([d_admin, d_manager, d_officer, d_other])
        await db.commit()
        for d in [d_admin, d_manager, d_officer, d_other]:
            await db.refresh(d)

    return {
        "admin_headers": admin_token_headers,
        "manager_headers": manager_token_headers,
        "officer_headers": officer_token_headers,
        "admin_delivery": d_admin.id,
        "manager_delivery": d_manager.id,
        "officer_delivery": d_officer.id,
        "other_delivery": d_other.id,
        "officer_id": officer_id,
    }


# ============================================
# LIST SCOPING
# ============================================

@pytest.mark.asyncio
async def test_admin_sees_all_deliveries(client: AsyncClient, idor_data):
    resp = await client.get(URL, headers=idor_data["admin_headers"])
    assert resp.status_code == 200
    assert resp.json()["total_count"] >= 4


@pytest.mark.asyncio
async def test_officer_sees_only_own(client: AsyncClient, idor_data):
    resp = await client.get(URL, headers=idor_data["officer_headers"])
    assert resp.status_code == 200
    data = resp.json()
    for d in data["deliveries"]:
        assert d["user_id"] == idor_data["officer_id"]


# ============================================
# DETAIL IDOR
# ============================================

@pytest.mark.asyncio
async def test_admin_views_any_delivery(client: AsyncClient, idor_data):
    resp = await client.get(
        f"{URL}/{idor_data['other_delivery']}", headers=idor_data["admin_headers"]
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_officer_views_own_delivery(client: AsyncClient, idor_data):
    resp = await client.get(
        f"{URL}/{idor_data['officer_delivery']}", headers=idor_data["officer_headers"]
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_officer_cannot_view_other_returns_404(client: AsyncClient, idor_data):
    resp = await client.get(
        f"{URL}/{idor_data['admin_delivery']}", headers=idor_data["officer_headers"]
    )
    assert resp.status_code == 404  # IDOR: 404 not 403


# ============================================
# STATS SCOPING
# ============================================

@pytest.mark.asyncio
async def test_officer_stats_scoped_to_self(client: AsyncClient, idor_data):
    resp = await client.get(f"{URL}/stats", headers=idor_data["officer_headers"])
    assert resp.status_code == 200
    data = resp.json()
    # Officer should see fewer deliveries than admin
    admin_resp = await client.get(f"{URL}/stats", headers=idor_data["admin_headers"])
    assert data["total"] <= admin_resp.json()["total"]


# ============================================
# ADMIN-ONLY ENDPOINTS: OFFICER DENIED
# ============================================

@pytest.mark.asyncio
async def test_latency_officer_denied(client: AsyncClient, idor_data):
    resp = await client.get(f"{URL}/stats/latency", headers=idor_data["officer_headers"])
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_health_officer_denied(client: AsyncClient, idor_data):
    resp = await client.get(f"{URL}/health", headers=idor_data["officer_headers"])
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_quotas_officer_denied(client: AsyncClient, idor_data):
    resp = await client.get(f"{URL}/quotas", headers=idor_data["officer_headers"])
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_breakers_officer_denied(client: AsyncClient, idor_data):
    resp = await client.get(f"{URL}/circuit-breakers", headers=idor_data["officer_headers"])
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_reset_officer_denied(client: AsyncClient, idor_data):
    resp = await client.post(
        f"{URL}/circuit-breakers/email/reset", headers=idor_data["officer_headers"]
    )
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_replay_cross_user_returns_404(client: AsyncClient, idor_data):
    """Officer cannot replay another user's delivery."""
    resp = await client.post(
        f"{URL}/{idor_data['admin_delivery']}/replay",
        headers=idor_data["officer_headers"],
    )
    assert resp.status_code == 404
