# tests/integration/api/auth/test_change_password.py
# -*- coding: utf-8 -*-
"""
✅ CHANGE PASSWORD API TESTS (Updated for httpOnly Cookie Pattern)

Tests for change password functionality:
- Success case with session invalidation
- Incorrect old password rejection  
- Weak password validation
- Unauthenticated access rejection
"""
import logging

import pytest
from httpx import AsyncClient, ASGITransport

try:
    from tests.fixtures.constants import AuthURLs, ProfileURLs, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_change_password_success(
    client: AsyncClient, regular_user_in_db: dict
):
    """
    ✅ TEST: Đổi mật khẩu thành công (204 No Content).
    
    Kiểm tra:
    1. Login và lấy cookies
    2. Change password returns 204
    3. New password works for login
    4. Old password no longer works
    5. Old token no longer works
    """
    log.info("--- Running: test_change_password_success ---")
    username = regular_user_in_db["username"]
    old_password = regular_user_in_db["password"]
    new_password = "NewStrongPasswordChanged!123"

    # Step 1: Login để lấy cookies
    login_data = {"username": username, "password": old_password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Initial login failed: {login_res.text}"
    
    old_access_token = login_res.cookies.get("access_token")
    assert old_access_token, "access_token cookie not set after login"
    log.info("✅ Logged in successfully with old password")

    # Step 2: Gọi API đổi mật khẩu
    payload = {"old_password": old_password, "new_password": new_password}
    response = await client.post(AuthURLs.CHANGE_PASSWORD, json=payload)

    assert response.status_code == 204, f"Change Password: Status {response.status_code}, Text: {response.text}"
    log.info("✅ Change password returned 204 No Content")

    # Step 3: Login với mật khẩu MỚI (verify password was changed)
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        new_login_res = await new_client.post(AuthURLs.LOGIN, data={"username": username, "password": new_password})
        assert new_login_res.status_code == 200, f"Login with new password failed: {new_login_res.text}"
    log.info("✅ Login with NEW password successful")

    # Step 4: Login với mật khẩu CŨ fails
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as old_pw_client:
        old_login_res = await old_pw_client.post(AuthURLs.LOGIN, data={"username": username, "password": old_password})
        assert old_login_res.status_code == 401, "Login with OLD password should fail"
    log.info("✅ Login with OLD password correctly rejected")

    # Step 5: Token CŨ không hoạt động
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as old_token_client:
        old_token_client.cookies.set("access_token", old_access_token)
        profile_res = await old_token_client.get(ProfileURLs.PROFILE)
        assert profile_res.status_code == 401, "Old token should be invalid"
    log.info("✅ Old access token correctly rejected (401)")

    log.info("--- Finished: test_change_password_success ---")


@pytest.mark.asyncio
async def test_change_password_incorrect_old_password(
    client: AsyncClient, regular_user_token_headers: dict
):
    """
    ✅ TEST: Đổi mật khẩu với mật khẩu cũ không đúng (400 Bad Request).
    """
    log.info("--- Running: test_change_password_incorrect_old_password ---")
    payload = {
        "old_password": TestUsers.INVALID_PASSWORD,
        "new_password": "NewStrongPassword!123",
    }
    response = await client.post(
        AuthURLs.CHANGE_PASSWORD, json=payload, headers=regular_user_token_headers
    )

    assert response.status_code == 400, f"Response: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Incorrect old password"
    log.info("✅ Incorrect old password correctly blocked (400)")
    log.info("--- Finished: test_change_password_incorrect_old_password ---")


@pytest.mark.asyncio
async def test_change_password_weak_new_password(
    client: AsyncClient, regular_user_token_headers: dict, regular_user_in_db: dict
):
    """
    ✅ TEST: Đổi mật khẩu với mật khẩu mới quá yếu (422).
    """
    log.info("--- Running: test_change_password_weak_new_password ---")
    payload = {
        "old_password": regular_user_in_db["password"],
        "new_password": TestUsers.WEAK_PASSWORD,
    }
    response = await client.post(
        AuthURLs.CHANGE_PASSWORD, json=payload, headers=regular_user_token_headers
    )

    assert response.status_code == 422, f"Response: {response.text}"
    log.info("✅ Weak password correctly blocked (422)")
    log.info("--- Finished: test_change_password_weak_new_password ---")


@pytest.mark.asyncio
async def test_change_password_unauthenticated(client: AsyncClient):
    """
    ✅ TEST: Đổi mật khẩu khi chưa đăng nhập (401).
    """
    log.info("--- Running: test_change_password_unauthenticated ---")
    
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        payload = {"old_password": "any_old", "new_password": "NewStrongPassword!123"}
        response = await new_client.post(AuthURLs.CHANGE_PASSWORD, json=payload)

    assert response.status_code == 401, f"Response: {response.text}"
    log.info("✅ Unauthenticated access correctly blocked (401)")
    log.info("--- Finished: test_change_password_unauthenticated ---")
