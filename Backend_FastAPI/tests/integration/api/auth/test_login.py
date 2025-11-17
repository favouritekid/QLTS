# tests/services/test_user_service.py
# -*- coding: utf-8 -*-

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession  # Cần để type hint cho mock_db

from app.models.user import User

# Import các thành phần cần test và exception
from app.services import user_service
from app.utils.exceptions import InvalidCredentials

# Import constants
try:
    from tests.fixtures.constants import SecurityConstants, TestUsers
except ImportError:
    pytest.fail(
        "Could not import constants from tests.fixtures.constants. Please create the file."
    )

log = logging.getLogger(__name__)  # Khởi tạo logger

# === Bắt đầu các bài Test ===


@pytest.mark.asyncio
async def test_authenticate_user_valid_credentials(mocker):
    """
    Test authenticate_user: Xác thực thành công.
    Kiểm tra:
    1. Giá trị trả về (Return Value) là đúng đối tượng User.
    2. Mock calls (get_user, verify_password) được gọi chính xác.
    3. Trạng thái DB (mock): db.refresh được gọi.
    """
    log.info("--- Running: test_authenticate_user_valid_credentials ---")

    # 1. Chuẩn bị Mock Data (SỬ DỤNG HẰNG SỐ)
    user_data = TestUsers.DEFAULT
    mock_user = User(
        id=1,
        username=user_data["username"],
        email=user_data["email"],
        password_hash=user_data["real_hash"],  # <-- Dùng hash thật
        role=user_data["role"],
        status=user_data["status"],
    )
    log.info(f"Mock user created: {mock_user.username}")

    # 2. Mock các dependencies
    # Mock hàm service phụ thuộc
    mock_get_user = AsyncMock(return_value=mock_user)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)
    log.debug("Patched get_user_by_username")

    # Mock hàm security phụ thuộc
    mock_verify = MagicMock(return_value=True)
    mocker.patch("app.services.user_service.verify_password", mock_verify)
    log.debug("Patched verify_password to return True")

    # Mock DB session
    mock_db = AsyncMock(spec=AsyncSession)
    mock_db.refresh = AsyncMock(return_value=None)  # Cấu hình refresh
    log.debug("Mock AsyncSession created")

    # 3. Gọi hàm cần test
    log.info("Calling authenticate_user with valid credentials...")
    authenticated_user = await user_service.authenticate_user(
        db=mock_db,  # <-- Truyền mock_db
        username=user_data["username"],
        password=user_data["password"],
    )
    log.info("authenticate_user call returned.")

    # 4. Assert Return Value (Nội dung response)
    assert authenticated_user is not None, "Authenticated user should not be None"
    assert (
        authenticated_user == mock_user
    ), "Returned user object does not match mock user"
    assert authenticated_user.username == user_data["username"]
    log.info("Return value (User object) assertion successful.")

    # 5. Assert Mock Calls (Side effects/DB state)
    # Kiểm tra gọi hàm get_user_by_username
    mock_get_user.assert_awaited_once_with(mock_db, user_data["username"])
    # Kiểm tra gọi hàm verify_password
    mock_verify.assert_called_once_with(user_data["password"], user_data["real_hash"])
    # Kiểm tra Trạng thái Database (mock): db.refresh được gọi
    mock_db.refresh.assert_awaited_once_with(mock_user)
    log.info("Mock call (get_user, verify_password, db.refresh) assertions successful.")

    # 6. Assert Cache/Celery (Không áp dụng)
    # Hàm này không gọi cache hay celery

    log.info("--- Finished: test_authenticate_user_valid_credentials ---")


