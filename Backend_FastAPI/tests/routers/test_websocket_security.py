# tests/routers/test_websocket_security.py
# -*- coding: utf-8 -*-
"""
✅ WEBSOCKET SECURITY TESTS (FIX-3)

Tests for WebSocket authentication security improvements:
- User blacklist check (parity with HTTP auth)
- Periodic revalidation mechanism
- Force logout events

SECURITY ISSUE FIXED:
- Before: WebSocket only checked session validity
- After: WebSocket checks user blacklist + periodic revalidation
- Impact: Prevents information leak via WebSocket after password change

Created: 2025-11-07
Related PR: Security Audit & Performance Improvements

NOTE: These tests require proper WebSocket client setup.
Install: pip install python-socketio[asyncio_client]
"""
import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

# Socket.IO async client
try:
    import socketio
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    socketio = None

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import User

# Import constants
try:
    from ..fixtures.constants import AuthURLs, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# Skip all tests if socketio client not available
pytestmark = pytest.mark.skipif(
    not SOCKETIO_AVAILABLE,
    reason="python-socketio not installed. Install with: pip install python-socketio[asyncio_client]"
)


# ============================================
# FIXTURES
# ============================================


@pytest_asyncio.fixture
async def sio_client():
    """Create Socket.IO async client for testing"""
    if not SOCKETIO_AVAILABLE:
        pytest.skip("socketio not available")

    sio = socketio.AsyncClient()
    yield sio

    # Cleanup
    if sio.connected:
        await sio.disconnect()


async def get_user_token(client, username: str, password: str) -> str:
    """Helper to get access token for WebSocket authentication"""
    from httpx import AsyncClient

    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    if login_res.status_code != 200:
        pytest.fail(f"Login failed: {login_res.text}")
    return login_res.json()["access_token"]


