# tests/integration/api/auth/test_logout.py
# -*- coding: utf-8 -*-
"""
✅ LOGOUT API TESTS (Updated for httpOnly Cookie Pattern)

Tests for logout functionality:
- Logout success with cookies
- Unauthenticated logout rejection
- Token replay after logout
- Header auth backwards compatibility

Note: These tests verify API behavior, not Redis state directly.
"""
import logging

import pytest
from httpx import AsyncClient, ASGITransport

from app.security import decode_token_for_invalidation

try:
    from tests.fixtures.constants import AuthURLs, ProfileURLs, SecurityConstants
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_logout_success(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Logout thành công với httpOnly cookies.
    
    Kiểm tra:
    1. Login sets cookies
    2. Logout returns 204
    3. Cookies are deleted (Max-Age=0)
    4. Cannot access protected endpoints after logout
    """
    log.info("--- Running: test_logout_success ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    
    access_token = login_res.cookies.get("access_token")
    assert access_token, "access_token cookie not set after login"
    log.info("✅ Login successful, cookies obtained")

    # Step 2: Logout
    logout_res = await client.post(AuthURLs.LOGOUT)
    assert logout_res.status_code == 204, f"Logout failed: Status {logout_res.status_code}"
    log.info("✅ Logout returned 204 No Content")

    # Step 3: Check cookies are deleted
    logout_cookies = logout_res.headers.get_list("set-cookie")
    access_delete = [h for h in logout_cookies if "access_token=" in h]
    refresh_delete = [h for h in logout_cookies if "refresh_token=" in h]
    
    if access_delete:
        assert "Max-Age=0" in access_delete[0] or "max-age=0" in access_delete[0].lower()
        log.info("✅ access_token cookie deleted")
    if refresh_delete:
        assert "Max-Age=0" in refresh_delete[0] or "max-age=0" in refresh_delete[0].lower()
        log.info("✅ refresh_token cookie deleted")

    # Step 4: Cannot access protected endpoint
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        new_client.cookies.set("access_token", access_token)
        profile_res = await new_client.get(ProfileURLs.PROFILE)
        assert profile_res.status_code == 401, "Old token should be rejected after logout"
    log.info("✅ Protected endpoint correctly rejects old token")

    log.info("--- Finished: test_logout_success ---")


@pytest.mark.asyncio
async def test_logout_unauthenticated(client: AsyncClient):
    """
    ✅ TEST: Logout khi chưa đăng nhập (401).
    
    Security: Ensures unauthenticated requests are rejected.
    """
    log.info("--- Running: test_logout_unauthenticated ---")
    
    # Create fresh client without cookies
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        response = await new_client.post(AuthURLs.LOGOUT)
    
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    error_data = response.json()
    assert "detail" in error_data
    log.info("✅ Unauthenticated logout correctly blocked (401)")
    
    log.info("--- Finished: test_logout_unauthenticated ---")


@pytest.mark.asyncio
async def test_logout_twice_with_same_session(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Logout lần 2 với cùng token bị reject (401).
    
    Security: Token replay prevention after logout.
    """
    log.info("--- Running: test_logout_twice_with_same_session ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Login
    login_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert login_res.status_code == 200
    
    access_token = login_res.cookies.get("access_token")
    log.info("✅ Login successful")

    # First logout
    logout1 = await client.post(AuthURLs.LOGOUT)
    assert logout1.status_code == 204
    log.info("✅ First logout successful")

    # Second logout with old token (simulating replay attack)
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as replay_client:
        replay_client.cookies.set("access_token", access_token)
        logout2 = await replay_client.post(AuthURLs.LOGOUT)
        assert logout2.status_code == 401, "Replayed token should be rejected"
    log.info("✅ Second logout correctly rejected (401)")

    log.info("--- Finished: test_logout_twice_with_same_session ---")


@pytest.mark.asyncio
async def test_logout_with_header_auth_backwards_compatible(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Logout with Authorization header (mobile app compatibility).
    
    Security: During migration period, both cookie and header auth work.
    """
    log.info("--- Running: test_logout_with_header_auth_backwards_compatible ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Login to get token
    login_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert login_res.status_code == 200
    access_token = login_res.cookies.get("access_token")
    log.info("✅ Login successful")

    # Logout using header (like mobile app)
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as header_client:
        headers = {"Authorization": f"Bearer {access_token}"}
        logout_res = await header_client.post(AuthURLs.LOGOUT, headers=headers)
        assert logout_res.status_code == 204, f"Expected 204, got {logout_res.status_code}"
    log.info("✅ Logout with header auth successful")

    # Verify old token no longer works
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as verify_client:
        verify_client.cookies.set("access_token", access_token)
        profile_res = await verify_client.get(ProfileURLs.PROFILE)
        assert profile_res.status_code == 401
    log.info("✅ Old token rejected after header logout")

    log.info("--- Finished: test_logout_with_header_auth_backwards_compatible ---")
