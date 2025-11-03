# tests/routers/test_profile_api.py
# -*- coding: utf-8 -*-
import io
from unittest.mock import patch, AsyncMock
from fastapi import UploadFile, HTTPException, status
from app.config import settings # Cần settings để check message lỗi 413
import pytest
import pytest_asyncio # Import nếu chưa có
from httpx import AsyncClient
import logging
from sqlalchemy import select # Import select để truy vấn DB

# Import các thành phần app
from app.models import User
from app.database import AsyncSessionLocal
from app.security import verify_password # Có thể cần nếu test đổi pass qua profile (hiện tại không có)

# Import constants
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from ..fixtures.constants import (
        ProfileURLs,
        TestUsers,
        AuthURLs, # Cần AuthURLs nếu test unauthenticated cần login
        # NON_EXISTENT_ID # Không cần ID không tồn tại cho profile của chính user
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)

# === GET /api/profile ===

@pytest.mark.asyncio
async def test_get_profile_success(client: AsyncClient, regular_user_token_headers: dict, regular_user_in_db: dict):
    """Test GET /api/profile - Lấy profile thành công, kiểm tra nội dung response."""
    log.info("--- Running: test_get_profile_success ---")
    response = await client.get(ProfileURLs.PROFILE, headers=regular_user_token_headers) # Dùng constant URL

    # --- Assert Response ---
    assert response.status_code == 200, f"GET Profile Resp: {response.text}"
    profile_data = response.json()
    assert isinstance(profile_data, dict), "Response body should be a dictionary (User object)"

    # 1. Kiểm tra các trường dữ liệu chính khớp với fixture
    assert profile_data.get("username") == regular_user_in_db["username"], "Username mismatch"
    assert profile_data.get("email") == regular_user_in_db["email"], "Email mismatch"
    assert profile_data.get("id") == regular_user_in_db["id"], "User ID mismatch"
    assert profile_data.get("role") == TestUsers.REGULAR["role"], "Role mismatch" # Kiểm tra role từ constant
    assert profile_data.get("status") == TestUsers.REGULAR["status"], "Status mismatch" # Kiểm tra status

    # 2. Kiểm tra các trường có thể null ban đầu (tùy thuộc fixture)
    assert profile_data.get("full_name") is None, "Expected initial full_name to be None"
    assert profile_data.get("phone_number") is None, "Expected initial phone_number to be None"
    assert profile_data.get("avatar_url") is None, "Expected initial avatar_url to be None"

    # 3. Đảm bảo thông tin nhạy cảm không bị rò rỉ
    assert "password_hash" not in profile_data, "Password hash leaked in profile response"
    assert "active_jti" not in profile_data, "Active JTI leaked in profile response"

    log.info("Get profile successful. Response structure and content verified.")
    log.info("--- Finished: test_get_profile_success ---")


@pytest.mark.asyncio
async def test_get_profile_unauthenticated(client: AsyncClient):
    """Test GET /api/profile - Chưa đăng nhập (401)."""
    log.info("--- Running: test_get_profile_unauthenticated ---")
    response = await client.get(ProfileURLs.PROFILE) # Không có headers

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Unauth Resp: {response.text}" # Unauthorized
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Not authenticated" # Message mặc định
    log.info("Unauthenticated access correctly denied (401) with default message.")
    log.info("--- Finished: test_get_profile_unauthenticated ---")

# === PUT /api/profile ===

