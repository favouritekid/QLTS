# tests/routers/test_password_reset_api.py
# -*- coding: utf-8 -*-
import pytest
import pytest_asyncio
from httpx import AsyncClient
import logging
# --- FIX 1: Import ANY ---
from unittest.mock import patch, AsyncMock, ANY
# --- FIX 2: Import datetime ---
from datetime import timedelta, datetime, timezone # Added datetime here

# Import các thành phần app
from app.database import AsyncSessionLocal
from app.models import User
from app.config import settings
from app.security import create_password_reset_token, verify_password # Import security functions

# Import constants
try:
    from ..fixtures.constants import (
        AuthURLs,
        TestUsers,
        SecurityConstants,
        NON_EXISTENT_ID # Dùng cho user không tồn tại khi reset
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)

# === Tests cho /forgot-password ===

@pytest.mark.asyncio
@patch('app.services.user_service.get_user_by_email', new_callable=AsyncMock)
@patch('app.services.user_service.send_password_reset_email_task.delay')
async def test_forgot_password_success(
    mock_celery_delay: AsyncMock,
    mock_get_user: AsyncMock,
    client: AsyncClient,
    regular_user_in_db: dict # Cần user này để mock_get_user trả về
):
    """Test POST /forgot-password - Thành công (202), Celery task được gọi."""
    log.info("--- Running: test_forgot_password_success ---")
    user_email = regular_user_in_db["email"]
    user_username = regular_user_in_db["username"]
    mock_user_obj = User(id=regular_user_in_db["id"], email=user_email, username=user_username)
    mock_get_user.return_value = mock_user_obj # Giả lập tìm thấy user

    # --- Action ---
    response = await client.post(AuthURLs.FORGOT_PASSWORD, json={"email": user_email})

    # --- Assert Response ---
    assert response.status_code == 202, f"Forgot Password Resp: {response.text}"
    resp_data = response.json()
    assert "msg" in resp_data
    assert "password reset link will be sent" in resp_data["msg"]
    log.info("Forgot password returned 202 with correct message.")

    # --- Assert Mock Calls (Side Effect) ---
    # --- FIX 1 Applied: Use ANY ---
    mock_get_user.assert_awaited_once_with(ANY, email=user_email)
    mock_celery_delay.assert_called_once()
    # Kiểm tra các tham số của Celery task
    call_args, call_kwargs = mock_celery_delay.call_args
    assert call_kwargs.get("email_to") == user_email
    assert call_kwargs.get("username") == user_username
    assert "reset_url" in call_kwargs
    assert f"{settings.FRONTEND_URL}/reset-password?token=" in call_kwargs["reset_url"]
    log.info("Celery task delay called once with correct arguments.")


@pytest.mark.asyncio
@patch('app.services.user_service.get_user_by_email', new_callable=AsyncMock, return_value=None) # Giả lập không tìm thấy user
@patch('app.services.user_service.send_password_reset_email_task.delay')
async def test_forgot_password_email_not_found(
    mock_celery_delay: AsyncMock,
    mock_get_user: AsyncMock,
    client: AsyncClient
):
    """Test POST /forgot-password - Email không tồn tại (vẫn 202), Celery KHÔNG được gọi."""
    log.info("--- Running: test_forgot_password_email_not_found ---")
    non_existent_email = TestUsers.NON_EXISTENT_EMAIL

    # --- Action ---
    response = await client.post(AuthURLs.FORGOT_PASSWORD, json={"email": non_existent_email})

    # --- Assert Response ---
    assert response.status_code == 202, f"Forgot Password (Not Found) Resp: {response.text}"
    resp_data = response.json()
    assert "msg" in resp_data
    assert "password reset link will be sent" in resp_data["msg"] # Message giống hệt
    log.info("Forgot password (email not found) returned 202 with correct message.")

    # --- Assert Mock Calls ---
    # --- FIX 1 Applied: Use ANY ---
    mock_get_user.assert_awaited_once_with(ANY, email=non_existent_email)
    mock_celery_delay.assert_not_called() # Quan trọng: Không được gọi Celery
    log.info("Celery task delay correctly NOT called.")


@pytest.mark.asyncio
async def test_forgot_password_invalid_email_format(client: AsyncClient):
    """Test POST /forgot-password - Email sai định dạng (422)."""
    log.info("--- Running: test_forgot_password_invalid_email_format ---")
    invalid_email = "not-an-email"

    # --- Action ---
    response = await client.post(AuthURLs.FORGOT_PASSWORD, json={"email": invalid_email})

    # --- Assert 422 Validation Error ---
    assert response.status_code == 422, f"Invalid Email Format Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data and error_data["detail"] == "Validation Error"
    assert "errors" in error_data and isinstance(error_data["errors"], list)
    found_error = False
    for err in error_data["errors"]:
        if err.get("field") == "body -> email" and "value is not a valid email address" in err.get("message", ""):
            found_error = True
            break
    assert found_error, "Email validation error message not found in 422 response"
    log.info("Invalid email format correctly blocked (422).")


# === Tests cho /reset-password ===

