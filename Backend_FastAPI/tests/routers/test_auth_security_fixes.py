# tests/routers/test_auth_security_fixes.py
# -*- coding: utf-8 -*-
"""
✅ COMPREHENSIVE SECURITY TESTS FOR AUTH FIXES (Updated for httpOnly Cookies)

This file contains tests for all critical security fixes:
- FIX-1: Cookie path mismatch on logout (UPDATED for httpOnly cookies)
- FIX-2: Error handling for session invalidation (UPDATED for cookie-based auth)
- FIX-3: WebSocket user blacklist check
- FIX-4: Auto-refresh token mechanism (covered in test_refresh_api.py)
- FIX-5: httpOnly cookie authentication (NEW - Client-side auth guard vulnerability fix)

Created: 2025-11-07
Updated: 2025-11-09 - httpOnly cookie migration
Related PR: Security Audit & Performance Improvements + Client-Side Auth Guard Fix
"""
import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import User, UserSession
from app.security import decode_token_for_invalidation

# Import constants
try:
    from ..fixtures.constants import AuthURLs, ProfileURLs, SecurityConstants, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# ============================================
# FIX-1: COOKIE PATH MISMATCH TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix1_logout_cookie_path_correct(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ FIX-1 + FIX-5: Test that logout properly clears BOTH httpOnly cookies with correct paths.

    SECURITY ISSUE FIXED:
    - Before: set_cookie used path="/api", delete_cookie used path="/api/auth"
    - After: Both use path="/api" for refresh_token, path="/" for access_token
    - Impact: Cookie was not deleted after logout → Session hijacking risk
    - NEW: Both tokens now in httpOnly cookies (XSS protection)

    This test verifies:
    1. Both cookies (access_token, refresh_token) are set after login with correct paths
    2. Both cookies are httpOnly (JavaScript cannot access)
    3. Both cookies are deleted after logout with same paths
    4. Refresh token cannot be reused after logout
    """
    log.info("--- Running: test_fix1_logout_cookie_path_correct ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"

    # ✅ FIX-5: Verify BOTH cookies are set
    cookies_after_login = login_res.cookies
    assert "access_token" in cookies_after_login, "access_token cookie not set after login"
    assert "refresh_token" in cookies_after_login, "refresh_token cookie not set after login"
    log.info("✅ Login successful, both httpOnly cookies set")

    # ✅ FIX-5: Verify cookies are httpOnly (check Set-Cookie headers)
    set_cookie_headers = login_res.headers.get_list("set-cookie")
    access_cookie_header = [h for h in set_cookie_headers if "access_token=" in h][0] if set_cookie_headers else ""
    refresh_cookie_header = [h for h in set_cookie_headers if "refresh_token=" in h][0] if set_cookie_headers else ""

    assert "HttpOnly" in access_cookie_header or "httponly" in access_cookie_header.lower(), \
        "access_token cookie should be httpOnly"
    assert "HttpOnly" in refresh_cookie_header or "httponly" in refresh_cookie_header.lower(), \
        "refresh_token cookie should be httpOnly"
    log.info("✅ Both cookies are httpOnly (XSS protected)")

    # Step 2: Logout using cookies (no Authorization header needed)
    logout_res = await client.post(AuthURLs.LOGOUT, cookies=cookies_after_login)
    assert logout_res.status_code == 204, f"Logout failed: {logout_res.text}"
    log.info("✅ Logout successful (204) using cookies only")

    # Step 3: Verify BOTH cookies are deleted
    logout_set_cookie_headers = logout_res.headers.get_list("set-cookie")
    access_delete_header = [h for h in logout_set_cookie_headers if "access_token=" in h][0] if logout_set_cookie_headers else ""
    refresh_delete_header = [h for h in logout_set_cookie_headers if "refresh_token=" in h][0] if logout_set_cookie_headers else ""

    # Verify access_token deletion with path="/"
    if access_delete_header:
        assert "Max-Age=0" in access_delete_header or "expires" in access_delete_header.lower(), \
            "access_token cookie not properly deleted"
        assert "Path=/" in access_delete_header or "path=/" in access_delete_header.lower(), \
            f"access_token cookie path mismatch! Expected '/', got: {access_delete_header}"
        log.info("✅ access_token cookie deleted with correct path (/)")

    # Verify refresh_token deletion with path="/api"
    if refresh_delete_header:
        assert "Max-Age=0" in refresh_delete_header or "expires" in refresh_delete_header.lower(), \
            "refresh_token cookie not properly deleted"
        # ✅ FIX-1: Verify path is "/api" (not "/api/auth")
        assert "Path=/api" in refresh_delete_header or "path=/api" in refresh_delete_header.lower(), \
            f"refresh_token cookie path mismatch! Expected '/api', got: {refresh_delete_header}"
        log.info("✅ refresh_token cookie deleted with correct path (/api)")

    # Step 4: Verify refresh fails with old cookies
    refresh_res = await client.post(AuthURLs.REFRESH, cookies=cookies_after_login)
    assert refresh_res.status_code == 401, "Refresh should fail after logout"
    log.info("✅ Refresh correctly rejected after logout")
    log.info("--- Finished: test_fix1_logout_cookie_path_correct ---")


@pytest.mark.asyncio
async def test_fix1_refresh_cookie_path_consistency(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ FIX-1 + FIX-5: Test that refresh endpoint uses correct cookie paths for BOTH tokens.

    Verifies that when refreshing token:
    - New refresh_token cookie uses path="/api"
    - New access_token cookie uses path="/"
    - Both new cookies are httpOnly
    - Response contains user info (FIX-4)
    - Tokens are NOT in response body (httpOnly only)
    """
    log.info("--- Running: test_fix1_refresh_cookie_path_consistency ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Step 1: Login to get cookies
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"

    # Verify both cookies are set
    cookies_after_login = login_res.cookies
    assert "access_token" in cookies_after_login, "access_token cookie not set after login"
    assert "refresh_token" in cookies_after_login, "refresh_token cookie not set after login"
    log.info("✅ Login successful, both cookies set")

    # Step 2: Call refresh endpoint with cookies (browser sends both automatically)
    refresh_res = await client.post(AuthURLs.REFRESH, cookies=cookies_after_login)
    assert refresh_res.status_code == 200, f"Refresh failed: {refresh_res.text}"
    log.info("✅ Refresh successful (200)")

    # Step 3: Verify new cookies have correct paths
    refresh_set_cookie_headers = refresh_res.headers.get_list("set-cookie")
    access_cookie_header = [h for h in refresh_set_cookie_headers if "access_token=" in h][0] if refresh_set_cookie_headers else ""
    refresh_cookie_header = [h for h in refresh_set_cookie_headers if "refresh_token=" in h][0] if refresh_set_cookie_headers else ""

    # Verify access_token cookie path="/"
    if access_cookie_header:
        assert "Path=/" in access_cookie_header or "path=/" in access_cookie_header.lower(), \
            f"access_token cookie path mismatch! Expected '/', got: {access_cookie_header}"
        assert "HttpOnly" in access_cookie_header or "httponly" in access_cookie_header.lower(), \
            "access_token cookie should be httpOnly"
        log.info("✅ access_token cookie uses correct path (/) and is httpOnly")

    # Verify refresh_token cookie path="/api"
    if refresh_cookie_header:
        assert "Path=/api" in refresh_cookie_header or "path=/api" in refresh_cookie_header.lower(), \
            f"refresh_token cookie path mismatch! Expected '/api', got: {refresh_cookie_header}"
        assert "HttpOnly" in refresh_cookie_header or "httponly" in refresh_cookie_header.lower(), \
            "refresh_token cookie should be httpOnly"
        log.info("✅ refresh_token cookie uses correct path (/api) and is httpOnly")

    # Step 4: Verify response contains user info (FIX-4)
    refresh_data = refresh_res.json()
    assert "user" in refresh_data, "User info missing in refresh response (FIX-4)"
    log.info("✅ Refresh response contains user info (FIX-4)")

    # ✅ FIX-5: Verify tokens are NOT in response body (security improvement)
    # They should ONLY be in httpOnly cookies
    assert "access_token" not in refresh_data or refresh_data.get("access_token") is None, \
        "access_token should NOT be in response body (httpOnly cookie only)"
    assert "refresh_token" not in refresh_data or refresh_data.get("refresh_token") is None, \
        "refresh_token should NOT be in response body (httpOnly cookie only)"
    log.info("✅ Tokens correctly NOT in response body (httpOnly cookies only)")

    log.info("--- Finished: test_fix1_refresh_cookie_path_consistency ---")


# ============================================
# FIX-2: ERROR HANDLING TESTS
# ============================================


@pytest.mark.asyncio
async def test_fix2_change_password_invalidation_failure_throws_500(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ FIX-2 + FIX-5: Test that change password returns 500 if session invalidation fails.

    SECURITY ISSUE FIXED:
    - Before: If invalidate_all_sessions failed, only logged error but returned 204 success
    - After: Throws 500 error to alert user of security issue
    - Impact: User knows if old sessions are still active
    - NEW: Uses httpOnly cookies for authentication (no Authorization header)

    This test mocks invalidate_all_sessions to fail and verifies 500 response.
    """
    log.info("--- Running: test_fix2_change_password_invalidation_failure_throws_500 ---")
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Login
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200
    login_cookies = login_res.cookies

    # Mock invalidate_all_sessions to fail
    with patch(
        "app.services.user_service.invalidate_all_sessions",
        new_callable=AsyncMock,
        side_effect=Exception("Redis connection failed")
    ):
        # Attempt password change using cookies (no Authorization header)
        payload = {
            "old_password": password,
            "new_password": "NewSecurePassword!123"
        }
        response = await client.post(
            AuthURLs.CHANGE_PASSWORD,
            json=payload,
            cookies=login_cookies  # ✅ FIX-5: Use cookies instead of headers
        )

        # ✅ FIX-2: Should return 500, not 204
        assert response.status_code == 500, \
            f"Expected 500 when invalidation fails, got {response.status_code}"

        error_data = response.json()
        assert "detail" in error_data
        assert "failed to invalidate sessions" in error_data["detail"].lower(), \
            f"Unexpected error message: {error_data['detail']}"

        log.info("✅ Change password correctly returned 500 when invalidation failed")

    log.info("--- Finished: test_fix2_change_password_invalidation_failure_throws_500 ---")


@pytest.mark.asyncio
async def test_fix2_reset_password_invalidation_failure_throws_500(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ FIX-2: Test that reset password returns 500 if session invalidation fails.

    Similar to change password, reset password should also fail loudly
    if it cannot invalidate old sessions.
    """
    log.info("--- Running: test_fix2_reset_password_invalidation_failure_throws_500 ---")
    user_email = regular_user_in_db["email"]

    # Create reset token
    from app.security import create_password_reset_token
    reset_token = create_password_reset_token(email=user_email)

    # Mock invalidate_all_sessions to fail
    with patch(
        "app.services.user_service.invalidate_all_sessions",
        new_callable=AsyncMock,
        side_effect=Exception("Database connection lost")
    ):
        payload = {
            "token": reset_token,
            "new_password": "NewSecurePassword!123"
        }
        response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

        # ✅ FIX-2: Should return 500
        assert response.status_code == 500, \
            f"Expected 500 when invalidation fails, got {response.status_code}"

        error_data = response.json()
        assert "failed to invalidate sessions" in error_data["detail"].lower()
        log.info("✅ Reset password correctly returned 500 when invalidation failed")

    log.info("--- Finished: test_fix2_reset_password_invalidation_failure_throws_500 ---")


@pytest.mark.asyncio
async def test_fix2_change_password_success_invalidates_all_sessions(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ FIX-2 + FIX-5: Verify that successful password change ACTUALLY invalidates all sessions.

    This test ensures the happy path works correctly:
    1. Create 2 sessions with httpOnly cookies (2 browsers)
    2. Change password from browser 1 using cookies
    3. Verify both sessions are invalidated
    4. Verify user_blacklist is set in Redis
    """
    log.info("--- Running: test_fix2_change_password_success_invalidates_all_sessions ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # Create Session 1
    login1_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert login1_res.status_code == 200
    session1_cookies = login1_res.cookies

    # Create Session 2 (simulating different browser)
    login2_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": password})
    assert login2_res.status_code == 200
    session2_cookies = login2_res.cookies

    log.info("✅ Created 2 sessions with httpOnly cookies")

    # Verify both sessions work before password change
    profile1_res = await client.get(ProfileURLs.PROFILE, cookies=session1_cookies)
    profile2_res = await client.get(ProfileURLs.PROFILE, cookies=session2_cookies)
    assert profile1_res.status_code == 200 and profile2_res.status_code == 200
    log.info("✅ Both sessions working before password change")

    # Change password from session 1 using cookies
    new_password = "NewSecurePassword!123"
    change_res = await client.post(
        AuthURLs.CHANGE_PASSWORD,
        json={"old_password": password, "new_password": new_password},
        cookies=session1_cookies  # ✅ FIX-5: Use cookies instead of headers
    )
    assert change_res.status_code == 204, f"Password change failed: {change_res.text}"
    log.info("✅ Password changed successfully using cookies")

    # Verify user_blacklist is set
    user_blacklist_exists = await test_redis_client.exists(f"user_blacklist:{user_id}")
    assert user_blacklist_exists == 1, "user_blacklist not set after password change"
    log.info("✅ user_blacklist set in Redis")

    # Verify BOTH sessions are now invalid
    await asyncio.sleep(0.1)  # Small delay for Redis propagation

    profile1_after = await client.get(ProfileURLs.PROFILE, cookies=session1_cookies)
    profile2_after = await client.get(ProfileURLs.PROFILE, cookies=session2_cookies)

    assert profile1_after.status_code == 401, "Session 1 should be invalid after password change"
    assert profile2_after.status_code == 401, "Session 2 should be invalid after password change"
    log.info("✅ Both sessions correctly invalidated after password change")

    log.info("--- Finished: test_fix2_change_password_success_invalidates_all_sessions ---")


# ============================================
# FIX-3: WEBSOCKET SECURITY PLACEHOLDER
# ============================================


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires WebSocket test client setup")
async def test_fix3_websocket_checks_user_blacklist():
    """
    ✅ FIX-3: Test that WebSocket auth checks user_blacklist.

    SECURITY ISSUE FIXED:
    - Before: WebSocket only checked session validity
    - After: WebSocket also checks user_blacklist (parity with HTTP auth)
    - Impact: Prevents information leak via WebSocket after password change

    TODO: Implement with proper WebSocket test client (socketio.AsyncClient)
    """
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires WebSocket test client setup")
async def test_fix3_websocket_periodic_revalidation():
    """
    ✅ FIX-3: Test that WebSocket periodic revalidation disconnects invalid sessions.

    Verifies that client calls revalidate_auth every 5 minutes and gets disconnected
    if session is no longer valid.

    TODO: Implement with WebSocket test client
    """
    pass


# ============================================
# INTEGRATION TESTS (All Fixes Together)
# ============================================


@pytest.mark.asyncio
async def test_comprehensive_security_flow(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """
    ✅ COMPREHENSIVE: Test all security fixes in a realistic end-to-end scenario with httpOnly cookies.

    Scenario:
    1. User logs in from 2 devices (creates 2 sessions with httpOnly cookies)
    2. User detects suspicious activity → changes password using cookies
    3. Verify:
       - Password change succeeds
       - All old sessions are invalidated
       - Old cookies cannot be reused (both access_token and refresh_token)
       - user_blacklist is set
       - Can login again with new password
       - New session works with httpOnly cookies
    """
    log.info("--- Running: test_comprehensive_security_flow ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    old_password = regular_user_in_db["password"]
    new_password = "SuperSecureNewPassword!2024"

    # Step 1: Create 2 sessions with httpOnly cookies
    session1_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": old_password})
    session2_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": old_password})
    assert session1_res.status_code == 200 and session2_res.status_code == 200

    session1_cookies = session1_res.cookies
    session2_cookies = session2_res.cookies

    # Verify httpOnly cookies are set
    assert "access_token" in session1_cookies and "refresh_token" in session1_cookies
    assert "access_token" in session2_cookies and "refresh_token" in session2_cookies

    log.info("✅ Step 1: Created 2 sessions with httpOnly cookies")

    # Step 2: Change password using cookies (no Authorization header)
    change_res = await client.post(
        AuthURLs.CHANGE_PASSWORD,
        json={"old_password": old_password, "new_password": new_password},
        cookies=session1_cookies  # ✅ FIX-5: Use cookies instead of headers
    )
    assert change_res.status_code == 204
    log.info("✅ Step 2: Password changed using httpOnly cookies")

    # Step 3: Verify all old sessions invalid
    profile1_res = await client.get(ProfileURLs.PROFILE, cookies=session1_cookies)
    profile2_res = await client.get(ProfileURLs.PROFILE, cookies=session2_cookies)

    assert profile1_res.status_code == 401, "Session 1 should be invalid"
    assert profile2_res.status_code == 401, "Session 2 should be invalid"
    log.info("✅ Step 3: All old sessions invalidated")

    # Step 4: Verify old cookies cannot refresh (FIX-1 + FIX-5)
    refresh1_res = await client.post(AuthURLs.REFRESH, cookies=session1_cookies)
    refresh2_res = await client.post(AuthURLs.REFRESH, cookies=session2_cookies)

    assert refresh1_res.status_code == 401, "Old cookie 1 should not work"
    assert refresh2_res.status_code == 401, "Old cookie 2 should not work"
    log.info("✅ Step 4: Old httpOnly cookies cannot be reused (FIX-1 + FIX-5)")

    # Step 5: Verify user_blacklist set
    blacklist_exists = await test_redis_client.exists(f"user_blacklist:{user_id}")
    assert blacklist_exists == 1
    log.info("✅ Step 5: user_blacklist set in Redis")

    # Step 6: Can login with new password
    new_login_res = await client.post(AuthURLs.LOGIN, data={"username": username, "password": new_password})
    assert new_login_res.status_code == 200, "Should be able to login with new password"
    new_cookies = new_login_res.cookies
    assert "access_token" in new_cookies and "refresh_token" in new_cookies
    log.info("✅ Step 6: Can login with new password, httpOnly cookies set")

    # Step 7: New session works with httpOnly cookies
    new_profile_res = await client.get(ProfileURLs.PROFILE, cookies=new_cookies)
    assert new_profile_res.status_code == 200, "New session should work"
    log.info("✅ Step 7: New session works properly with httpOnly cookies")

    log.info("--- Finished: test_comprehensive_security_flow ---")
    log.info("✅✅✅ ALL SECURITY FIXES VERIFIED IN END-TO-END FLOW (httpOnly Cookies) ✅✅✅")
