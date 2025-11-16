# tests/services/test_user_service.py
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.user import User
from app.services import user_service
from app.utils.exceptions import InvalidCredentials

# === ĐỊNH NGHĨA HẰNG SỐ CẤU HÌNH ===

# Thay thế bằng hash bạn vừa tạo cho "password123!"
REAL_PASSWORD_HASH_FOR_TESTUSER = (
    "$2b$12$BvEj6Ldp4bfmCgqAikhEa.QE9TCNY7scpcDtvlJDGB4se.7rSZQdS"
)

# Thay thế bằng dummy hash bạn vừa tạo hoặc lấy từ app/security.py
DUMMY_BCRYPT_HASH = "$2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62"

TEST_USERNAME = "testuser"
VALID_PASSWORD = "password123!"
INVALID_PASSWORD = "wrongpassword"
NON_EXISTENT_USERNAME = "nosuchuser"

# === KẾT THÚC ĐỊNH NGHĨA ===

# --- (Cấu hình logging nếu cần) ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


@pytest.mark.asyncio
async def test_authenticate_user_valid_credentials(mocker):
    """
    Kiểm tra xác thực thành công với username và password hợp lệ.
    """
    test_name = "test_authenticate_user_valid_credentials"
    logging.info(f"--- Starting test: {test_name} ---")

    # 1. Chuẩn bị Mock Data (SỬ DỤNG HẰNG SỐ)
    mock_user = User(
        id=1,
        username=TEST_USERNAME,
        email="test@example.com",
        password_hash=REAL_PASSWORD_HASH_FOR_TESTUSER,  # <-- Sử dụng hằng số
        role="user",
        status="active",
    )
    logging.info(f"[{test_name}] Mock user created: {mock_user.username}")

    # 2. Mock các dependencies
    mock_get_user = AsyncMock(return_value=mock_user)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)
    logging.info(f"[{test_name}] Patched get_user_by_username")

    mock_verify = MagicMock(return_value=True)
    mocker.patch("app.services.user_service.verify_password", mock_verify)
    logging.info(f"[{test_name}] Patched verify_password to return True")

    # 3. Gọi hàm cần test (SỬ DỤNG HẰNG SỐ)
    logging.info(f"[{test_name}] Calling authenticate_user with valid credentials...")
    authenticated_user = await user_service.authenticate_user(
        db=AsyncMock(),
        username=TEST_USERNAME,  # <-- Sử dụng hằng số
        password=VALID_PASSWORD,  # <-- Sử dụng hằng số
    )
    logging.info(f"[{test_name}] authenticate_user call returned.")

    # 4. Assert kết quả
    assert authenticated_user is not None
    assert authenticated_user.username == TEST_USERNAME  # <-- Sử dụng hằng số
    logging.info(f"[{test_name}] User assertion successful.")

    # Assert các mock đã được gọi đúng (SỬ DỤNG HẰNG SỐ)
    mock_get_user.assert_awaited_once_with(mocker.ANY, TEST_USERNAME)
    mock_verify.assert_called_once_with(VALID_PASSWORD, REAL_PASSWORD_HASH_FOR_TESTUSER)
    logging.info(f"[{test_name}] Mock call assertions successful.")
    logging.info(f"--- Finished test: {test_name} ---")


@pytest.mark.asyncio
async def test_authenticate_user_invalid_password(mocker):
    """
    Kiểm tra xác thực thất bại với password không hợp lệ.
    """
    test_name = "test_authenticate_user_invalid_password"
    logging.info(f"--- Starting test: {test_name} ---")

    # 1. Chuẩn bị Mock Data (SỬ DỤNG HẰNG SỐ)
    mock_user = User(
        id=1,
        username=TEST_USERNAME,
        email="test@example.com",
        password_hash=REAL_PASSWORD_HASH_FOR_TESTUSER,  # <-- Sử dụng hằng số
        role="user",
        status="active",
    )
    logging.info(f"[{test_name}] Mock user created: {mock_user.username}")

    # 2. Mock dependencies
    mock_get_user = AsyncMock(return_value=mock_user)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)
    logging.info(f"[{test_name}] Patched get_user_by_username")

    mock_verify = MagicMock(return_value=False)
    mocker.patch("app.services.user_service.verify_password", mock_verify)
    logging.info(f"[{test_name}] Patched verify_password to return False")

    # 3. Gọi hàm và Assert Exception (SỬ DỤNG HẰNG SỐ)
    logging.info(f"[{test_name}] Calling authenticate_user with invalid password...")
    with pytest.raises(InvalidCredentials) as exc_info:
        await user_service.authenticate_user(
            db=AsyncMock(),
            username=TEST_USERNAME,  # <-- Sử dụng hằng số
            password=INVALID_PASSWORD,  # <-- Sử dụng hằng số
        )
    logging.info(f"[{test_name}] InvalidCredentials raised as expected.")

    assert exc_info.value.detail == "Incorrect username or password."
    logging.info(f"[{test_name}] Exception detail assertion successful.")

    # 4. Assert mock calls (SỬ DỤNG HẰNG SỐ)
    mock_get_user.assert_awaited_once_with(mocker.ANY, TEST_USERNAME)
    mock_verify.assert_called_once_with(
        INVALID_PASSWORD, REAL_PASSWORD_HASH_FOR_TESTUSER
    )
    logging.info(f"[{test_name}] Mock call assertions successful (verify was called).")
    logging.info(f"--- Finished test: {test_name} ---")


@pytest.mark.asyncio
async def test_authenticate_user_not_found(mocker):
    """
    Kiểm tra xác thực thất bại khi username không tồn tại.
    """
    test_name = "test_authenticate_user_not_found"
    logging.info(f"--- Starting test: {test_name} ---")

    # 1. Mock dependencies
    mock_get_user = AsyncMock(return_value=None)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)
    logging.info(f"[{test_name}] Patched get_user_by_username to return None")

    mock_verify = MagicMock(return_value=False)
    mocker.patch("app.services.user_service.verify_password", mock_verify)
    logging.info(f"[{test_name}] Patched verify_password (will be called with dummy)")

    # 2. Gọi hàm và Assert Exception (SỬ DỤNG HẰNG SỐ)
    logging.info(
        f"[{test_name}] Calling authenticate_user with non-existent username..."
    )
    with pytest.raises(InvalidCredentials) as exc_info:
        await user_service.authenticate_user(
            db=AsyncMock(),
            username=NON_EXISTENT_USERNAME,  # <-- Sử dụng hằng số
            password="anypassword",
        )
    logging.info(f"[{test_name}] InvalidCredentials raised as expected.")

    assert exc_info.value.detail == "Incorrect username or password."
    logging.info(f"[{test_name}] Exception detail assertion successful.")

    # 3. Assert mock calls (SỬ DỤNG HẰNG SỐ)
    mock_get_user.assert_awaited_once_with(mocker.ANY, NON_EXISTENT_USERNAME)
    mock_verify.assert_called_once_with(
        "anypassword", DUMMY_BCRYPT_HASH
    )  # <-- Sử dụng hằng số
    logging.info(
        f"[{test_name}] Mock call assertions successful (verify called with dummy hash)."
    )
    logging.info(f"--- Finished test: {test_name} ---")
