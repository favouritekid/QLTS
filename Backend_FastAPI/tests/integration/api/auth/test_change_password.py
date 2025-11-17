# tests/routers/test_change_password_api.py
# -*- coding: utf-8 -*-
import logging

import pytest
import pytest_asyncio  # Import nếu chưa có
from httpx import AsyncClient
from jose import jwt  # Cần để decode lấy JTI

from app.config import settings

# Import các thành phần app
from app.database import AsyncSessionLocal
from app.models import User
from app.security import (  # Cần verify_password và decode
    decode_token_for_invalidation,
    verify_password,
)

# Import constants
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from tests.fixtures.constants import ProfileURLs  # Cần ProfileURLs để test token cũ
    from tests.fixtures.constants import (
        SecurityConstants,  # Không cần trực tiếp nhưng có thể hữu ích
    )
    from tests.fixtures.constants import (
        AuthURLs,
        TestUsers,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_change_password_success(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """
    Test Đổi mật khẩu thành công (204 No Content).
    Kiểm tra DB state (hash mới, active_jti=None), Redis state (user_blacklist, refresh_jti xóa),
    và token cũ bị vô hiệu hóa.
    """
    log.info("--- Running: test_change_password_success ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    old_password = regular_user_in_db["password"]
    # Đảm bảo mật khẩu mới đủ mạnh và khác mật khẩu cũ
    new_password = "NewStrongPasswordChanged!123"
    assert old_password != new_password

    # --- Bước 1: Login để lấy token cũ ---
    login_data = {"username": username, "password": old_password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Initial login failed: {login_res.text}"
    tokens = login_res.json()
    old_access_token = tokens["access_token"]
    old_refresh_token = tokens["refresh_token"]  # Lấy cả refresh token cũ
    old_headers = {"Authorization": f"Bearer {old_access_token}"}
    log.info("Logged in successfully with old password.")

    # Lấy JTI của refresh token cũ từ Redis để kiểm tra blacklist sau này
    old_refresh_jti = await test_redis_client.get(f"refresh_jti:{user_id}")
    assert (
        old_refresh_jti is not None
    ), "Refresh JTI should exist in Redis before password change"
    log.debug(f"Old refresh JTI found in Redis: {old_refresh_jti}")

    # --- Bước 2: Gọi API đổi mật khẩu ---
    # Note: Backend không cần confirm_new_password nữa
    payload = {"old_password": old_password, "new_password": new_password}
    response = await client.post(
        AuthURLs.CHANGE_PASSWORD, json=payload, headers=old_headers
    )  # Dùng constant URL

    # --- Assert Response ---
    assert (
        response.status_code == 204
    ), f"Change Password Resp: Status {response.status_code}, Text: {response.text}"  # No Content on success
    # Không có body content để kiểm tra
    log.info("Change password API returned 204 No Content as expected.")

    # --- Bước 3: Kiểm tra Side Effects ---
    log.info("Verifying side effects...")

    # 3.1: Assert DB State (hash mới, active_jti=None)
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert (
            db_user is not None
        ), f"User {user_id} not found in DB after password change"
        assert db_user.active_jti is None, "active_jti should be set to None in DB"
        assert verify_password(
            new_password, db_user.password_hash
        ), "New password hash mismatch in DB"
        # Kiểm tra mật khẩu cũ không còn hợp lệ
        assert not verify_password(
            old_password, db_user.password_hash
        ), "Old password should no longer be valid"
    log.info("DB state verified: New hash saved, active_jti is None.")

    # 3.2: Assert Redis State (user_blacklist tồn tại, refresh_jti xóa)
    user_blacklist_key = f"user_blacklist:{user_id}"
    is_user_blacklisted = await test_redis_client.exists(user_blacklist_key)
    assert (
        is_user_blacklisted == 1
    ), f"User ID {user_id} should be in user_blacklist in Redis"
    # Kiểm tra TTL của user_blacklist (phải > 0 và hợp lý)
    blacklist_ttl = await test_redis_client.ttl(user_blacklist_key)
    expected_max_ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60)
    assert (
        blacklist_ttl > 0 and abs(blacklist_ttl - expected_max_ttl) <= 10
    ), f"Unexpected TTL for user_blacklist: {blacklist_ttl}"
    log.info(f"Redis check OK: {user_blacklist_key} exists with TTL ~{blacklist_ttl}s.")

    refresh_jti_key = f"refresh_jti:{user_id}"
    stored_refresh_jti = await test_redis_client.get(refresh_jti_key)
    assert (
        stored_refresh_jti is None
    ), f"Redis key '{refresh_jti_key}' should be deleted after password change"
    log.info(f"Redis check OK: {refresh_jti_key} deleted.")

    # (Tùy chọn) Kiểm tra refresh JTI CŨ có bị blacklist không (logic service có thể làm)
    # is_old_refresh_blacklisted = await test_redis_client.exists(f"blacklist:{old_refresh_jti}")
    # assert is_old_refresh_blacklisted == 1, "Old refresh JTI should also be blacklisted"
    # log.info("Redis check OK: Old refresh JTI blacklisted.")

    # --- Bước 4: Kiểm tra login lại bằng mật khẩu MỚI -> Thành công ---
    log.info("Attempting login with NEW password...")
    new_login_data = {"username": username, "password": new_password}
    new_login_res = await client.post(AuthURLs.LOGIN, data=new_login_data)
    assert (
        new_login_res.status_code == 200
    ), f"Login with new password failed: {new_login_res.text}"
    log.info("Login with NEW password successful.")

    # --- Bước 5: Kiểm tra dùng token CŨ -> Thất bại (do user blacklist) ---
    log.info("Attempting to use OLD access token...")
    # Sử dụng endpoint cần xác thực, ví dụ /api/profile
    profile_res = await client.get(
        ProfileURLs.PROFILE, headers=old_headers
    )  # Dùng constant URL
    assert (
        profile_res.status_code == 401
    ), "Old access token should be invalid (due to user blacklist)"
    error_data_old_token = profile_res.json()
    assert "detail" in error_data_old_token
    assert "Could not validate credentials" in error_data_old_token["detail"]
    log.info("Using OLD access token correctly failed with 401 and specific message.")

    log.info("--- Finished: test_change_password_success ---")


@pytest.mark.asyncio
async def test_change_password_incorrect_old_password(
    client: AsyncClient, regular_user_token_headers: dict
):
    """Test Đổi mật khẩu với mật khẩu cũ không đúng (400 Bad Request)."""
    log.info("--- Running: test_change_password_incorrect_old_password ---")
    payload = {
        "old_password": TestUsers.INVALID_PASSWORD,  # Dùng constant
        "new_password": "NewStrongPassword!123",
    }
    response = await client.post(
        AuthURLs.CHANGE_PASSWORD, json=payload, headers=regular_user_token_headers
    )

    # --- Assert Error Response ---
    assert response.status_code == 400, f"Resp: {response.text}"  # Bad Request
    error_data = response.json()
    assert "detail" in error_data
    assert (
        error_data["detail"] == "Incorrect old password"
    )  # Message lỗi cụ thể từ service
    log.info("Incorrect old password correctly blocked (400) with specific message.")
    log.info("--- Finished: test_change_password_incorrect_old_password ---")


# NOTE: Test này đã bị DISABLE vì backend không còn validate confirm_new_password
# Password matching được validate ở frontend (client-side) only
# @pytest.mark.asyncio
# async def test_change_password_mismatched_new_passwords(client: AsyncClient, regular_user_token_headers: dict, regular_user_in_db: dict):
#     """Test Đổi mật khẩu với mật khẩu mới không khớp (422)."""
#     # Test này không còn áp dụng vì backend không nhận confirm_new_password
#     pass


@pytest.mark.asyncio
async def test_change_password_weak_new_password(
    client: AsyncClient, regular_user_token_headers: dict, regular_user_in_db: dict
):
    """Test Đổi mật khẩu với mật khẩu mới quá yếu (422)."""
    log.info("--- Running: test_change_password_weak_new_password ---")
    payload = {
        "old_password": regular_user_in_db["password"],
        "new_password": TestUsers.WEAK_PASSWORD,  # Dùng constant
    }
    response = await client.post(
        AuthURLs.CHANGE_PASSWORD, json=payload, headers=regular_user_token_headers
    )

    # --- Assert 422 Validation Error ---
    assert response.status_code == 422, f"Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data  # Kiểm tra key "detail"
    assert "errors" in error_data and isinstance(error_data["errors"], list)

    found_error = False
    for error in error_data["errors"]:
        assert isinstance(error, dict)
        assert "field" in error and "message" in error  # Handler trả về 'field'

        # --- SỬA DÒNG IF Ở ĐÂY ---
        # Kiểm tra giá trị của key 'field'
        if error.get("field") == "body -> new_password":
            # --- KẾT THÚC SỬA ---
            found_error = True
            # Kiểm tra message lỗi (độ dài hoặc độ phức tạp)
            assert "at least 8 characters" in error.get(
                "message", ""
            ) or "Password must contain" in error.get(
                "message", ""
            ), f"Unexpected validation message for weak password: {error.get('message')}"
            break  # Tìm thấy lỗi, thoát vòng lặp
    assert (
        found_error
    ), "Validation error for weak 'new_password' field not found in errors list"
    log.info("Weak new password correctly blocked (422) with detailed error.")
    log.info("--- Finished: test_change_password_weak_new_password ---")


@pytest.mark.asyncio
async def test_change_password_unauthenticated(client: AsyncClient):
    """Test Đổi mật khẩu khi chưa đăng nhập (401)."""
    log.info("--- Running: test_change_password_unauthenticated ---")
    payload = {"old_password": "any_old", "new_password": "NewStrongPassword!123"}
    response = await client.post(
        AuthURLs.CHANGE_PASSWORD, json=payload
    )  # Không có headers

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Resp: {response.text}"  # Unauthorized
    error_data = response.json()
    assert "detail" in error_data
    assert (
        error_data["detail"] == "Not authenticated"
    )  # Message mặc định của FastAPI/Starlette
    log.info("Unauthenticated access correctly blocked (401) with default message.")
    log.info("--- Finished: test_change_password_unauthenticated ---")