@pytest.mark.asyncio
async def test_reset_password_success(client: AsyncClient, regular_user_in_db: dict):
    """Test POST /reset-password - Reset thành công (200), kiểm tra DB và login mới."""
    log.info("--- Running: test_reset_password_success ---")
    user_id = regular_user_in_db["id"]
    user_email = regular_user_in_db["email"]
    username = regular_user_in_db["username"]
    old_password = regular_user_in_db["password"]
    new_password = "ResetPasswordSuccessfully!1" # Đảm bảo đủ mạnh

    # --- Setup: Tạo token reset hợp lệ ---
    valid_token = create_password_reset_token(email=user_email)
    log.info("Generated valid reset token.")

    # --- Action ---
    # Note: Backend không cần confirm_new_password nữa
    payload = {
        "token": valid_token,
        "new_password": new_password
    }
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    # --- Assert Response ---
    assert response.status_code == 200, f"Reset Password Resp: {response.text}"
    resp_data = response.json()
    assert isinstance(resp_data, dict)
    assert resp_data.get("id") == user_id
    assert resp_data.get("email") == user_email
    assert "password_hash" not in resp_data # Không lộ hash
    log.info("Reset password successful (200). Response verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None
        assert verify_password(new_password, db_user.password_hash), "New password hash mismatch in DB"
        assert not verify_password(old_password, db_user.password_hash), "Old password should no longer be valid"
    log.info("Database state verified: New hash saved.")

    # --- Assert Side Effect (Login với mật khẩu mới) ---
    log.info("Attempting login with new password...")
    login_data = {"username": username, "password": new_password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Login with new password failed: {login_res.text}"
    log.info("Login with NEW password successful.")


@pytest.mark.asyncio
async def test_reset_password_invalid_token_string(client: AsyncClient):
    """Test POST /reset-password - Token string không hợp lệ (401 InvalidToken)."""
    log.info("--- Running: test_reset_password_invalid_token_string ---")
    new_password = "AnyValidPassword!1"
    payload = {
        "token": SecurityConstants.INVALID_TOKEN_STRING, # Dùng constant
        "new_password": new_password
    }
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Invalid Token Resp: {response.text}" # Handler ném InvalidToken (401)
    error_data = response.json()
    assert "detail" in error_data
    assert "Could not validate credentials" in error_data["detail"] # Message từ InvalidToken handler
    log.info("Invalid token string correctly blocked (401).")


@pytest.mark.asyncio
async def test_reset_password_expired_token(client: AsyncClient, regular_user_in_db: dict):
    """Test POST /reset-password - Token đã hết hạn (401 InvalidToken)."""
    log.info("--- Running: test_reset_password_expired_token ---")
    user_email = regular_user_in_db["email"]
    new_password = "AnyValidPassword!1"

    # --- Setup: Tạo token hết hạn ---
    # --- FIX 2 Applied: Use imported datetime ---
    with patch('app.security.datetime') as mock_dt:
        mock_dt.now.return_value = datetime.now(timezone.utc) - timedelta(hours=1) # Giả lập thời gian là 1h trước
        expired_token_negative_delta = create_password_reset_token(email=user_email)

    payload = {
        "token": expired_token_negative_delta,
        "new_password": new_password
    }
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Expired Token Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert "Could not validate credentials" in error_data["detail"] # Lỗi do verify_password_reset_token trả về None
    log.info("Expired token correctly blocked (401).")


@pytest.mark.asyncio
async def test_reset_password_user_not_found_for_token(client: AsyncClient, regular_user_in_db: dict):
    """Test POST /reset-password - Token hợp lệ nhưng user đã bị xóa (404)."""
    log.info("--- Running: test_reset_password_user_not_found_for_token ---")
    user_id = regular_user_in_db["id"]
    user_email = regular_user_in_db["email"]
    new_password = "AnyValidPassword!1"

    # --- Setup: Tạo token hợp lệ, sau đó xóa user ---
    valid_token = create_password_reset_token(email=user_email)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user_to_delete = await session.get(User, user_id)
            if user_to_delete:
                await session.delete(user_to_delete)
    log.info(f"User {user_id} deleted after generating token.")

    payload = {
        "token": valid_token,
        "new_password": new_password
    }
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    # --- Assert Error Response ---
    assert response.status_code == 404, f"User Not Found Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert "User associated with this token not found" in error_data["detail"] # Message từ service
    log.info("Reset password for deleted user correctly blocked (404).")


@pytest.mark.asyncio
async def test_reset_password_weak_password(client: AsyncClient, regular_user_in_db: dict):
    """Test POST /reset-password - Mật khẩu mới yếu (422)."""
    log.info("--- Running: test_reset_password_weak_password ---")
    user_email = regular_user_in_db["email"]
    valid_token = create_password_reset_token(email=user_email)
    weak_password = TestUsers.WEAK_PASSWORD

    payload = {
        "token": valid_token,
        "new_password": weak_password
    }
    response = await client.post(AuthURLs.RESET_PASSWORD, json=payload)

    # --- Assert 422 Validation Error ---
    assert response.status_code == 422, f"Weak Password Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data and error_data["detail"] == "Validation Error"
    assert "errors" in error_data and isinstance(error_data["errors"], list)
    found_error = False
    for err in error_data["errors"]:
        if err.get("field") == "body -> new_password":
            found_error = True
            assert ("at least 8 characters" in err.get("message", "") or "Password must contain" in err.get("message", ""))
            break
    assert found_error, "Weak password validation error not found"
    log.info("Weak new password correctly blocked (422).")


# NOTE: Test này đã bị DISABLE vì backend không còn validate confirm_new_password
# Password matching được validate ở frontend (client-side) only
# @pytest.mark.asyncio
# async def test_reset_password_mismatched_passwords(client: AsyncClient, regular_user_in_db: dict):
#     """Test POST /reset-password - Mật khẩu mới không khớp (422)."""
#     # Test này không còn áp dụng vì backend không nhận confirm_new_password
#     pass