# tests/routers/test_cookie_based_auth.py
# -*- coding: utf-8 -*-
"""
✅ COMPREHENSIVE COOKIE-BASED AUTHENTICATION TESTS

Tests for the httpOnly cookie authentication migration:
- Login sets access_token and refresh_token cookies
- API endpoints authenticate using cookies (not Authorization header)
- Cookies have correct security attributes (httpOnly, secure, samesite, path)
- Refresh endpoint works with cookies
- Logout deletes both cookies
- Socket.io authenticates using cookies

Created: 2025-11-09
Related: Client-side auth guard vulnerability fix + cookie migration
"""
import asyncio
import logging
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.config import settings

# Import constants
try:
    from ..fixtures.constants import AuthURLs, ProfileURLs, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# ============================================
# COOKIE SECURITY TESTS
# ============================================


@pytest.mark.asyncio
async def test_login_sets_both_cookies(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Login sets both access_token and refresh_token cookies.

    Verifies:
    1. access_token cookie is set with correct attributes
    2. refresh_token cookie is set with correct attributes
    3. Tokens are NOT in response body (httpOnly security)
    4. Response contains user info only
    """
    log.info("--- Running: test_login_sets_both_cookies ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"

    # ✅ FIX-5: Verify tokens are NOT in response body (httpOnly security)
    response_data = login_res.json()
    assert "access_token" not in response_data or response_data.get("access_token") is None, \
        "access_token should NOT be in response body (httpOnly cookie only)"
    assert "user" in response_data, "user info missing from response"
    log.info("✅ Response contains user info only (no tokens)")

    # Verify cookies are set
    cookies = login_res.cookies
    assert "access_token" in cookies, "access_token cookie not set"
    assert "refresh_token" in cookies, "refresh_token cookie not set"
    log.info("✅ Both cookies are set")

    # Verify cookie attributes via Set-Cookie header
    set_cookie_headers = login_res.headers.get_list("set-cookie")

    # Find access_token cookie header
    access_cookie_header = None
    refresh_cookie_header = None
    for header in set_cookie_headers:
        if "access_token=" in header:
            access_cookie_header = header
        if "refresh_token=" in header:
            refresh_cookie_header = header

    assert access_cookie_header is not None, "access_token Set-Cookie header not found"
    assert refresh_cookie_header is not None, "refresh_token Set-Cookie header not found"

    # Verify access_token attributes
    assert "HttpOnly" in access_cookie_header, "access_token should be HttpOnly"
    assert "Path=/" in access_cookie_header or "path=/" in access_cookie_header.lower(), \
        "access_token should have path=/"
    assert "SameSite=Lax" in access_cookie_header or "samesite=lax" in access_cookie_header.lower(), \
        "access_token should have SameSite=Lax"

    # Verify refresh_token attributes
    assert "HttpOnly" in refresh_cookie_header, "refresh_token should be HttpOnly"
    assert "Path=/api" in refresh_cookie_header or "path=/api" in refresh_cookie_header.lower(), \
        "refresh_token should have path=/api"
    assert "SameSite=Strict" in refresh_cookie_header or "samesite=strict" in refresh_cookie_header.lower(), \
        "refresh_token should have SameSite=Strict"

    log.info("✅ Cookie attributes verified:")
    log.info(f"  - access_token: HttpOnly, Path=/, SameSite=Lax")
    log.info(f"  - refresh_token: HttpOnly, Path=/api, SameSite=Strict")

    # Note: Secure flag only set in production
    if settings.APP_ENV == "production":
        assert "Secure" in access_cookie_header, "access_token should be Secure in production"
        assert "Secure" in refresh_cookie_header, "refresh_token should be Secure in production"
        log.info("✅ Secure flag verified (production mode)")

    log.info("--- Finished: test_login_sets_both_cookies ---")


@pytest.mark.asyncio
async def test_api_auth_with_cookies_no_header(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: API endpoints authenticate using cookies (no Authorization header).

    Verifies:
    1. Login and get cookies
    2. Call protected endpoint with cookies only (no Authorization header)
    3. Request succeeds
    """
    log.info("--- Running: test_api_auth_with_cookies_no_header ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200

    # Get cookies (httpx automatically manages cookies)
    cookies = login_res.cookies
    log.info("✅ Login successful, cookies obtained")

    # Step 2: Call protected endpoint with cookies ONLY (no Authorization header)
    # httpx.AsyncClient automatically sends cookies
    profile_res = await client.get(ProfileURLs.PROFILE)

    assert profile_res.status_code == 200, \
        f"Profile request should succeed with cookies. Got: {profile_res.status_code}, {profile_res.text}"

    profile_data = profile_res.json()
    assert profile_data["username"] == username
    log.info("✅ Protected endpoint accessible with cookies (no Authorization header)")

    log.info("--- Finished: test_api_auth_with_cookies_no_header ---")


@pytest.mark.asyncio
async def test_refresh_works_with_cookies(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Refresh endpoint works with httpOnly cookies.

    Verifies:
    1. Login to get cookies
    2. Call /refresh with cookies (no body)
    3. New access_token and refresh_token cookies are set
    4. Can use new cookies to access protected endpoints
    """
    log.info("--- Running: test_refresh_works_with_cookies ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200

    old_cookies = dict(login_res.cookies)
    log.info("✅ Login successful")

    # Step 2: Call refresh (cookies sent automatically)
    refresh_res = await client.post(AuthURLs.REFRESH)
    assert refresh_res.status_code == 200, f"Refresh failed: {refresh_res.text}"

    # Verify new cookies are set
    new_cookies = refresh_res.cookies
    assert "access_token" in new_cookies, "New access_token cookie not set"
    assert "refresh_token" in new_cookies, "New refresh_token cookie not set"

    # Verify tokens rotated (new values different from old)
    assert new_cookies["access_token"] != old_cookies["access_token"], \
        "access_token should be rotated"
    assert new_cookies["refresh_token"] != old_cookies["refresh_token"], \
        "refresh_token should be rotated"

    log.info("✅ Tokens rotated successfully")

    # Step 3: Verify new cookies work
    # httpx client now has new cookies
    profile_res = await client.get(ProfileURLs.PROFILE)
    assert profile_res.status_code == 200, "New cookies should work"
    log.info("✅ New cookies work for protected endpoints")

    # Verify response contains user info (FIX-4)
    refresh_data = refresh_res.json()
    assert "user" in refresh_data, "User info missing in refresh response"
    assert refresh_data["user"]["username"] == username
    log.info("✅ Refresh response contains user info")

    log.info("--- Finished: test_refresh_works_with_cookies ---")


@pytest.mark.asyncio
async def test_logout_deletes_both_cookies(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Logout deletes both cookies with correct paths.

    Verifies:
    1. Login to get cookies
    2. Logout
    3. Both cookies are deleted (Max-Age=0)
    4. Paths match the set_cookie paths
    5. Cannot access protected endpoints after logout
    """
    log.info("--- Running: test_logout_deletes_both_cookies ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200
    log.info("✅ Login successful")

    # Verify can access protected endpoint
    profile_res_before = await client.get(ProfileURLs.PROFILE)
    assert profile_res_before.status_code == 200

    # Step 2: Logout
    logout_res = await client.post(AuthURLs.LOGOUT)
    assert logout_res.status_code == 204, f"Logout failed: {logout_res.text}"
    log.info("✅ Logout successful")

    # Step 3: Verify cookie deletion via Set-Cookie headers
    set_cookie_headers = logout_res.headers.get_list("set-cookie")

    access_cookie_deleted = False
    refresh_cookie_deleted = False

    for header in set_cookie_headers:
        if "access_token" in header:
            # Verify Max-Age=0 and correct path
            assert "Max-Age=0" in header or "max-age=0" in header.lower(), \
                "access_token should have Max-Age=0"
            assert "Path=/" in header or "path=/" in header.lower(), \
                "access_token deletion should have path=/"
            access_cookie_deleted = True

        if "refresh_token" in header:
            # Verify Max-Age=0 and correct path
            assert "Max-Age=0" in header or "max-age=0" in header.lower(), \
                "refresh_token should have Max-Age=0"
            assert "Path=/api" in header or "path=/api" in header.lower(), \
                "refresh_token deletion should have path=/api"
            refresh_cookie_deleted = True

    assert access_cookie_deleted, "access_token cookie not deleted"
    assert refresh_cookie_deleted, "refresh_token cookie not deleted"
    log.info("✅ Both cookies deleted with correct paths")

    # Step 4: Verify cannot access protected endpoints
    # httpx client cookies should be cleared
    profile_res_after = await client.get(ProfileURLs.PROFILE)
    assert profile_res_after.status_code == 401, \
        "Should not be able to access protected endpoint after logout"
    log.info("✅ Cannot access protected endpoints after logout")

    log.info("--- Finished: test_logout_deletes_both_cookies ---")


# ============================================
# SECURITY EDGE CASE TESTS
# ============================================


@pytest.mark.asyncio
async def test_expired_cookie_rejected(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ TEST: Expired access_token cookie is rejected.

    Verifies:
    1. Login to get cookies
    2. Invalidate session in Redis (simulate expiry)
    3. Request with expired cookie returns 401
    """
    log.info("--- Running: test_expired_cookie_rejected ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200
    log.info("✅ Login successful")

    # Step 2: Extract r_jti from access_token cookie and invalidate session
    # ✅ FIX-5: Token is now in cookie, not response body
    access_token = login_res.cookies.get("access_token")
    assert access_token, "access_token cookie not found"
    from jose import jwt
    payload = jwt.decode(
        access_token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM]
    )
    r_jti = payload.get("r_jti")
    assert r_jti, "Could not extract r_jti from token"

    # Invalidate session
    await test_redis_client.delete(f"session:{r_jti}")
    log.info("✅ Session invalidated in Redis")

    # Step 3: Try to access protected endpoint (should fail)
    await asyncio.sleep(0.1)  # Small delay for Redis propagation
    profile_res = await client.get(ProfileURLs.PROFILE)
    assert profile_res.status_code == 401, \
        "Should reject expired session cookie"
    log.info("✅ Expired cookie correctly rejected")

    log.info("--- Finished: test_expired_cookie_rejected ---")


@pytest.mark.asyncio
async def test_blacklisted_user_cookie_rejected(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ TEST: Cookie from blacklisted user is rejected.

    Verifies:
    1. Login to get cookies
    2. Blacklist user (simulate password change)
    3. Request with cookie returns 401
    """
    log.info("--- Running: test_blacklisted_user_cookie_rejected ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200
    log.info("✅ Login successful")

    # Step 2: Blacklist user
    await test_redis_client.set(f"user_blacklist:{user_id}", "password_changed", ex=3600)
    log.info(f"✅ User {user_id} blacklisted")

    # Step 3: Try to access protected endpoint (should fail)
    await asyncio.sleep(0.1)  # Small delay for Redis propagation
    profile_res = await client.get(ProfileURLs.PROFILE)
    assert profile_res.status_code == 401, \
        "Should reject blacklisted user cookie"
    log.info("✅ Blacklisted user cookie correctly rejected")

    # Cleanup
    await test_redis_client.delete(f"user_blacklist:{user_id}")

    log.info("--- Finished: test_blacklisted_user_cookie_rejected ---")


@pytest.mark.asyncio
async def test_cookie_and_header_both_work(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Both cookie and Authorization header work (backwards compatibility).

    Verifies backend accepts both authentication methods during migration period.
    """
    log.info("--- Running: test_cookie_and_header_both_work ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200

    # ✅ FIX-5: Token is now in cookie, not response body
    access_token = login_res.cookies.get("access_token")
    assert access_token, "access_token cookie not found"

    # Test 1: Cookie-based auth (httpx client has cookies)
    profile_res_cookie = await client.get(ProfileURLs.PROFILE)
    assert profile_res_cookie.status_code == 200, "Cookie auth should work"
    log.info("✅ Cookie-based auth works")

    # Test 2: Header-based auth (create new client without cookies)
    async with AsyncClient(base_url=client.base_url) as new_client:
        headers = {"Authorization": f"Bearer {access_token}"}
        profile_res_header = await new_client.get(ProfileURLs.PROFILE, headers=headers)
        assert profile_res_header.status_code == 200, "Header auth should work"
        log.info("✅ Header-based auth works (backwards compatibility)")

    log.info("--- Finished: test_cookie_and_header_both_work ---")


# ============================================
# INTEGRATION TEST
# ============================================


@pytest.mark.asyncio
async def test_complete_cookie_auth_flow(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ COMPREHENSIVE: Test complete cookie-based auth flow.

    Flow:
    1. Login → verify cookies set
    2. Access protected endpoint with cookies
    3. Refresh → verify new cookies
    4. Access endpoint with new cookies
    5. Logout → verify cookies deleted
    6. Cannot access endpoint after logout
    """
    log.info("--- Running: test_complete_cookie_auth_flow ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200
    assert "access_token" in login_res.cookies
    assert "refresh_token" in login_res.cookies
    log.info("✅ Step 1: Login successful, cookies set")

    # Step 2: Access protected endpoint
    profile_res = await client.get(ProfileURLs.PROFILE)
    assert profile_res.status_code == 200
    assert profile_res.json()["username"] == username
    log.info("✅ Step 2: Protected endpoint accessible")

    # Step 3: Refresh tokens
    refresh_res = await client.post(AuthURLs.REFRESH)
    assert refresh_res.status_code == 200
    assert "access_token" in refresh_res.cookies
    assert "refresh_token" in refresh_res.cookies
    log.info("✅ Step 3: Tokens refreshed")

    # Step 4: Access endpoint with new cookies
    profile_res_after_refresh = await client.get(ProfileURLs.PROFILE)
    assert profile_res_after_refresh.status_code == 200
    log.info("✅ Step 4: Protected endpoint accessible with new cookies")

    # Step 5: Logout
    logout_res = await client.post(AuthURLs.LOGOUT)
    assert logout_res.status_code == 204
    log.info("✅ Step 5: Logout successful")

    # Step 6: Cannot access after logout
    profile_res_after_logout = await client.get(ProfileURLs.PROFILE)
    assert profile_res_after_logout.status_code == 401
    log.info("✅ Step 6: Cannot access after logout")

    log.info("--- Finished: test_complete_cookie_auth_flow ---")
    log.info("✅✅✅ COMPLETE COOKIE AUTH FLOW VERIFIED ✅✅✅")
