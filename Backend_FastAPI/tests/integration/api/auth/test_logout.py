# tests/routers/test_logout_api.py
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
from app.security import decode_token_for_invalidation  # Cần để lấy JTI và TTL

# Import constants
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from ..fixtures.constants import (
        ProfileURLs,  # Cần ProfileURLs để test token sau logout
    )
    from ..fixtures.constants import (
        SecurityConstants,  # Không cần trực tiếp nhưng import sẵn
    )
    from ..fixtures.constants import (
        AuthURLs,
        TestUsers,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_logout_success(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """
    Test Logout thành công (204 No Content).
    Kiểm tra DB state (active_jti=None), Redis state (blacklists, refresh_jti xóa),
    và token cũ bị vô hiệu hóa.
    """
    log.info("--- Running: test_logout_success ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # --- Bước 1: Login để lấy token ---
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    tokens = login_res.json()
    access_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    log.info("Logged in successfully.")

    # Lấy JTI của access token và refresh token để kiểm tra blacklist sau
    access_jti, access_ttl = decode_token_for_invalidation(access_token)
    assert (
        access_jti and access_ttl is not None and access_ttl > 0
    ), "Could not decode access token JTI/TTL"

    refresh_jti_key = f"refresh_jti:{user_id}"
    refresh_jti_before_logout = await test_redis_client.get(refresh_jti_key)
    assert (
        refresh_jti_before_logout is not None
    ), "Refresh JTI should exist in Redis before logout"
    log.debug(
        f"Access JTI: {access_jti}, Refresh JTI before logout: {refresh_jti_before_logout}"
    )

    # --- Bước 2: Gọi API logout ---
    response = await client.post(AuthURLs.LOGOUT, headers=headers)  # Dùng constant URL

    # --- Assert Response ---
    assert (
        response.status_code == 204
    ), f"Logout Resp: Status {response.status_code}, Text: {response.text}"
    # Status 204 không có body content
    log.info("Logout API returned 204 No Content as expected.")

    # --- Bước 3: Kiểm tra Side Effects ---
    log.info("Verifying side effects...")

    # 3.1: Assert DB State (active_jti=None)
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None, f"User {user_id} not found in DB after logout"
        assert (
            db_user.active_jti is None
        ), "active_jti should be set to None in DB after logout"
    log.info("DB state verified: active_jti is None.")

    # 3.2: Assert Redis State (blacklists, refresh_jti xóa)
    access_blacklist_key = f"blacklist:{access_jti}"
    is_access_blacklisted = await test_redis_client.exists(access_blacklist_key)
    assert (
        is_access_blacklisted == 1
    ), f"Access JTI '{access_jti}' should be blacklisted in Redis"
    access_blacklist_ttl = await test_redis_client.ttl(access_blacklist_key)
    # TTL blacklist của access token phải gần bằng TTL gốc còn lại
    assert (
        access_blacklist_ttl > 0 and abs(access_blacklist_ttl - access_ttl) <= 10
    ), f"Unexpected TTL for access token blacklist: {access_blacklist_ttl} (original TTL ~{access_ttl})"
    log.info(
        f"Redis check OK: Access JTI '{access_jti}' is blacklisted with TTL ~{access_blacklist_ttl}s."
    )

    stored_refresh_jti_after = await test_redis_client.get(refresh_jti_key)
    assert (
        stored_refresh_jti_after is None
    ), f"Redis key '{refresh_jti_key}' should be deleted after logout"
    log.info(f"Redis check OK: '{refresh_jti_key}' deleted.")

    refresh_blacklist_key = f"blacklist:{refresh_jti_before_logout}"
    is_refresh_blacklisted = await test_redis_client.exists(refresh_blacklist_key)
    assert (
        is_refresh_blacklisted == 1
    ), f"Refresh JTI '{refresh_jti_before_logout}' should be blacklisted in Redis"
    refresh_blacklist_ttl = await test_redis_client.ttl(refresh_blacklist_key)
    # TTL blacklist của refresh token nên xấp xỉ TTL tối đa của refresh token
    expected_refresh_ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60)
    assert (
        refresh_blacklist_ttl > 0
        and abs(refresh_blacklist_ttl - expected_refresh_ttl) <= 10
    ), f"Unexpected TTL for refresh token blacklist: {refresh_blacklist_ttl}"
    log.info(
        f"Redis check OK: Refresh JTI '{refresh_jti_before_logout}' is blacklisted with TTL ~{refresh_blacklist_ttl}s."
    )

    # --- Bước 4: Kiểm tra dùng lại access token -> Thất bại ---
    log.info("Attempting to use the logged-out access token...")
    # Sử dụng endpoint cần xác thực, ví dụ /api/profile
    profile_res = await client.get(
        ProfileURLs.PROFILE, headers=headers
    )  # Dùng constant URL
    assert (
        profile_res.status_code == 401
    ), "Logged-out access token should result in 401"
    error_data_old_token = profile_res.json()
    assert "detail" in error_data_old_token
    # Lỗi do JTI bị blacklist ném ra từ get_current_user
    assert "Could not validate credentials" in error_data_old_token["detail"]
    log.info(
        "Using logged-out access token correctly failed with 401 and specific message."
    )

    log.info("--- Finished: test_logout_success ---")


@pytest.mark.asyncio
async def test_logout_unauthenticated(client: AsyncClient):
    """Test Logout khi chưa đăng nhập (401)."""
    log.info("--- Running: test_logout_unauthenticated ---")
    response = await client.post(AuthURLs.LOGOUT)  # Không có headers

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Resp: {response.text}"  # Unauthorized
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Not authenticated"  # Message mặc định
    log.info("Unauthenticated logout correctly blocked (401) with default message.")
    log.info("--- Finished: test_logout_unauthenticated ---")


@pytest.mark.asyncio
async def test_logout_twice_with_same_token(
    client: AsyncClient, regular_user_in_db: dict, test_redis_client
):
    """Test Logout 2 lần với cùng một token (Lần 1: 204, Lần 2: 401)."""
    log.info("--- Running: test_logout_twice_with_same_token ---")

    # --- Login ---
    login_data = {
        "username": regular_user_in_db["username"],
        "password": regular_user_in_db["password"],
    }
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res.status_code == 200
    tokens = login_res.json()
    access_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    log.info("Logged in.")

    # --- Logout lần 1 (Thành công) ---
    response1 = await client.post(AuthURLs.LOGOUT, headers=headers)
    assert response1.status_code == 204, "First logout should succeed (204)"
    log.info("First logout successful (204).")

    # --- Logout lần 2 (Thất bại vì token đã blacklist) ---
    log.info("Attempting second logout with the same token...")
    response2 = await client.post(AuthURLs.LOGOUT, headers=headers)

    # --- Assert Error Response (Lần 2) ---
    assert (
        response2.status_code == 401
    ), "Second logout with same token should fail (401)"
    error_data2 = response2.json()
    assert "detail" in error_data2
    # Lỗi do get_current_user phát hiện JTI đã blacklist
    assert "Could not validate credentials" in error_data2["detail"]
    log.info("Second logout correctly failed (401) with specific message.")

    log.info("--- Finished: test_logout_twice_with_same_token ---")
