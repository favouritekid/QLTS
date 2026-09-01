# tests/api/test_notification_delivery_idor.py
"""
E2E Phase 2: IDOR scope enforcement for notification delivery ops.

Tests: admin=all, manager=unit scope, officer=self scope.
Admin-only endpoints: latency, health, quotas, breakers return 403 for non-admin.
d_other is officer's zalo delivery (not external) to avoid FK issues with non-existent user IDs.

Cookie-jar hazard (why ``idor_data`` clears cookies)
---------------------------------------------------
``get_current_user`` reads the ``access_token`` COOKIE first and only falls
back to the ``Authorization`` header (``app/core/deps.py:130-136``), while
``tests/fixtures/users.get_auth_headers`` logs in through the SHARED
``client`` and leaves the httpOnly cookie in the jar. Requesting all three
role fixtures therefore leaves the LAST login (officer) parked in the jar,
and every subsequent request — Bearer-admin included — authenticated as the
officer. That is what made ``test_admin_sees_all_deliveries`` read the
officer's 2 rows instead of all 4. The fixture drops the jar once the tokens
are minted so the Bearer header is the only identity in play.
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

    # Three logins ran while resolving the token fixtures above; the last one
    # (officer) left its httpOnly access_token in the shared jar, and the
    # cookie OUTRANKS the Authorization header in ``get_current_user``
    # (app/core/deps.py:130-136). Drop the jar so each test's Bearer token is
    # the only identity the server sees.
    client.cookies.clear()

    return {
        "admin_headers": admin_token_headers,
        "manager_headers": manager_token_headers,
        "officer_headers": officer_token_headers,
        "admin_delivery": d_admin.id,
        "manager_delivery": d_manager.id,
        "officer_delivery": d_officer.id,
        "other_delivery": d_other.id,
        "officer_id": officer_id,
        "admin_id": admin_id,
        "manager_id": manager_id,
        # Every id this fixture seeded — admin must see ALL of them.
        "all_delivery_ids": {
            d_admin.id, d_manager.id, d_officer.id, d_other.id,
        },
        # The two rows inside the officer's self-scope.
        "officer_scope_ids": {d_officer.id, d_other.id},
    }


# ============================================
# LIST SCOPING
# ============================================

@pytest.mark.asyncio
async def test_admin_sees_all_deliveries(client: AsyncClient, idor_data):
    """scope_kind='all' (app/core/deps.py:1963-1964): admin's page must
    contain EVERY seeded id, not merely 'enough' rows. Counting alone is what
    let the officer-cookie leak pass as 'admin sees 2 >= …'."""
    resp = await client.get(
        URL, params={"page_size": 200}, headers=idor_data["admin_headers"]
    )
    assert resp.status_code == 200
    body = resp.json()
    seen = {d["id"] for d in body["deliveries"]}
    missing = idor_data["all_delivery_ids"] - seen
    assert not missing, (
        f"Admin scope must return every seeded delivery; missing {sorted(missing)}. "
        f"Saw ids={sorted(seen)}, total_count={body['total_count']}"
    )
    # The two rows OUTSIDE the officer's self-scope are the ones that prove
    # this is an all-scope read and not a leaked officer identity.
    assert {idor_data["admin_delivery"], idor_data["manager_delivery"]} <= seen
    assert body["total_count"] >= len(idor_data["all_delivery_ids"])


@pytest.mark.asyncio
async def test_officer_sees_only_own(client: AsyncClient, idor_data):
    """scope_kind='self' (app/core/deps.py:1980-1984): EXACTLY the officer's
    own two rows — an empty page would satisfy a per-row loop vacuously."""
    resp = await client.get(
        URL, params={"page_size": 200}, headers=idor_data["officer_headers"]
    )
    assert resp.status_code == 200
    data = resp.json()
    seen = {d["id"] for d in data["deliveries"]}
    assert seen == idor_data["officer_scope_ids"], (
        f"Officer must see exactly their own 2 deliveries, got {sorted(seen)}"
    )
    assert data["total_count"] == len(idor_data["officer_scope_ids"])
    for d in data["deliveries"]:
        assert d["user_id"] == idor_data["officer_id"]


# ============================================
# DETAIL IDOR
# ============================================

@pytest.mark.asyncio
async def test_admin_views_any_delivery(client: AsyncClient, idor_data):
    """Admin reads a record that is NOT theirs and NOT in the officer's scope.

    ``other_delivery`` used to be the probe, but it belongs to the officer —
    with the leaked officer cookie the request passed for the wrong reason.
    ``manager_delivery`` is outside both identities, so a 200 here can only
    come from the ADMIN branch of ``get_delivery_for_user``
    (app/core/deps.py:2067-2068).
    """
    resp = await client.get(
        f"{URL}/{idor_data['manager_delivery']}", headers=idor_data["admin_headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == idor_data["manager_delivery"]
    assert body["user_id"] == idor_data["manager_id"]


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
    """Stats obey the same scope. ``<=`` was satisfied by equality — i.e. it
    stayed green while the officer cookie made BOTH calls officer-scoped. Pin
    the officer to their exact two rows and require a STRICT gap to admin."""
    resp = await client.get(f"{URL}/stats", headers=idor_data["officer_headers"])
    assert resp.status_code == 200
    officer_total = resp.json()["total"]

    admin_resp = await client.get(f"{URL}/stats", headers=idor_data["admin_headers"])
    assert admin_resp.status_code == 200
    admin_total = admin_resp.json()["total"]

    assert officer_total == len(idor_data["officer_scope_ids"]), (
        f"Officer stats must count only their own deliveries, got {officer_total}"
    )
    assert admin_total >= len(idor_data["all_delivery_ids"]), (
        f"Admin stats must count every seeded delivery, got {admin_total}"
    )
    assert officer_total < admin_total, (
        f"Officer scope must be STRICTLY narrower than admin's "
        f"({officer_total} vs {admin_total}) — equality means both calls "
        "resolved to the same identity."
    )


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
