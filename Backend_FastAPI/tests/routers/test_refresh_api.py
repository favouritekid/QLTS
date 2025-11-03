# tests/routers/test_refresh_api.py
# -*- coding: utf-8 -*-
import pytest
import pytest_asyncio # Import nếu chưa có
from httpx import AsyncClient, Response # Import Response để kiểm tra kiểu
import logging
import asyncio # Cần cho test concurrent requests
from jose import jwt, JWTError # Cần để decode token mới
from datetime import timedelta, datetime, timezone # Cần datetime và timezone

# Import các thành phần app
from app.database import AsyncSessionLocal
from app.models import User
from app.config import settings
from app.security import decode_token_for_invalidation, create_refresh_token # Cần create_refresh_token

# Import constants
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from ..fixtures.constants import (
        AuthURLs,
        TestUsers,
        ProfileURLs, # Cần để test token mới/cũ
        SecurityConstants
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)

# --- Helper Function ---
async def get_tokens(client: AsyncClient, username: str, password: str) -> dict:
    """Helper để login và trả về dict chứa tokens."""
    login_data = {"username": username, "password": password}
    login_res = await client.post(AuthURLs.LOGIN, data=login_data)
    # Ném lỗi nếu login thất bại, giúp debug dễ hơn
    if login_res.status_code != 200:
        pytest.fail(f"Helper get_tokens failed: Login returned {login_res.status_code} - {login_res.text}")
    return login_res.json()

# --- Tests ---