@pytest.mark.asyncio
async def test_update_profile_success(client: AsyncClient, regular_user_token_headers: dict, regular_user_in_db: dict):
    """Test PUT /api/profile - Cập nhật thành công, kiểm tra response và DB state."""
    log.info("--- Running: test_update_profile_success ---")
    user_id = regular_user_in_db["id"]
    # Endpoint dùng Form data
    update_data_form = {
        "full_name": "Updated Full Name Here",
        "phone_number": "0987654321",
        "email": "updated.profile.email@example.com" # Email mới hợp lệ
    }
    response = await client.put(ProfileURLs.PROFILE, data=update_data_form, headers=regular_user_token_headers)

    # --- Assert Response ---
    assert response.status_code == 200, f"Update Profile Resp: {response.text}"
    updated_profile_resp = response.json()
    assert isinstance(updated_profile_resp, dict)
    assert updated_profile_resp.get("id") == user_id
    assert updated_profile_resp.get("full_name") == update_data_form["full_name"]
    assert updated_profile_resp.get("phone_number") == update_data_form["phone_number"]
    assert updated_profile_resp.get("email") == update_data_form["email"]
    # Kiểm tra các trường không đổi
    assert updated_profile_resp.get("username") == regular_user_in_db["username"]
    assert "password_hash" not in updated_profile_resp
    log.info("Profile updated successfully. Response verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None, "User not found in DB after profile update"
        assert db_user.full_name == update_data_form["full_name"]
        assert db_user.phone_number == update_data_form["phone_number"]
        assert db_user.email == update_data_form["email"]
        # Đảm bảo các trường khác không bị thay đổi ngoài ý muốn
        assert db_user.username == regular_user_in_db["username"]
        assert db_user.role == TestUsers.REGULAR["role"]
    log.info("Database state verified after profile update.")

    log.info("--- Finished: test_update_profile_success ---")


@pytest.mark.asyncio
async def test_update_profile_duplicate_email(client: AsyncClient, admin_user_in_db: dict, regular_user_token_headers: dict):
    """Test PUT /api/profile - Cập nhật email trùng với user khác (409)."""
    log.info("--- Running: test_update_profile_duplicate_email ---")
    # Email của admin user (tạo bởi fixture admin_user_in_db)
    duplicate_email = TestUsers.ADMIN["email"]
    update_data_form = {
        "email": duplicate_email
    }
    response = await client.put(ProfileURLs.PROFILE, data=update_data_form, headers=regular_user_token_headers)

    # --- Assert Error Response ---
    assert response.status_code == 409, f"Dupe Email Resp: {response.text}" # Conflict
    error_data = response.json()
    assert "detail" in error_data
    # Kiểm tra message lỗi cụ thể từ service update_profile
    assert error_data["detail"] == "Email already registered by another user"
    log.info("Duplicate email correctly blocked (409) with specific message.")
    log.info("--- Finished: test_update_profile_duplicate_email ---")


# tests/routers/test_profile_api.py

@pytest.mark.asyncio
async def test_update_profile_invalid_email(client: AsyncClient, regular_user_token_headers: dict):
    """Test PUT /api/profile - Cập nhật email sai định dạng (422)."""
    log.info("--- Running: test_update_profile_invalid_email ---")
    invalid_email_str = "not-a-valid-email"
    update_data_form = {
        "email": invalid_email_str
    }
    response = await client.put(ProfileURLs.PROFILE, data=update_data_form, headers=regular_user_token_headers)

    # --- Assert 422 Validation Error ---
    assert response.status_code == 422, f"Invalid Email Resp: {response.text}" # Unprocessable Entity
    error_data = response.json()

    # --- SỬA ASSERTIONS Ở ĐÂY ---
    # Kiểm tra lỗi validation NÉM TỪ BÊN TRONG ENDPOINT (do dùng Form data)
    # Handler trả về lỗi 422 với message trong 'detail'
    assert "detail" in error_data, "422 response missing 'detail'"
    assert isinstance(error_data["detail"], str), "'detail' should be a string for this error type"

    # Kiểm tra message lỗi cụ thể
    assert f"Invalid email format: {invalid_email_str}" in error_data["detail"]
    assert "value is not a valid email address" in error_data["detail"] # Kiểm tra phần lỗi từ Pydantic/EmailStr
    # Bỏ qua kiểm tra 'errors' list vì nó không tồn tại trong trường hợp này
    # assert "errors" in error_data and isinstance(error_data["errors"], list)
    # --- KẾT THÚC SỬA ---

    log.info("Invalid email format correctly blocked (422) with detailed error in 'detail' field.")
    log.info("--- Finished: test_update_profile_invalid_email ---")


@pytest.mark.asyncio
async def test_update_profile_only_some_fields(client: AsyncClient, regular_user_token_headers: dict, regular_user_in_db: dict):
    """Test PUT /api/profile - Chỉ cập nhật một vài trường, kiểm tra response và DB."""
    log.info("--- Running: test_update_profile_only_some_fields ---")
    user_id = regular_user_in_db["id"]
    original_email = regular_user_in_db["email"] # Lưu lại email gốc
    update_data_form = {
        "phone_number": "555-1234" # Chỉ cập nhật số điện thoại
    }
    response = await client.put(ProfileURLs.PROFILE, data=update_data_form, headers=regular_user_token_headers)

    # --- Assert Response ---
    assert response.status_code == 200, f"Partial Update Resp: {response.text}"
    updated_profile_resp = response.json()
    assert updated_profile_resp.get("phone_number") == update_data_form["phone_number"]
    # Các trường khác phải giữ nguyên giá trị ban đầu
    assert updated_profile_resp.get("full_name") is None # Ban đầu là None
    assert updated_profile_resp.get("email") == original_email # Email không đổi
    log.info("Profile partial update successful. Response verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None
        assert db_user.phone_number == update_data_form["phone_number"]
        assert db_user.full_name is None # Vẫn là None
        assert db_user.email == original_email # Email không đổi
    log.info("Database state verified after partial update.")
    log.info("--- Finished: test_update_profile_only_some_fields ---")

# === Helper tạo mock file (có thể đặt ở đây hoặc trong conftest) ===
def create_mock_avatar(filename="avatar.png", content=b"fake_image_bytes", content_type="image/png"):
    """Tạo một tuple file mock_in_memory để dùng với httpx files=..."""
    return (filename, io.BytesIO(content), content_type)

# ===============================================================
# === MỤC 4.2: TESTS API UPLOAD AVATAR (PROFILE) ===
# ===============================================================

@pytest.mark.asyncio
# Mock hàm save_avatar được gọi BÊN TRONG user_service (mà profile_service gọi)
@patch("app.services.user_service.file_helpers.save_avatar", new_callable=AsyncMock)
async def test_update_profile_with_avatar_success(
    mock_save_avatar: AsyncMock,
    client: AsyncClient,
    regular_user_token_headers: dict,
    regular_user_in_db: dict
):
    """Test 4.2: PUT /api/profile - Cập nhật profile thành công KÈM AVATAR."""
    log.info("--- Running: test_update_profile_with_avatar_success ---")
    user_id = regular_user_in_db["id"]
    
    # 1. Setup Mock
    mock_avatar_url = "/static/avatars/mock_profile_avatar.png"
    mock_save_avatar.return_value = mock_avatar_url

    # Lấy avatar_url cũ (ban đầu là None)
    async with AsyncSessionLocal() as session:
        user_before = await session.get(User, user_id)
        old_avatar_url = user_before.avatar_url
    assert old_avatar_url is None, "User fixture should not have an avatar initially"

    # 2. Chuẩn bị data
    update_data_form = {"full_name": "My New Profile Name"}
    mock_file = create_mock_avatar(filename="profile.png")

    # 3. Action
    response = await client.put(
        ProfileURLs.PROFILE,
        data=update_data_form,
        files={"avatar": mock_file},
        headers=regular_user_token_headers
    )

    # 4. Assert Response
    assert response.status_code == 200, f"Resp: {response.text}"
    updated_profile = response.json()
    assert updated_profile.get("avatar_url") == mock_avatar_url, "Avatar URL không khớp trong response"
    assert updated_profile.get("full_name") == update_data_form["full_name"]
    log.info("Update profile with avatar successful. Response content verified.")

    # 5. Assert Mock Call (Side Effect)
    # Service 'update_profile' gọi 'save_avatar'
    mock_save_avatar.assert_awaited_once()
    assert mock_save_avatar.await_args[0][0].filename == "profile.png"
    assert mock_save_avatar.await_args[1].get("old_avatar_url") == old_avatar_url 
    log.info("Mock save_avatar called correctly.")

    # 6. Assert DB State
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None
        assert db_user.avatar_url == mock_avatar_url, "Avatar URL không được cập nhật đúng trong DB"
        assert db_user.full_name == update_data_form["full_name"]
    log.info("Database state verified: avatar_url updated.")


@pytest.mark.asyncio
@patch("app.services.user_service.file_helpers.save_avatar", new_callable=AsyncMock)
async def test_update_profile_avatar_bad_file_type(
    mock_save_avatar: AsyncMock,
    client: AsyncClient,
    regular_user_token_headers: dict,
    regular_user_in_db: dict
):
    """Test 4.2: PUT /api/profile - Lỗi 400 File Type Không Hợp Lệ."""
    log.info("--- Running: test_update_profile_avatar_bad_file_type ---")
    user_id = regular_user_in_db["id"]
    original_full_name = regular_user_in_db.get("full_name") # Là None

    # 1. Setup Mock (Ném lỗi 400)
    error_detail = "Unsupported file format. Allowed: jpg, jpeg, png."
    mock_save_avatar.side_effect = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail
    )
    
    # 2. Chuẩn bị data
    mock_file = create_mock_avatar(filename="file.txt", content_type="text/plain")
    update_data = {"full_name": "Should Not Update Name"}

    # 3. Action
    response = await client.put(
        ProfileURLs.PROFILE,
        data=update_data,
        files={"avatar": mock_file},
        headers=regular_user_token_headers
    )

    # 4. Assert Error Response
    assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == error_detail, "Message lỗi 400 không chính xác"
    log.info("Update profile with bad file type correctly failed (400) with specific message.")

    # 5. Assert DB State (Không thay đổi)
    async with AsyncSessionLocal() as session:
        db_user = await session.get(User, user_id)
        assert db_user is not None
        # Tên không được cập nhật
        assert db_user.full_name == original_full_name # Phải là giá trị gốc
        # Avatar không được cập nhật
        assert db_user.avatar_url is None
    log.info("Database state verified: No changes were made (transaction rolled back).")