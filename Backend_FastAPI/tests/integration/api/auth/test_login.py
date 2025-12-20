# tests/integration/api/auth/test_login.py
# -*- coding: utf-8 -*-
"""
✅ AUTHENTICATE_USER SERVICE TESTS (Unit Tests)

Tests for user_service.authenticate_user function:
- Valid credentials return user
- Invalid password raises InvalidCredentials
- Non-existent user raises InvalidCredentials (same message for security)
- Timing attack prevention (verify_password always called)
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import user_service
from app.utils.exceptions import InvalidCredentials

try:
    from tests.fixtures.constants import TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)

# The dummy hash used in authenticate_user for timing attack prevention
DUMMY_BCRYPT_HASH = "$2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62"


@pytest.mark.asyncio
async def test_authenticate_user_valid_credentials(mocker):
    """
    ✅ TEST: Xác thực thành công với credentials hợp lệ.
    
    Kiểm tra:
    1. Trả về đúng User object
    2. get_user_by_username được gọi
    3. verify_password được gọi với hash thật
    """
    log.info("--- Running: test_authenticate_user_valid_credentials ---")

    # Prepare mock data
    user_data = TestUsers.DEFAULT
    mock_user = User(
        id=1,
        username=user_data["username"],
        email=user_data["email"],
        password_hash=user_data["real_hash"],
        role=user_data["role"],
        status=user_data["status"],
    )
    log.info(f"Mock user created: {mock_user.username}")

    # Mock dependencies
    mock_get_user = AsyncMock(return_value=mock_user)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)

    mock_verify = MagicMock(return_value=True)
    mocker.patch("app.services.user_service.verify_password", mock_verify)

    mock_db = AsyncMock(spec=AsyncSession)

    # Call function
    log.info("Calling authenticate_user with valid credentials...")
    authenticated_user = await user_service.authenticate_user(
        db=mock_db,
        username=user_data["username"],
        password=user_data["password"],
    )

    # Assert return value
    assert authenticated_user is not None
    assert authenticated_user == mock_user
    assert authenticated_user.username == user_data["username"]
    log.info("✅ Return value assertion successful")

    # Assert mock calls
    mock_get_user.assert_awaited_once_with(mock_db, user_data["username"])
    mock_verify.assert_called_once_with(user_data["password"], user_data["real_hash"])
    # Note: db.refresh is no longer called in authenticate_user
    log.info("✅ Mock call assertions successful")

    log.info("--- Finished: test_authenticate_user_valid_credentials ---")


@pytest.mark.asyncio
async def test_authenticate_user_invalid_password(mocker):
    """
    ✅ TEST: Sai mật khẩu raises InvalidCredentials.
    
    Kiểm tra:
    1. InvalidCredentials được raise
    2. verify_password vẫn được gọi (chống timing attack)
    """
    log.info("--- Running: test_authenticate_user_invalid_password ---")

    user_data = TestUsers.DEFAULT
    mock_user = User(
        id=1,
        username=user_data["username"],
        password_hash=user_data["real_hash"],
    )

    mock_get_user = AsyncMock(return_value=mock_user)
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)

    mock_verify = MagicMock(return_value=False)  # Password invalid
    mocker.patch("app.services.user_service.verify_password", mock_verify)

    mock_db = AsyncMock(spec=AsyncSession)

    # Should raise InvalidCredentials
    with pytest.raises(InvalidCredentials) as exc_info:
        await user_service.authenticate_user(
            db=mock_db,
            username=user_data["username"],
            password=TestUsers.INVALID_PASSWORD,
        )

    assert exc_info.value.detail == "Incorrect username or password."
    log.info("✅ InvalidCredentials raised with correct message")

    # verify_password should still be called (timing attack prevention)
    mock_verify.assert_called_once_with(TestUsers.INVALID_PASSWORD, user_data["real_hash"])
    log.info("✅ verify_password was called (timing attack prevention)")

    log.info("--- Finished: test_authenticate_user_invalid_password ---")


@pytest.mark.asyncio
async def test_authenticate_user_not_found(mocker):
    """
    ✅ TEST: User không tồn tại raises InvalidCredentials.
    
    Security: 
    - Same error message as invalid password (no user enumeration)
    - verify_password called with dummy hash (timing attack prevention)
    """
    log.info("--- Running: test_authenticate_user_not_found ---")

    mock_get_user = AsyncMock(return_value=None)  # User not found
    mocker.patch("app.services.user_service.get_user_by_username", mock_get_user)

    mock_verify = MagicMock(return_value=False)
    mocker.patch("app.services.user_service.verify_password", mock_verify)

    mock_db = AsyncMock(spec=AsyncSession)

    # Should raise InvalidCredentials
    with pytest.raises(InvalidCredentials) as exc_info:
        await user_service.authenticate_user(
            db=mock_db,
            username=TestUsers.NON_EXISTENT_USERNAME,
            password="anypassword",
        )

    # Same message as invalid password (security - no user enumeration)
    assert exc_info.value.detail == "Incorrect username or password."
    log.info("✅ InvalidCredentials with generic message (no user enumeration)")

    # verify_password MUST be called with dummy hash (timing attack prevention)
    mock_verify.assert_called_once_with("anypassword", DUMMY_BCRYPT_HASH)
    log.info("✅ verify_password called with dummy hash (timing attack prevention)")

    log.info("--- Finished: test_authenticate_user_not_found ---")
