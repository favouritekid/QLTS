# tests/api/test_security_e2e.py
# -*- coding: utf-8 -*-
"""
E2E tests for Security endpoints: login history, suspicious logins,
confirm login, secure account, trusted devices.

Tests full API flows through real HTTP calls against the running app.

Run with:
    pytest tests/api/test_security_e2e.py -v
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import LoginHistory, TrustedDevice, User

try:
    from tests.fixtures.constants import (
        AuthURLs,
        SecurityURLs,
        TestUsers,
        NON_EXISTENT_ID,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================


async def _login_and_get_headers(client: AsyncClient, user_info: dict) -> dict:
    """Login a user and return auth headers."""
    res = await client.post(
        AuthURLs.LOGIN,
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    access_token = res.cookies.get("access_token")
    assert access_token, "access_token cookie not found"
    return {"Authorization": f"Bearer {access_token}"}


# ============================================================================
# E2E #1: LOGIN HISTORY — Read login records
# ============================================================================


@pytest.mark.asyncio
async def test_login_history_shows_current_login(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """E2E: After login, GET /login-history should return at least 1 record."""
    # Act
    response = await client.get(
        SecurityURLs.LOGIN_HISTORY,
        headers=admin_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data
    assert data["total"] >= 1, "Should have at least 1 login record (the login itself)"
    assert len(data["items"]) >= 1

    # Verify record structure
    item = data["items"][0]
    assert "id" in item
    assert "login_at" in item
    assert "is_new_ip" in item
    assert "is_new_device" in item
    assert "is_new_location" in item
    assert "risk_score" in item
    assert "is_suspicious" in item
    assert isinstance(item["risk_score"], int)


@pytest.mark.asyncio
async def test_login_history_pagination(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """E2E: Login-history supports skip/limit pagination."""
    # Act — request with limit=1
    response = await client.get(
        SecurityURLs.LOGIN_HISTORY,
        params={"skip": 0, "limit": 1},
        headers=admin_token_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 1


@pytest.mark.asyncio
async def test_login_history_requires_auth(client: AsyncClient):
    """E2E: GET /login-history without auth returns 401."""
    response = await client.get(SecurityURLs.LOGIN_HISTORY)
    assert response.status_code == 401


# ============================================================================
# E2E #2: SUSPICIOUS LOGINS — First login is always suspicious
# ============================================================================


@pytest.mark.asyncio
async def test_suspicious_logins_returns_first_login(
    client: AsyncClient,
    regular_user_in_db: dict,
    regular_user_token_headers: dict,
):
    """E2E: First login from new IP/device should appear in suspicious-logins."""
    # Act
    response = await client.get(
        SecurityURLs.SUSPICIOUS_LOGINS,
        params={"pending_only": True},
        headers=regular_user_token_headers,
    )

    # Assert
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) >= 1, "First login should be flagged as suspicious"

    suspicious = items[0]
    assert suspicious["is_suspicious"] is True
    assert suspicious["user_response"] is None  # Not yet responded


@pytest.mark.asyncio
async def test_suspicious_logins_requires_auth(client: AsyncClient):
    """E2E: GET /suspicious-logins without auth returns 401."""
    response = await client.get(SecurityURLs.SUSPICIOUS_LOGINS)
    assert response.status_code == 401


# ============================================================================
# E2E #3: CONFIRM LOGIN → TRUST DEVICE (full flow)
# ============================================================================


@pytest.mark.asyncio
async def test_confirm_login_and_trust_device_flow(
    client: AsyncClient,
    regular_user_in_db: dict,
    regular_user_token_headers: dict,
):
    """
    E2E Full Flow:
    1. GET suspicious-logins → get login_id
    2. POST confirm-login (trust_device=True) → verify confirmed
    3. GET suspicious-logins (pending_only=True) → should be empty
    4. GET trusted-devices → should have 1 device
    """
    # STEP 1: Get suspicious logins
    susp_resp = await client.get(
        SecurityURLs.SUSPICIOUS_LOGINS,
        params={"pending_only": True},
        headers=regular_user_token_headers,
    )
    assert susp_resp.status_code == 200
    suspicious = susp_resp.json()
    assert len(suspicious) >= 1
    login_id = suspicious[0]["id"]

    # STEP 2: Confirm the login with trust_device=True
    confirm_resp = await client.post(
        SecurityURLs.CONFIRM_LOGIN,
        json={"login_id": login_id, "trust_device": True},
        headers=regular_user_token_headers,
    )
    assert confirm_resp.status_code == 200
    confirm_data = confirm_resp.json()
    assert confirm_data["message"] == "Login confirmed successfully"
    assert confirm_data["device_trusted"] is True

    # STEP 3: Suspicious logins (pending) should now be empty
    susp_resp2 = await client.get(
        SecurityURLs.SUSPICIOUS_LOGINS,
        params={"pending_only": True},
        headers=regular_user_token_headers,
    )
    assert susp_resp2.status_code == 200
    pending = susp_resp2.json()
    # The confirmed login should no longer appear in pending
    pending_ids = [item["id"] for item in pending]
    assert login_id not in pending_ids

    # STEP 4: Trusted devices should have the newly trusted device
    devices_resp = await client.get(
        SecurityURLs.TRUSTED_DEVICES,
        headers=regular_user_token_headers,
    )
    assert devices_resp.status_code == 200
    devices_data = devices_resp.json()
    assert devices_data["total"] >= 1
    assert len(devices_data["items"]) >= 1

    device = devices_data["items"][0]
    assert "id" in device
    assert "name" in device
    assert "browser" in device
    assert "trusted_at" in device


@pytest.mark.asyncio
async def test_confirm_login_without_trusting_device(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """E2E: Confirm login with trust_device=False should NOT create trusted device."""
    # Get a suspicious login
    susp_resp = await client.get(
        SecurityURLs.SUSPICIOUS_LOGINS,
        params={"pending_only": True},
        headers=admin_token_headers,
    )
    assert susp_resp.status_code == 200
    suspicious = susp_resp.json()
    assert len(suspicious) >= 1
    login_id = suspicious[0]["id"]

    # Confirm WITHOUT trusting device
    confirm_resp = await client.post(
        SecurityURLs.CONFIRM_LOGIN,
        json={"login_id": login_id, "trust_device": False},
        headers=admin_token_headers,
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["device_trusted"] is False

    # Trusted devices should be empty
    devices_resp = await client.get(
        SecurityURLs.TRUSTED_DEVICES,
        headers=admin_token_headers,
    )
    assert devices_resp.status_code == 200
    assert devices_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_confirm_nonexistent_login_returns_404(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """E2E: Confirm a non-existent login_id returns 404."""
    response = await client.post(
        SecurityURLs.CONFIRM_LOGIN,
        json={"login_id": NON_EXISTENT_ID, "trust_device": False},
        headers=admin_token_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_confirm_login_requires_auth(client: AsyncClient):
    """E2E: POST /confirm-login without auth returns 401."""
    response = await client.post(
        SecurityURLs.CONFIRM_LOGIN,
        json={"login_id": 1, "trust_device": False},
    )
    assert response.status_code == 401


# ============================================================================
# E2E #4: STALE LOGIN CONFIRMATION (C3 fix regression)
# ============================================================================


@pytest.mark.asyncio
async def test_confirm_stale_login_returns_400(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """
    E2E (C3 fix): Cannot confirm a login older than 7 days.
    Directly insert an old LoginHistory record, then try to confirm via API.
    """
    user_id = admin_user_in_db["id"]

    # Arrange: Insert a login record that is 10 days old
    async with AsyncSessionLocal() as session:
        async with session.begin():
            old_login = LoginHistory(
                user_id=user_id,
                login_at=datetime.now(timezone.utc) - timedelta(days=10),
                ip_address="99.99.99.99",
                is_new_ip=True,
                is_new_device=True,
                is_new_location=True,
                risk_score=100,
            )
            session.add(old_login)
            await session.flush()
            old_login_id = old_login.id

    # Act: Try to confirm
    response = await client.post(
        SecurityURLs.CONFIRM_LOGIN,
        json={"login_id": old_login_id, "trust_device": False},
        headers=admin_token_headers,
    )

    # Assert: Should be rejected
    assert response.status_code == 400
    assert "7 days" in response.json().get("detail", "")


# ============================================================================
# E2E #5: SECURE ACCOUNT (full flow)
# ============================================================================


@pytest.mark.asyncio
async def test_secure_account_flow(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """
    E2E Full Flow:
    1. GET suspicious-logins → get login_id
    2. POST secure-account → verify response
    3. Verify DB: password_reset_required=True
    4. Verify DB: trusted devices removed
    5. Verify DB: login marked as "secured"
    """
    user_id = admin_user_in_db["id"]

    # STEP 1: Get suspicious login
    susp_resp = await client.get(
        SecurityURLs.SUSPICIOUS_LOGINS,
        params={"pending_only": True},
        headers=admin_token_headers,
    )
    assert susp_resp.status_code == 200
    suspicious = susp_resp.json()
    assert len(suspicious) >= 1
    login_id = suspicious[0]["id"]

    # STEP 2: Secure account
    secure_resp = await client.post(
        f"{SecurityURLs.SECURE_ACCOUNT}?login_id={login_id}",
        headers=admin_token_headers,
    )
    assert secure_resp.status_code == 200
    secure_data = secure_resp.json()
    assert "Account secured" in secure_data["message"]
    assert "sessions_revoked" in secure_data
    assert isinstance(secure_data["sessions_revoked"], int)

    # STEP 3: Verify DB — password_reset_required=True
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        assert user.password_reset_required is True, \
            "password_reset_required should be True after secure_account"

    # STEP 4: Verify DB — trusted devices removed
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TrustedDevice).where(TrustedDevice.user_id == user_id)
        )
        devices = result.scalars().all()
        assert len(devices) == 0, "All trusted devices should be removed"

    # STEP 5: Verify DB — login marked as "secured"
    async with AsyncSessionLocal() as session:
        login = await session.get(LoginHistory, login_id)
        assert login.user_response == "secured"
        assert login.responded_at is not None


@pytest.mark.asyncio
async def test_secure_account_nonexistent_login_returns_404(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """E2E: Secure account with non-existent login_id returns 404."""
    response = await client.post(
        f"{SecurityURLs.SECURE_ACCOUNT}?login_id={NON_EXISTENT_ID}",
        headers=admin_token_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_secure_account_requires_auth(client: AsyncClient):
    """E2E: POST /secure-account without auth returns 401."""
    response = await client.post(
        f"{SecurityURLs.SECURE_ACCOUNT}?login_id=1",
    )
    assert response.status_code == 401


# ============================================================================
# E2E #6: TRUSTED DEVICE MANAGEMENT
# ============================================================================


@pytest.mark.asyncio
async def test_trusted_devices_list_empty_initially(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """E2E: Trusted devices list is empty for a new user."""
    response = await client.get(
        SecurityURLs.TRUSTED_DEVICES,
        headers=admin_token_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_delete_trusted_device_flow(
    client: AsyncClient,
    regular_user_in_db: dict,
    regular_user_token_headers: dict,
):
    """
    E2E Full Flow:
    1. Confirm login (trust_device=True) → device created
    2. GET trusted-devices → verify device exists
    3. DELETE trusted-devices/{id} → 204
    4. GET trusted-devices → verify empty
    """
    # STEP 1: Get suspicious login and confirm with trust
    susp_resp = await client.get(
        SecurityURLs.SUSPICIOUS_LOGINS,
        params={"pending_only": True},
        headers=regular_user_token_headers,
    )
    suspicious = susp_resp.json()
    assert len(suspicious) >= 1
    login_id = suspicious[0]["id"]

    await client.post(
        SecurityURLs.CONFIRM_LOGIN,
        json={"login_id": login_id, "trust_device": True},
        headers=regular_user_token_headers,
    )

    # STEP 2: Get trusted devices
    devices_resp = await client.get(
        SecurityURLs.TRUSTED_DEVICES,
        headers=regular_user_token_headers,
    )
    assert devices_resp.status_code == 200
    devices = devices_resp.json()
    assert devices["total"] >= 1
    device_id = devices["items"][0]["id"]

    # STEP 3: Delete the device
    delete_resp = await client.delete(
        SecurityURLs.TRUSTED_DEVICE_DETAIL(device_id),
        headers=regular_user_token_headers,
    )
    assert delete_resp.status_code == 204

    # STEP 4: Verify device is gone
    devices_resp2 = await client.get(
        SecurityURLs.TRUSTED_DEVICES,
        headers=regular_user_token_headers,
    )
    assert devices_resp2.status_code == 200
    assert devices_resp2.json()["total"] == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_device_returns_404(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
):
    """E2E (Bug #2 regression): DELETE non-existent device returns 404, not 500."""
    response = await client.delete(
        SecurityURLs.TRUSTED_DEVICE_DETAIL(NON_EXISTENT_ID),
        headers=admin_token_headers,
    )
    assert response.status_code == 404
    assert "Device not found" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_delete_all_trusted_devices(
    client: AsyncClient,
    regular_user_in_db: dict,
    regular_user_token_headers: dict,
):
    """E2E: DELETE /trusted-devices (no id) removes all devices."""
    # Setup: confirm login to create a trusted device
    susp_resp = await client.get(
        SecurityURLs.SUSPICIOUS_LOGINS,
        params={"pending_only": True},
        headers=regular_user_token_headers,
    )
    suspicious = susp_resp.json()
    if len(suspicious) >= 1:
        await client.post(
            SecurityURLs.CONFIRM_LOGIN,
            json={"login_id": suspicious[0]["id"], "trust_device": True},
            headers=regular_user_token_headers,
        )

    # Act: Delete ALL devices
    delete_resp = await client.delete(
        SecurityURLs.TRUSTED_DEVICES,
        headers=regular_user_token_headers,
    )
    assert delete_resp.status_code == 204

    # Assert: No devices remain
    devices_resp = await client.get(
        SecurityURLs.TRUSTED_DEVICES,
        headers=regular_user_token_headers,
    )
    assert devices_resp.status_code == 200
    assert devices_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_trusted_devices_requires_auth(client: AsyncClient):
    """E2E: GET /trusted-devices without auth returns 401."""
    response = await client.get(SecurityURLs.TRUSTED_DEVICES)
    assert response.status_code == 401


# ============================================================================
# E2E #7: CROSS-USER ISOLATION (IDOR protection)
# ============================================================================


@pytest.mark.asyncio
async def test_cannot_confirm_other_users_login(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
    regular_user_in_db: dict,
):
    """
    E2E (IDOR): Admin cannot confirm regular user's suspicious login.
    Should return 404 (not 403) to avoid leaking resource existence.
    """
    regular_user_id = regular_user_in_db["id"]

    # Insert a suspicious login for regular user
    async with AsyncSessionLocal() as session:
        async with session.begin():
            login = LoginHistory(
                user_id=regular_user_id,
                login_at=datetime.now(timezone.utc),
                ip_address="10.20.30.40",
                is_new_ip=True,
                is_new_device=True,
                is_new_location=False,
                risk_score=70,
            )
            session.add(login)
            await session.flush()
            other_login_id = login.id

    # Act: Admin tries to confirm regular user's login
    response = await client.post(
        SecurityURLs.CONFIRM_LOGIN,
        json={"login_id": other_login_id, "trust_device": False},
        headers=admin_token_headers,
    )

    # Assert: 404 (not 403)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_secure_other_users_login(
    client: AsyncClient,
    admin_user_in_db: dict,
    admin_token_headers: dict,
    regular_user_in_db: dict,
):
    """
    E2E (IDOR): Admin cannot secure account via regular user's login record.
    Should return 404.
    """
    regular_user_id = regular_user_in_db["id"]

    # Insert a suspicious login for regular user
    async with AsyncSessionLocal() as session:
        async with session.begin():
            login = LoginHistory(
                user_id=regular_user_id,
                login_at=datetime.now(timezone.utc),
                ip_address="50.60.70.80",
                is_new_ip=True,
                is_new_device=False,
                is_new_location=True,
                risk_score=50,
            )
            session.add(login)
            await session.flush()
            other_login_id = login.id

    # Act: Admin tries to secure account via other user's login
    response = await client.post(
        f"{SecurityURLs.SECURE_ACCOUNT}?login_id={other_login_id}",
        headers=admin_token_headers,
    )

    # Assert: 404
    assert response.status_code == 404
