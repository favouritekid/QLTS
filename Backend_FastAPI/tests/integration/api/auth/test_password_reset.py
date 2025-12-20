# tests/integration/api/auth/test_password_reset.py
# -*- coding: utf-8 -*-
"""
✅ PASSWORD RESET API TESTS

Tests for password reset functionality:
- Forgot password (always returns 202 for security)
- Reset password with valid token
- Invalid/expired token handling
- Weak password validation

Note: Tests verify via API behavior, not direct DB checks (session isolation).
"""
import logging
from datetime import timedelta

import pytest
from httpx import AsyncClient, ASGITransport

from app.security import create_password_reset_token

try:
    from tests.fixtures.constants import AuthURLs, SecurityConstants, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# === Tests cho /forgot-password ===

@pytest.mark.asyncio
async def test_forgot_password_success(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Forgot password với email hợp lệ (202).
    
    Note: Always returns 202 for security (no user enumeration).
    We don't mock Celery - just verify API returns correct status.
    """
    log.info("--- Running: test_forgot_password_success ---")
    user_email = regular_user_in_db["email"]

    response = await client.post(AuthURLs.FORGOT_PASSWORD, json={"email": user_email})
    
    assert response.status_code == 202, f"Response: {response.text}"
    resp_data = response.json()
    assert "detail" in resp_data
    assert "password reset link will be sent" in resp_data["detail"]
    log.info("✅ Forgot password returned 202")
    log.info("--- Finished: test_forgot_password_success ---")


@pytest.mark.asyncio
async def test_forgot_password_email_not_found(client: AsyncClient):
    """
    ✅ TEST: Forgot password với email không tồn tại (vẫn 202).
    
    Security: Same response to prevent user enumeration.
    """
    log.info("--- Running: test_forgot_password_email_not_found ---")
    
    response = await client.post(
        AuthURLs.FORGOT_PASSWORD, 
        json={"email": TestUsers.NON_EXISTENT_EMAIL}
    )
    
    assert response.status_code == 202, f"Response: {response.text}"
    resp_data = response.json()
    assert "detail" in resp_data
    log.info("✅ Forgot password (non-existent) returned 202 (security)")
    log.info("--- Finished: test_forgot_password_email_not_found ---")


@pytest.mark.asyncio
async def test_forgot_password_invalid_email_format(client: AsyncClient):
    """
    ✅ TEST: Forgot password với email sai định dạng (422).
    """
    log.info("--- Running: test_forgot_password_invalid_email_format ---")
    
    response = await client.post(AuthURLs.FORGOT_PASSWORD, json={"email": "not-an-email"})
    
    assert response.status_code == 422, f"Response: {response.text}"
    log.info("✅ Invalid email format correctly blocked (422)")
    log.info("--- Finished: test_forgot_password_invalid_email_format ---")


# === Tests cho /reset-password ===

@pytest.mark.asyncio
async def test_reset_password_success(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Reset password thành công (200).
    
    Kiểm tra:
    1. Valid token accepted
    2. Login with new password works
    3. Login with old password fails
    """
    log.info("--- Running: test_reset_password_success ---")
    user_email = regular_user_in_db["email"]
    username = regular_user_in_db["username"]
    old_password = regular_user_in_db["password"]
    new_password = "ResetPasswordSuccessfully!1"

    # Create valid reset token
    valid_token = create_password_reset_token(email=user_email)
    log.info("Generated valid reset token")

    # Reset password
    payload = {"token": valid_token, "new_password": new_password}
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    assert response.status_code == 200, f"Response: {response.text}"
    resp_data = response.json()
    assert resp_data.get("email") == user_email
    assert "password_hash" not in resp_data
    log.info("✅ Reset password returned 200")

    # Verify via API: Login with new password works
    from app.main import fastapi_app
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as new_client:
        login_res = await new_client.post(AuthURLs.LOGIN, data={"username": username, "password": new_password})
        assert login_res.status_code == 200, f"Login with new password failed: {login_res.text}"
    log.info("✅ Login with new password successful")

    # Verify via API: Login with old password fails
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as old_client:
        old_login_res = await old_client.post(AuthURLs.LOGIN, data={"username": username, "password": old_password})
        assert old_login_res.status_code == 401, "Login with old password should fail"
    log.info("✅ Login with old password correctly rejected")

    log.info("--- Finished: test_reset_password_success ---")


@pytest.mark.asyncio
async def test_reset_password_invalid_token_string(client: AsyncClient):
    """
    ✅ TEST: Reset password với token không hợp lệ (401).
    """
    log.info("--- Running: test_reset_password_invalid_token_string ---")
    
    payload = {
        "token": SecurityConstants.INVALID_TOKEN_STRING,
        "new_password": "AnyValidPassword!1",
    }
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    assert response.status_code == 401, f"Response: {response.text}"
    log.info("✅ Invalid token correctly blocked (401)")
    log.info("--- Finished: test_reset_password_invalid_token_string ---")


@pytest.mark.asyncio
async def test_reset_password_expired_token(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Reset password với token đã hết hạn (401).
    """
    log.info("--- Running: test_reset_password_expired_token ---")
    user_email = regular_user_in_db["email"]

    # Create expired token manually
    from jose import jwt
    from datetime import datetime, timezone
    from app.config import settings
    
    expired_payload = {
        "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        "sub": user_email,
        "scope": "password_reset"
    }
    expired_token = jwt.encode(
        expired_payload, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )

    payload = {"token": expired_token, "new_password": "AnyValidPassword!1"}
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    assert response.status_code == 401, f"Response: {response.text}"
    log.info("✅ Expired token correctly blocked (401)")
    log.info("--- Finished: test_reset_password_expired_token ---")


@pytest.mark.asyncio
async def test_reset_password_weak_password(client: AsyncClient, regular_user_in_db: dict):
    """
    ✅ TEST: Reset password với mật khẩu mới yếu (422).
    """
    log.info("--- Running: test_reset_password_weak_password ---")
    user_email = regular_user_in_db["email"]
    valid_token = create_password_reset_token(email=user_email)

    payload = {"token": valid_token, "new_password": TestUsers.WEAK_PASSWORD}
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    assert response.status_code == 422, f"Response: {response.text}"
    log.info("✅ Weak password correctly blocked (422)")
    log.info("--- Finished: test_reset_password_weak_password ---")