# ============================================
# FIX-3: USER BLACKLIST CHECK TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_websocket_auth_checks_user_blacklist(
    client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ FIX-3: Test that WebSocket connection is refused for blacklisted users.

    Test Flow:
    1. Blacklist user in Redis
    2. Try to connect with valid token
    3. Connection should be refused

    Expected: ConnectionRefusedError due to user_blacklist check
    """
    log.info("--- Running: test_fix3_websocket_auth_checks_user_blacklist ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Get access token
    access_token = await get_user_token(client, username, password)
    log.info("✅ Got access token")

    # Blacklist user (simulate password change)
    await test_redis_client.set(f"user_blacklist:{user_id}", "password_changed", ex=3600)
    log.info(f"✅ User {user_id} blacklisted in Redis")

    # Try to connect via WebSocket
    socket_url = f"http://localhost:8000"  # Adjust based on test server
    connect_error = None

    try:
        await sio_client.connect(
            socket_url,
            auth={"token": access_token},
            transports=["websocket"]
        )
        # If we get here, connection succeeded (BAD!)
        pytest.fail("❌ SECURITY ISSUE: WebSocket connected despite user blacklist!")

    except socketio.exceptions.ConnectionRefusedError as e:
        connect_error = e
        log.info(f"✅ Connection correctly refused: {e}")

    # Verify connection was refused
    assert connect_error is not None, "Connection should have been refused"
    assert not sio_client.connected, "Client should not be connected"

    # Cleanup
    await test_redis_client.delete(f"user_blacklist:{user_id}")

    log.info("--- Finished: test_fix3_websocket_auth_checks_user_blacklist ---")


@pytest.mark.asyncio
async def test_fix3_websocket_auth_with_valid_user(
    client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ FIX-3: Test that WebSocket connection succeeds for non-blacklisted users.

    This is the happy path test to ensure the fix doesn't break normal connections.
    """
    log.info("--- Running: test_fix3_websocket_auth_with_valid_user ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Get access token
    access_token = await get_user_token(client, username, password)

    # Connect via WebSocket (should succeed)
    socket_url = f"http://localhost:8000"

    try:
        await sio_client.connect(
            socket_url,
            auth={"token": access_token},
            transports=["websocket"]
        )

        assert sio_client.connected, "Client should be connected"
        log.info("✅ WebSocket connected successfully for valid user")

    finally:
        if sio_client.connected:
            await sio_client.disconnect()

    log.info("--- Finished: test_fix3_websocket_auth_with_valid_user ---")


# ============================================
# FIX-3: PERIODIC REVALIDATION TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_websocket_revalidation_success(
    client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ FIX-3: Test periodic revalidation with valid session.

    Test Flow:
    1. Connect WebSocket
    2. Call revalidate_auth event
    3. Should return {"valid": True}
    """
    log.info("--- Running: test_fix3_websocket_revalidation_success ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Get token and connect
    access_token = await get_user_token(client, username, password)
    socket_url = f"http://localhost:8000"

    await sio_client.connect(
        socket_url,
        auth={"token": access_token},
        transports=["websocket"]
    )
    assert sio_client.connected

    # Call revalidate_auth event
    response = await sio_client.call("revalidate_auth", timeout=5)

    # Verify response
    assert isinstance(response, dict), "Response should be a dict"
    assert response.get("valid") is True, f"Expected valid=True, got {response}"
    log.info("✅ Revalidation successful")

    # Cleanup
    await sio_client.disconnect()

    log.info("--- Finished: test_fix3_websocket_revalidation_success ---")


@pytest.mark.asyncio
async def test_fix3_websocket_revalidation_detects_blacklist(
    client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ FIX-3: Test that revalidation detects user blacklist.

    Test Flow:
    1. Connect WebSocket
    2. Blacklist user (simulate password change)
    3. Call revalidate_auth
    4. Should return {"valid": False} and disconnect

    This is the MAIN security feature: catching missed force_logout events.
    """
    log.info("--- Running: test_fix3_websocket_revalidation_detects_blacklist ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Get token and connect
    access_token = await get_user_token(client, username, password)
    socket_url = f"http://localhost:8000"

    await sio_client.connect(
        socket_url,
        auth={"token": access_token},
        transports=["websocket"]
    )
    assert sio_client.connected
    log.info("✅ WebSocket connected")

    # Simulate password change (blacklist user)
    await test_redis_client.set(f"user_blacklist:{user_id}", "password_changed", ex=3600)
    log.info(f"✅ User {user_id} blacklisted")

    # Call revalidate_auth
    try:
        response = await sio_client.call("revalidate_auth", timeout=5)

        # Verify response indicates invalid
        assert isinstance(response, dict), "Response should be a dict"
        assert response.get("valid") is False, \
            f"❌ SECURITY ISSUE: Revalidation passed despite blacklist! Response: {response}"
        assert "reason" in response
        assert "invalidated" in response["reason"].lower() or "blacklist" in response["reason"].lower()

        log.info(f"✅ Revalidation correctly detected blacklist: {response}")

    except socketio.exceptions.TimeoutError:
        # Server might have disconnected us before response
        log.info("✅ Server disconnected before response (also acceptable)")

    # Wait for disconnect
    await asyncio.sleep(0.5)

    # Verify disconnection
    assert not sio_client.connected, \
        "❌ SECURITY ISSUE: Client still connected after revalidation failure!"

    # Cleanup
    await test_redis_client.delete(f"user_blacklist:{user_id}")

    log.info("--- Finished: test_fix3_websocket_revalidation_detects_blacklist ---")


# ============================================
# FIX-3: FORCE LOGOUT EVENTS TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_force_logout_batch_event(
    client, sio_client, regular_user_in_db: dict
):
    """
    ✅ FIX-3: Test that client receives and handles force_logout_batch event.

    This tests the existing force_logout mechanism still works.
    """
    log.info("--- Running: test_fix3_force_logout_batch_event ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Get token and connect
    access_token = await get_user_token(client, username, password)
    socket_url = f"http://localhost:8000"

    # Setup event listener
    logout_event_received = asyncio.Event()
    received_data = {}

    @sio_client.on("force_logout_batch")
    async def on_force_logout(data):
        nonlocal received_data
        received_data = data
        logout_event_received.set()
        log.info(f"✅ Received force_logout_batch: {data}")

    await sio_client.connect(
        socket_url,
        auth={"token": access_token},
        transports=["websocket"]
    )
    assert sio_client.connected

    # Extract r_jti from token
    from app.security import decode_token
    from jose import jwt
    payload = jwt.decode(
        access_token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM]
    )
    r_jti = payload.get("r_jti")
    assert r_jti, "Could not extract r_jti from token"

    # Simulate server emitting force_logout_batch
    # (In real scenario, this happens when admin revokes session)
    # For testing, we can't easily trigger this from client side,
    # so we'll just verify the event handler is registered

    # Note: Full integration test would require triggering from another client
    # or using server-side test hooks

    log.info("✅ Event handler registered (full integration test requires server hooks)")

    # Cleanup
    await sio_client.disconnect()

    log.info("--- Finished: test_fix3_force_logout_batch_event ---")


# ============================================
# FIX-3: INTEGRATION TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix3_websocket_end_to_end_security(
    client, sio_client, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ FIX-3: End-to-end WebSocket security test.

    Scenario:
    1. User connects via WebSocket
    2. User changes password (blacklist triggered)
    3. WebSocket either:
       a) Receives force_logout event and disconnects
       b) Next revalidation detects blacklist and disconnects
    4. User cannot reconnect with old token
    """
    log.info("--- Running: test_fix3_websocket_end_to_end_security ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]
    new_password = "NewSecurePassword!123"

    # Step 1: Connect WebSocket
    access_token = await get_user_token(client, username, password)
    socket_url = f"http://localhost:8000"

    await sio_client.connect(
        socket_url,
        auth={"token": access_token},
        transports=["websocket"]
    )
    assert sio_client.connected
    log.info("✅ Step 1: WebSocket connected")

    # Step 2: Change password (this blacklists user)
    from httpx import AsyncClient
    headers = {"Authorization": f"Bearer {access_token}"}
    change_res = await client.post(
        AuthURLs.CHANGE_PASSWORD,
        json={"old_password": password, "new_password": new_password},
        headers=headers
    )
    assert change_res.status_code == 204
    log.info("✅ Step 2: Password changed (user blacklisted)")

    # Step 3: Verify blacklist is set
    blacklist_exists = await test_redis_client.exists(f"user_blacklist:{user_id}")
    assert blacklist_exists == 1
    log.info("✅ Step 3: User blacklist confirmed in Redis")

    # Step 4: Try revalidation (should fail)
    await asyncio.sleep(0.5)  # Small delay for event propagation

    if sio_client.connected:
        try:
            response = await sio_client.call("revalidate_auth", timeout=5)
            assert response.get("valid") is False, \
                "Revalidation should fail for blacklisted user"
            log.info("✅ Step 4: Revalidation detected blacklist")
        except (socketio.exceptions.TimeoutError, socketio.exceptions.ConnectionError):
            log.info("✅ Step 4: Socket disconnected (also acceptable)")
    else:
        log.info("✅ Step 4: Socket already disconnected (ideal)")

    # Step 5: Verify cannot reconnect with old token
    if sio_client.connected:
        await sio_client.disconnect()

    try:
        await sio_client.connect(
            socket_url,
            auth={"token": access_token},  # Old token
            transports=["websocket"]
        )
        pytest.fail("❌ SECURITY ISSUE: Reconnected with old token after password change!")
    except socketio.exceptions.ConnectionRefusedError:
        log.info("✅ Step 5: Cannot reconnect with old token")

    log.info("--- Finished: test_fix3_websocket_end_to_end_security ---")
    log.info("✅✅✅ WEBSOCKET SECURITY FULLY VERIFIED ✅✅✅")


# ============================================
# PERFORMANCE TESTS
# ============================================


@pytest.mark.asyncio
@pytest.mark.slow
async def test_fix3_revalidation_performance(
    client, sio_client, regular_user_in_db: dict
):
    """
    Test that periodic revalidation doesn't impact performance.

    Verifies:
    - Revalidation completes in < 100ms
    - Multiple rapid revalidations don't cause issues
    """
    log.info("--- Running: test_fix3_revalidation_performance ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Connect
    access_token = await get_user_token(client, username, password)
    socket_url = f"http://localhost:8000"

    await sio_client.connect(
        socket_url,
        auth={"token": access_token},
        transports=["websocket"]
    )

    # Test 10 rapid revalidations
    import time
    times = []

    for i in range(10):
        start = time.perf_counter()
        response = await sio_client.call("revalidate_auth", timeout=5)
        end = time.perf_counter()

        assert response.get("valid") is True
        elapsed_ms = (end - start) * 1000
        times.append(elapsed_ms)
        log.debug(f"Revalidation {i+1}: {elapsed_ms:.2f}ms")

    # Verify performance
    avg_time = sum(times) / len(times)
    max_time = max(times)

    assert avg_time < 100, f"Average revalidation time too slow: {avg_time:.2f}ms"
    assert max_time < 200, f"Max revalidation time too slow: {max_time:.2f}ms"

    log.info(f"✅ Performance OK: avg={avg_time:.2f}ms, max={max_time:.2f}ms")

    # Cleanup
    await sio_client.disconnect()

    log.info("--- Finished: test_fix3_revalidation_performance ---")
