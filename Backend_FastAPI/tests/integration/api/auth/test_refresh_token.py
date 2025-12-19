# tests/integration/api/auth/test_refresh_token.py
# -*- coding: utf-8 -*-
"""
✅ REFRESH TOKEN API TESTS (Updated for httpOnly Cookie Pattern)

Tests for refresh token functionality:
- Refresh success with cookies
- Token rotation verification
- Invalid/expired token handling
- Blacklisted token rejection
- Concurrent refresh protection

Note: Tests verify API behavior, not Redis state directly.
"""
import asyncio
import logging
from datetime import timedelta
from typing import List

import pytest
from httpx import AsyncClient, Response, ASGITransport

from app.config import settings
from app.security import create_refresh_token, decode_token_for_invalidation

try:
    from tests.fixtures.constants import AuthURLs, ProfileURLs, SecurityConstants
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_refresh_success_with_cookies(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Refresh token thành công với httpOnly cookies.
    
    Kiểm tra:
    1. Login sets cookies
    2. Refresh endpoint returns new cookies
    3. Token rotation (new tokens different from old)
    4. New cookies work for protected endpoints
    5. User info in response (FIX-4)
    """
    log.info("--- Running: test_refresh_success_with_cookies ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    
    initial_access = login_res.cookies.get("access_token")
    initial_refresh = login_res.cookies.get("refresh_token")
    assert initial_access and initial_refresh, "Cookies not set after login"
    log.info("✅ Login successful, cookies obtained")

    # Step 2: Call refresh
    refresh_res = await client.post(AuthURLs.REFRESH)
    assert refresh_res.status_code == 200, f"Refresh failed: {refresh_res.text}"
    log.info("✅ Refresh returned 200")

    # Step 3: Verify new cookies set
    new_access = refresh_res.cookies.get("access_token")
    new_refresh = refresh_res.cookies.get("refresh_token")
    assert new_access and new_refresh, "New cookies not set"
    assert new_access != initial_access, "Access token not rotated"
    assert new_refresh != initial_refresh, "Refresh token not rotated"
    log.info("✅ Tokens rotated successfully")

    # Step 4: Verify response contains user info (FIX-4)
    response_data = refresh_res.json()
    assert "user" in response_data, "User info missing (FIX-4)"
    user_data = response_data["user"]
    assert user_data["id"] == user_id
    assert user_data["username"] == username
    assert "password_hash" not in user_data, "Password hash should not be exposed"
    log.info("✅ User info in response verified")

    # Step 5: New cookies work
    profile_res = await client.get(ProfileURLs.PROFILE)
    assert profile_res.status_code == 200, "New cookies should work"
    log.info("✅ New cookies work for protected endpoints")

    # Step 6: Old tokens don't work
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as old_client:
        old_client.cookies.set("access_token", initial_access)
        profile_old = await old_client.get(ProfileURLs.PROFILE)
        assert profile_old.status_code == 401, "Old access token should be invalid"
    log.info("✅ Old tokens correctly rejected")

    log.info("--- Finished: test_refresh_success_with_cookies ---")


@pytest.mark.asyncio
async def test_refresh_invalid_token_string(client: AsyncClient):
    """
    ✅ TEST: Refresh với token không hợp lệ (401).
    
    Security: Malformed token injection protection.
    """
    log.info("--- Running: test_refresh_invalid_token_string ---")
    
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        new_client.cookies.set("refresh_token", SecurityConstants.INVALID_TOKEN_STRING)
        response = await new_client.post(AuthURLs.REFRESH)
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    log.info("✅ Invalid token correctly rejected")

    log.info("--- Finished: test_refresh_invalid_token_string ---")


@pytest.mark.asyncio
async def test_refresh_expired_token(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Refresh với token đã hết hạn (401).
    
    Security: Expired token protection.
    """
    log.info("--- Running: test_refresh_expired_token ---")
    
    # Create expired token
    expired_token = create_refresh_token(
        data={"sub": regular_user_in_db["username"]},
        expires_delta=timedelta(seconds=-5)  # Already expired
    )

    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        new_client.cookies.set("refresh_token", expired_token)
        response = await new_client.post(AuthURLs.REFRESH)

    assert response.status_code == 401
    log.info("✅ Expired token correctly rejected")

    log.info("--- Finished: test_refresh_expired_token ---")


@pytest.mark.asyncio
async def test_refresh_blacklisted_token(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Refresh với token đã bị blacklist sau logout (401).
    
    Security: Token replay prevention after logout.
    """
    log.info("--- Running: test_refresh_blacklisted_token ---")
    
    # Login
    login_res = await client.post(AuthURLs.LOGIN, data={
        "username": regular_user_in_db["username"],
        "password": regular_user_in_db["password"]
    })
    assert login_res.status_code == 200
    refresh_token = login_res.cookies.get("refresh_token")
    log.info("✅ Login successful")

    # Logout
    logout_res = await client.post(AuthURLs.LOGOUT)
    assert logout_res.status_code == 204
    log.info("✅ Logged out")

    # Try refresh with old token
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        new_client.cookies.set("refresh_token", refresh_token)
        response = await new_client.post(AuthURLs.REFRESH)

    assert response.status_code == 401
    log.info("✅ Blacklisted token correctly rejected")

    log.info("--- Finished: test_refresh_blacklisted_token ---")


@pytest.mark.asyncio
async def test_refresh_old_token_after_rotation(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Cannot reuse old refresh token after rotation.
    
    Security: Prevents token replay after legitimate refresh.
    """
    log.info("--- Running: test_refresh_old_token_after_rotation ---")
    
    # Login
    login_res = await client.post(AuthURLs.LOGIN, data={
        "username": regular_user_in_db["username"],
        "password": regular_user_in_db["password"]
    })
    assert login_res.status_code == 200
    old_refresh = login_res.cookies.get("refresh_token")

    # First refresh
    refresh_res = await client.post(AuthURLs.REFRESH)
    assert refresh_res.status_code == 200
    log.info("✅ First refresh successful")

    # Try reusing old refresh token
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        new_client.cookies.set("refresh_token", old_refresh)
        response = await new_client.post(AuthURLs.REFRESH)

    assert response.status_code == 401, "Old token should be rejected after rotation"
    log.info("✅ Old refresh token rejected after rotation")

    log.info("--- Finished: test_refresh_old_token_after_rotation ---")


@pytest.mark.asyncio
async def test_refresh_concurrent_requests(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Concurrent refresh requests - only one should succeed.
    
    Security: Race condition protection for token rotation.
    """
    log.info("--- Running: test_refresh_concurrent_requests ---")

    # Login
    login_res = await client.post(AuthURLs.LOGIN, data={
        "username": regular_user_in_db["username"],
        "password": regular_user_in_db["password"]
    })
    assert login_res.status_code == 200
    refresh_token = login_res.cookies.get("refresh_token")

    from app.main import fastapi_app

    async def make_refresh_request():
        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
            c.cookies.set("refresh_token", refresh_token)
            return await c.post(AuthURLs.REFRESH)

    num_requests = 5
    tasks = [make_refresh_request() for _ in range(num_requests)]
    results: List[Response] = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = sum(1 for r in results if hasattr(r, 'status_code') and r.status_code == 200)
    fail_count = sum(1 for r in results if hasattr(r, 'status_code') and r.status_code in [400, 401])
    
    log.info(f"Concurrent results: {success_count} success, {fail_count} failures")
    
    # Should have exactly 1 success (due to token rotation)
    assert success_count == 1, f"Expected 1 success, got {success_count}"
    log.info("✅ Only one concurrent request succeeded")

    log.info("--- Finished: test_refresh_concurrent_requests ---")


@pytest.mark.asyncio
async def test_refresh_without_cookie(client: AsyncClient):
    """
    ✅ TEST: Refresh without refresh_token cookie (401).
    
    Security: Missing credential handling.
    """
    log.info("--- Running: test_refresh_without_cookie ---")
    
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        response = await new_client.post(AuthURLs.REFRESH)

    assert response.status_code == 401
    log.info("✅ Missing cookie correctly returns 401")

    log.info("--- Finished: test_refresh_without_cookie ---")