@pytest.mark.asyncio
async def test_authenticate_user_invalid_password(mocker):
    """
    Test authenticate_user: Sai mật khẩu.
    Kiểm tra:
    1. Ném ra Exception 'InvalidCredentials'.
    2. Thông báo lỗi (Exception detail) cụ thể.
    3. Mock calls (verify_password VẪN được gọi).
    """
    log.info("--- Running: test_authenticate_user_invalid_password ---")

    # 1. Chuẩn bị Mock Data
    user_data = TestUsers.DEFAULT
    mock_user = User(
        id=1,
        username=user_data["username"],
        password_hash=user_data["real_hash"],
        # ... (các trường khác)
    )
    log.info(f"Mock user created: {mock_user.username}")

    # 2. Mock dependencies
    mock_get_user = AsyncMock(return_value=mock_user)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)
    log.debug("Patched get_user_by_username")

    # Mock verify_password trả về False (sai mật khẩu)
    mock_verify = MagicMock(return_value=False)
    mocker.patch("app.services.user_service.verify_password", mock_verify)
    log.debug("Patched verify_password to return False")

    mock_db = AsyncMock(spec=AsyncSession)  # Cần cho `get_user_by_username`

    # 3. Gọi hàm và Assert Exception
    log.info("Calling authenticate_user with invalid password...")
    with pytest.raises(InvalidCredentials) as exc_info:
        await user_service.authenticate_user(
            db=mock_db,
            username=user_data["username"],
            password=TestUsers.INVALID_PASSWORD,  # <-- Dùng mật khẩu sai
        )
    log.info("InvalidCredentials raised as expected.")

    # 4. Assert Exception Detail (Thông báo lỗi cụ thể)
    assert (
        exc_info.value.detail == "Incorrect username or password."
    ), f"Unexpected error detail: {exc_info.value.detail}"
    log.info("Exception detail assertion successful.")

    # 5. Assert Mock Calls
    mock_get_user.assert_awaited_once_with(mock_db, user_data["username"])
    # Đảm bảo verify VẪN được gọi (chống timing attack)
    mock_verify.assert_called_once_with(
        TestUsers.INVALID_PASSWORD, user_data["real_hash"]
    )
    mock_db.refresh.assert_not_awaited()  # Không được gọi refresh
    log.info("Mock call assertions successful (verify was called, refresh was not).")
    log.info("--- Finished: test_authenticate_user_invalid_password ---")


@pytest.mark.asyncio
async def test_authenticate_user_not_found(mocker):
    """
    Test authenticate_user: User không tồn tại.
    Kiểm tra:
    1. Ném ra Exception 'InvalidCredentials'.
    2. Thông báo lỗi (Exception detail) GİỐNG HỆT lỗi sai password.
    3. Mock calls (verify_password VẪN được gọi với DUMMY HASH).
    """
    log.info("--- Running: test_authenticate_user_not_found ---")

    # 1. Mock dependencies
    # get_user_by_username trả về None
    mock_get_user = AsyncMock(return_value=None)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)
    log.debug("Patched get_user_by_username to return None")

    mock_verify = MagicMock(
        return_value=False
    )  # Kết quả không quan trọng, nhưng mock nó
    mocker.patch("app.services.user_service.verify_password", mock_verify)
    log.debug("Patched verify_password (will be called with dummy hash)")

    mock_db = AsyncMock(spec=AsyncSession)

    # 2. Gọi hàm và Assert Exception
    log.info("Calling authenticate_user with non-existent username...")
    with pytest.raises(InvalidCredentials) as exc_info:
        await user_service.authenticate_user(
            db=mock_db,
            username=TestUsers.NON_EXISTENT_USERNAME,  # <-- Dùng username không tồn tại
            password="anypassword",
        )
    log.info("InvalidCredentials raised as expected.")

    # 3. Assert Exception Detail (Thông báo lỗi cụ thể - Chống User Enumeration)
    # Message phải giống hệt trường hợp sai mật khẩu
    assert (
        exc_info.value.detail == "Incorrect username or password."
    ), f"Unexpected error detail (should be generic): {exc_info.value.detail}"
    log.info("Exception detail assertion successful (generic message for security).")

    # 4. Assert Mock Calls (Timing Attack check)
    mock_get_user.assert_awaited_once_with(mock_db, TestUsers.NON_EXISTENT_USERNAME)
    # verify_password PHẢI được gọi với DUMMY HASH
    # Lấy dummy hash từ logic thực tế của service
    dummy_hash_in_service = (
        user_service.DUMMY_BCRYPT_HASH
    )  # Giả sử DUMMY_HASH được định nghĩa trong service
    # Nếu không, dùng constant
    # dummy_hash_in_service = SecurityConstants.DUMMY_BCRYPT_HASH
    mock_verify.assert_called_once_with("anypassword", dummy_hash_in_service)
    mock_db.refresh.assert_not_awaited()  # Không được gọi refresh
    log.info("Mock call assertions successful (verify called with DUMMY hash).")
    log.info("--- Finished: test_authenticate_user_not_found ---")