@pytest.mark.asyncio
async def test_refresh_success(client: AsyncClient, regular_user_in_db: dict, test_redis_client):
    """
    Test Refresh token thành công (200 OK).
    Kiểm tra response, token rotation, DB state (active_jti), Redis state (blacklists, refresh_jti),
    và hiệu lực của token mới/cũ.
    """
    log.info("--- Running: test_refresh_success ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # --- Bước 1: Login lấy tokens ban đầu ---
    initial_tokens = await get_tokens(client, username, password)
    initial_refresh_token = initial_tokens["refresh_token"]
    initial_access_token = initial_tokens["access_token"]
    log.info("Logged in initially.")

    # Lấy JTI của tokens cũ để kiểm tra blacklist
    initial_access_jti, _ = decode_token_for_invalidation(initial_access_token)
    initial_refresh_jti, initial_refresh_ttl = decode_token_for_invalidation(initial_refresh_token)
    assert initial_access_jti, "Could not decode initial access JTI"
    assert initial_refresh_jti, "Could not decode initial refresh JTI"
    assert initial_refresh_ttl is not None and initial_refresh_ttl > 0, "Could not decode initial refresh TTL"
    log.debug(f"Initial Tokens - Access JTI: {initial_access_jti}, Refresh JTI: {initial_refresh_jti}")

    # --- Bước 2: Gọi API refresh ---
    log.info(f"Calling refresh endpoint: {AuthURLs.REFRESH}")
    response = await client.post(AuthURLs.REFRESH, json={"refresh_token": initial_refresh_token})

    # --- Assert Response ---
    assert response.status_code == 200, f"Refresh Resp: {response.text}"
    new_tokens = response.json()
    assert isinstance(new_tokens, dict), "Refresh response body should be a dictionary"
    assert "access_token" in new_tokens, "Refresh response missing 'access_token'"
    assert "refresh_token" in new_tokens, "Refresh response missing 'refresh_token'"
    assert new_tokens.get("token_type") == "bearer", "Incorrect token_type in refresh response"
    # Kiểm tra token rotation (tokens mới phải khác tokens cũ)
    new_access_token = new_tokens["access_token"]
    new_refresh_token = new_tokens["refresh_token"]
    assert new_access_token != initial_access_token, "New access token should be different from old one"
    assert new_refresh_token != initial_refresh_token, "New refresh token should be different from old one"
    log.info("Refresh successful (200). Response structure and token rotation verified.")

    # --- Assert Token Payloads Mới ---
    try:
        new_access_payload = jwt.decode(new_access_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        new_refresh_payload = jwt.decode(new_refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        new_access_jti = new_access_payload.get("jti")
        new_refresh_jti = new_refresh_payload.get("jti")
        assert new_access_jti and new_refresh_jti, "New tokens missing JTI"
        assert new_access_payload.get("sub") == username
        assert new_access_payload.get("type") == "access"
        assert new_refresh_payload.get("sub") == username
        assert new_refresh_payload.get("type") == "refresh"
        log.info("New token payloads decoded and verified.")
        log.debug(f"New Tokens - Access JTI: {new_access_jti}, Refresh JTI: {new_refresh_jti}")
    except JWTError as e:
        pytest.fail(f"Failed to decode new tokens: {e}")

    # --- Bước 3: Kiểm tra Side Effects ---
    log.info("Verifying side effects...")

    # 3.1: Assert DB State (active_jti khớp JTI access token MỚI)
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None, f"User {user_id} not found in DB after refresh"
        assert db_user.active_jti == new_access_jti, "active_jti in DB should match NEW access token JTI"
    log.info(f"DB state verified: active_jti matches NEW access JTI '{new_access_jti}'.")

    # 3.2: Assert Redis State
    #   a) Refresh Token JTI CŨ bị blacklist
    old_refresh_blacklist_key = f"blacklist:{initial_refresh_jti}"
    is_old_refresh_blacklisted = await test_redis_client.exists(old_refresh_blacklist_key)
    assert is_old_refresh_blacklisted == 1, f"Old refresh JTI '{initial_refresh_jti}' should be blacklisted"
    # Blacklist này thường có TTL ngắn (ví dụ 300s)
    old_blacklist_ttl = await test_redis_client.ttl(old_refresh_blacklist_key)
    assert old_blacklist_ttl > 0 and old_blacklist_ttl <= 300, f"Unexpected TTL for old refresh JTI blacklist: {old_blacklist_ttl}"
    log.info(f"Redis check OK: Old refresh JTI '{initial_refresh_jti}' blacklisted with TTL ~{old_blacklist_ttl}s.")

    #   b) Key `refresh_jti:{user_id}` chứa JTI MỚI
    refresh_jti_key = f"refresh_jti:{user_id}"
    stored_new_refresh_jti = await test_redis_client.get(refresh_jti_key)
    assert stored_new_refresh_jti == new_refresh_jti, "Redis should store the NEW refresh JTI"
    # Kiểm tra TTL của key này (phải xấp xỉ TTL của refresh token MỚI)
    _, new_refresh_ttl_expected = decode_token_for_invalidation(new_refresh_token)
    new_refresh_key_ttl_actual = await test_redis_client.ttl(refresh_jti_key)
    assert new_refresh_key_ttl_actual > 0 and abs(new_refresh_key_ttl_actual - new_refresh_ttl_expected) <= 10, \
           f"Unexpected TTL for new refresh JTI key: {new_refresh_key_ttl_actual} (expected ~{new_refresh_ttl_expected})"
    log.info(f"Redis check OK: '{refresh_jti_key}' stores NEW refresh JTI '{new_refresh_jti}' with TTL ~{new_refresh_key_ttl_actual}s.")

    # --- Bước 4: Kiểm tra dùng Access Token MỚI -> Thành công ---
    log.info("Attempting to use NEW access token...")
    new_headers = {"Authorization": f"Bearer {new_access_token}"}
    profile_res_new = await client.get(ProfileURLs.PROFILE, headers=new_headers) # Dùng constant URL
    assert profile_res_new.status_code == 200, f"NEW access token should be valid, but got {profile_res_new.status_code}"
    log.info("Using NEW access token successful (200).")

    # --- Bước 5: Kiểm tra dùng Access Token CŨ -> Thất bại ---
    log.info("Attempting to use OLD access token...")
    old_headers = {"Authorization": f"Bearer {initial_access_token}"}
    profile_res_old = await client.get(ProfileURLs.PROFILE, headers=old_headers)
    # Lỗi do active_jti trong DB không khớp JTI của token cũ
    assert profile_res_old.status_code == 401, "OLD access token should be invalid after refresh"
    error_data_old_access = profile_res_old.json()
    assert "detail" in error_data_old_access
    assert "Could not validate credentials" in error_data_old_access["detail"]
    log.info("Using OLD access token correctly failed (401).")

    # --- Bước 6: Kiểm tra dùng Refresh Token CŨ -> Thất bại ---
    log.info("Attempting to reuse OLD refresh token...")
    reuse_response = await client.post(AuthURLs.REFRESH, json={"refresh_token": initial_refresh_token})
    # Lỗi do JTI cũ đã bị blacklist
    assert reuse_response.status_code == 401, "Reusing OLD refresh token should fail (401)"
    error_data_old_refresh = reuse_response.json()
    assert "detail" in error_data_old_refresh
    assert "Invalid or expired refresh token" in error_data_old_refresh["detail"]
    log.info("Reusing OLD refresh token correctly failed (401).")

    log.info("--- Finished: test_refresh_success ---")


@pytest.mark.asyncio
async def test_refresh_invalid_token_string(client: AsyncClient):
    """Test Refresh với token không hợp lệ (chuỗi sai - 401), kiểm tra message lỗi."""
    log.info("--- Running: test_refresh_invalid_token_string ---")
    response = await client.post(AuthURLs.REFRESH, json={"refresh_token": SecurityConstants.INVALID_TOKEN_STRING}) # Dùng constant

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Invalid or expired refresh token" # Message lỗi cụ thể
    log.info("Refresh with invalid token string correctly failed (401) with specific message.")
    log.info("--- Finished: test_refresh_invalid_token_string ---")


@pytest.mark.asyncio
async def test_refresh_expired_token(client: AsyncClient, regular_user_in_db: dict):
    """Test Refresh với token đã hết hạn (401), kiểm tra message lỗi."""
    log.info("--- Running: test_refresh_expired_token ---")
    # Tạo một refresh token hết hạn ngay lập tức
    expired_token = create_refresh_token(
        data={"sub": regular_user_in_db["username"]},
        expires_delta=timedelta(seconds=-5) # Đảm bảo đã hết hạn
    )

    response = await client.post(AuthURLs.REFRESH, json={"refresh_token": expired_token})

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Invalid or expired refresh token" # Lỗi JWT decode trả về 401 này
    log.info("Refresh with expired token correctly failed (401) with specific message.")
    log.info("--- Finished: test_refresh_expired_token ---")


@pytest.mark.asyncio
async def test_refresh_blacklisted_token(client: AsyncClient, regular_user_in_db: dict, test_redis_client):
    """Test Refresh với token đã bị blacklist (ví dụ sau logout - 401), kiểm tra message lỗi."""
    log.info("--- Running: test_refresh_blacklisted_token ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # --- Login và Logout để blacklist token ---
    tokens = await get_tokens(client, username, password)
    refresh_token_to_blacklist = tokens["refresh_token"]
    access_token_for_logout = tokens["access_token"]
    refresh_jti, refresh_ttl = decode_token_for_invalidation(refresh_token_to_blacklist)
    assert refresh_jti and refresh_ttl, "Could not decode refresh token to blacklist"

    # Logout
    headers = {"Authorization": f"Bearer {access_token_for_logout}"}
    logout_res = await client.post(AuthURLs.LOGOUT, headers=headers)
    assert logout_res.status_code == 204, "Logout failed during setup"
    log.info("Logged out, tokens should be blacklisted.")

    # Kiểm tra lại là refresh JTI đã bị blacklist trong Redis
    is_blacklisted = await test_redis_client.exists(f"blacklist:{refresh_jti}")
    assert is_blacklisted == 1, f"Refresh JTI '{refresh_jti}' should be blacklisted after logout"

    # --- Thử refresh với token đã blacklist ---
    log.info("Attempting refresh with blacklisted token...")
    response = await client.post(AuthURLs.REFRESH, json={"refresh_token": refresh_token_to_blacklist})

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Invalid or expired refresh token" # Lỗi do blacklist check
    log.info("Refresh with blacklisted token correctly failed (401) with specific message.")

    log.info("--- Finished: test_refresh_blacklisted_token ---")


@pytest.mark.asyncio
async def test_refresh_concurrent_requests(client: AsyncClient, regular_user_in_db: dict, test_redis_client):
    """
    Test Gửi nhiều request refresh đồng thời với cùng một token.
    Kiểm tra chỉ 1 request thành công, các request khác thất bại (401/400),
    token gốc bị blacklist, Redis và DB chứa JTI mới nhất.
    """
    log.info("--- Running: test_refresh_concurrent_requests ---")
    user_id = regular_user_in_db["id"]
    username = regular_user_in_db["username"]
    password = regular_user_in_db["password"]

    # --- Login lấy refresh token ---
    tokens = await get_tokens(client, username, password)
    concurrent_refresh_token = tokens["refresh_token"]
    concurrent_refresh_jti, _ = decode_token_for_invalidation(concurrent_refresh_token)
    assert concurrent_refresh_jti, "Could not decode concurrent refresh JTI"
    log.info(f"Using refresh token with JTI: {concurrent_refresh_jti} for concurrent test")

    # --- Chuẩn bị nhiều coroutine gọi API refresh ---
    num_concurrent_requests = 5
    tasks = []
    for i in range(num_concurrent_requests):
        tasks.append(client.post(AuthURLs.REFRESH, json={"refresh_token": concurrent_refresh_token}))

    # --- Thực thi đồng thời ---
    log.info(f"Sending {num_concurrent_requests} concurrent refresh requests...")
    # Chạy và lấy kết quả (bao gồm cả exceptions)
    results: List[Response | Exception] = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Phân tích kết quả ---
    success_count = 0
    fail_401_400_count = 0 # Đếm cả 401 và 400 (do JTI mismatch)
    other_failures = []
    new_access_jti_from_success = None
    new_refresh_jti_from_success = None

    log.info("Analyzing results...")
    for i, result in enumerate(results):
        log.debug(f"Result {i+1}: Type={type(result)}")
        if isinstance(result, Response):
            log.info(f"Request {i+1} Status Code: {result.status_code}")
            if result.status_code == 200:
                success_count += 1
                # Lưu lại JTI mới từ request thành công
                try:
                    new_tokens = result.json()
                    new_at = new_tokens.get("access_token")
                    new_rt = new_tokens.get("refresh_token")
                    if new_at:
                        jti_at, _ = decode_token_for_invalidation(new_at)
                        if jti_at: new_access_jti_from_success = jti_at
                    if new_rt:
                        jti_rt, _ = decode_token_for_invalidation(new_rt)
                        if jti_rt: new_refresh_jti_from_success = jti_rt
                except Exception as e:
                    log.warning(f"Could not parse new JTIs from successful response {i+1}: {e}")
            elif result.status_code in [400, 401]: # Lỗi dự kiến do race condition/blacklist
                fail_401_400_count += 1
                # Kiểm tra message lỗi cụ thể
                try:
                    error_detail = result.json().get("detail", "")
                    assert "Invalid or expired refresh token" in error_detail or \
                           "Could not validate credentials" in error_detail # Có thể là lỗi JTI mismatch từ service
                except Exception:
                     log.warning(f"Could not parse detail from failed response {i+1} ({result.status_code})")
            else:
                log.error(f"Request {i+1} unexpected status code: {result.status_code} - {result.text}")
                other_failures.append(result)
        elif isinstance(result, Exception):
            log.error(f"Request {i+1} raised exception: {result}")
            other_failures.append(result)
        else:
             log.error(f"Request {i+1} returned unexpected type: {type(result)}")
             other_failures.append(result)

    # --- Assert Kết Quả Thực Thi ---
    assert success_count == 1, f"Expected exactly 1 successful request, but got {success_count}"
    assert fail_401_400_count == num_concurrent_requests - 1, \
           f"Expected {num_concurrent_requests - 1} failed requests (400/401), but got {fail_401_400_count}"
    assert len(other_failures) == 0, f"Got unexpected failures or exceptions: {other_failures}"
    log.info(f"Concurrent execution result OK: {success_count} success, {fail_401_400_count} failures (400/401).")

    # --- Assert Side Effects Cuối Cùng ---
    # 1. Token gốc phải bị blacklist
    is_original_blacklisted = await test_redis_client.exists(f"blacklist:{concurrent_refresh_jti}")
    assert is_original_blacklisted == 1, f"Original refresh token JTI '{concurrent_refresh_jti}' should be blacklisted"
    log.info(f"Redis check OK: Original refresh JTI '{concurrent_refresh_jti}' is blacklisted.")

    # 2. Redis key và DB phải chứa JTI mới (từ request thành công duy nhất)
    assert new_access_jti_from_success is not None, "Could not extract new access JTI from successful response"
    assert new_refresh_jti_from_success is not None, "Could not extract new refresh JTI from successful response"

    stored_final_refresh_jti = await test_redis_client.get(f"refresh_jti:{user_id}")
    assert stored_final_refresh_jti == new_refresh_jti_from_success, "Redis should store the JTI from the single successful request"
    log.info(f"Redis check OK: refresh_jti:{user_id} stores the final correct JTI '{new_refresh_jti_from_success}'.")

    async with AsyncSessionLocal() as session:
        final_db_user = await session.get(User, user_id)
        assert final_db_user is not None
        assert final_db_user.active_jti == new_access_jti_from_success, "DB active_jti should match the JTI from the single successful request"
    log.info(f"DB check OK: active_jti stores the final correct JTI '{new_access_jti_from_success}'.")

    log.info("--- Finished: test_refresh_concurrent_requests ---")