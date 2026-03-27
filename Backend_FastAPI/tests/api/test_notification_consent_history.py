# tests/api/test_notification_consent_history.py
"""
E2E Phase 4: Consent history audit trail API tests.

Tests: empty history, grant→revoke creates 2 rows, history by consent_id,
       old/new status transitions, performed_by tracking.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal

CONSENTS_URL = "/api/notification-consents"


@pytest_asyncio.fixture
async def consent_data(admin_token_headers, client):
    """Seed consent via API for history testing."""
    headers = admin_token_headers

    # Grant consent
    resp1 = await client.post(
        f"{CONSENTS_URL}/upsert",
        headers=headers,
        json={
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 7001,
            "consent_status": "granted",
            "consent_source": "manual",
        },
    )
    assert resp1.status_code == 200, f"Grant failed: {resp1.text}"
    consent_id = resp1.json()["id"]

    # Revoke consent
    resp2 = await client.post(
        f"{CONSENTS_URL}/upsert",
        headers=headers,
        json={
            "channel": "zalo",
            "source_type": "lead",
            "source_id": 7001,
            "consent_status": "revoked",
            "consent_source": "manual",
        },
    )
    assert resp2.status_code == 200, f"Revoke failed: {resp2.text}"

    return {
        "headers": headers,
        "consent_id": consent_id,
        "source_type": "lead",
        "source_id": 7001,
    }


# ============================================
# HISTORY BY ENTITY
# ============================================

@pytest.mark.asyncio
async def test_entity_history_after_grant_revoke(client: AsyncClient, consent_data):
    """Grant→revoke should create 2 history rows."""
    resp = await client.get(
        f"{CONSENTS_URL}/history",
        headers=consent_data["headers"],
        params={
            "source_type": consent_data["source_type"],
            "source_id": consent_data["source_id"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] >= 2
    # Newest first
    history = data["history"]
    assert history[0]["new_status"] == "revoked"


@pytest.mark.asyncio
async def test_entity_history_empty(client: AsyncClient, consent_data):
    """Non-existent entity has no history."""
    resp = await client.get(
        f"{CONSENTS_URL}/history",
        headers=consent_data["headers"],
        params={"source_type": "lead", "source_id": 99999},
    )
    assert resp.status_code == 200
    assert resp.json()["total_count"] == 0


# ============================================
# HISTORY BY CONSENT ID
# ============================================

@pytest.mark.asyncio
async def test_consent_id_history(client: AsyncClient, consent_data):
    """History by consent_id returns matching rows."""
    consent_id = consent_data["consent_id"]
    resp = await client.get(
        f"{CONSENTS_URL}/{consent_id}/history",
        headers=consent_data["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] >= 2


# ============================================
# STATUS TRANSITIONS
# ============================================

@pytest.mark.asyncio
async def test_history_status_transitions(client: AsyncClient, consent_data):
    """First row: granted, second: revoked with correct old/new."""
    resp = await client.get(
        f"{CONSENTS_URL}/history",
        headers=consent_data["headers"],
        params={
            "source_type": consent_data["source_type"],
            "source_id": consent_data["source_id"],
        },
    )
    history = resp.json()["history"]
    # Newest first: revoke, then grant
    revoke_row = history[0]
    grant_row = history[1]
    assert revoke_row["action"] == "revoked"
    assert revoke_row["new_status"] == "revoked"
    assert grant_row["action"] == "granted"
    assert grant_row["new_status"] == "granted"


# ============================================
# PERFORMED BY
# ============================================

@pytest.mark.asyncio
async def test_history_performed_by(client: AsyncClient, consent_data):
    """performed_by should be set (admin user ID)."""
    resp = await client.get(
        f"{CONSENTS_URL}/history",
        headers=consent_data["headers"],
        params={
            "source_type": consent_data["source_type"],
            "source_id": consent_data["source_id"],
        },
    )
    history = resp.json()["history"]
    for row in history:
        assert row["performed_by"] is not None
