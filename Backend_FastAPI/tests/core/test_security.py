# tests/core/test_security.py
# -*- coding: utf-8 -*-
import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import JWTError, jwt

# Import các hàm cần test và settings
from app import security
from app.config import settings  # Cần settings để lấy secret key và algorithm

# Import constants
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from ..fixtures.constants import SecurityConstants, TestUsers
except ImportError:
    pytest.fail(
        "Could not import constants from tests.fixtures.constants. Please create the file."
    )

log = logging.getLogger(__name__)  # Khởi tạo logger

# === Dữ liệu mẫu ===
# Sử dụng username và email từ constants
TEST_USERNAME = TestUsers.DEFAULT["username"]
TEST_EMAIL = TestUsers.DEFAULT["email"]
TEST_DATA_PAYLOAD = {"sub": TEST_USERNAME}

# ==================================
# Tests cho Access Token
# ==================================


def test_create_access_token_default_expiry():
    """
    Kiểm tra tạo access token:
    - Thời gian hết hạn mặc định.
    - Cấu trúc payload chuẩn (sub, exp, jti, type).
    - Không rò rỉ thông tin nhạy cảm.
    """
    log.info("--- Running: test_create_access_token_default_expiry ---")

    token = security.create_access_token(data=TEST_DATA_PAYLOAD)
    log.debug(f"Generated Token: {token}")

    assert isinstance(token, str), "Token phải là một chuỗi"

    # --- Assertions Nội Dung Response (Token Payload) ---
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        log.debug(f"Decoded Payload: {payload}")

        # 1. Kiểm tra cấu trúc JSON đúng và các trường tồn tại
        assert isinstance(payload, dict), "Payload phải là dictionary"
        required_keys = {"sub", "exp", "jti", "type"}
        assert required_keys.issubset(
            payload.keys()
        ), f"Payload thiếu keys: {required_keys - payload.keys()}"

        # 2. Kiểm tra giá trị như mong đợi
        assert (
            payload["sub"] == TEST_USERNAME
        ), f"Expected sub='{TEST_USERNAME}', got '{payload['sub']}'"
        assert (
            payload["type"] == "access"
        ), f"Expected type='access', got '{payload['type']}'"
        assert isinstance(payload["exp"], int), "'exp' phải là integer (Unix timestamp)"
        assert isinstance(payload["jti"], str), "'jti' phải là string"

        # 3. Kiểm tra JTI là UUID hợp lệ
        try:
            uuid.UUID(payload["jti"])
        except ValueError:
            pytest.fail(f"Invalid JTI format: {payload['jti']} is not a valid UUID")

        # 4. Kiểm tra không rò rỉ thông tin nhạy cảm (ngoài 'sub')
        unexpected_keys = {"password", "password_hash", "secret"}
        assert not unexpected_keys.intersection(
            payload.keys()
        ), f"Payload chứa key không mong muốn: {unexpected_keys.intersection(payload.keys())}"

        # 5. Kiểm tra thời gian hết hạn (gần đúng)
        expected_expiry = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        actual_expiry = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert abs(expected_expiry - actual_expiry) < timedelta(
            seconds=10
        ), "Thời gian hết hạn không khớp (sai số > 10s)"  # Tăng sai số lên 10s

    except JWTError as e:
        pytest.fail(f"Không thể decode token hợp lệ: {e}")
    except Exception as e:
        pytest.fail(f"Lỗi không mong muốn khi kiểm tra payload: {e}")

    # --- Assertions Trạng Thái DB / Cache / Celery ---
    # *Không áp dụng* cho unit test hàm tạo token này.
    # Hàm `create_access_token` không tương tác trực tiếp với DB, Redis, hay Celery.

    log.info("Default expiry check and payload structure passed.")
    log.info("--- Finished: test_create_access_token_default_expiry ---")


def test_create_access_token_custom_expiry():
    """Kiểm tra tạo access token với thời gian hết hạn tùy chỉnh."""
    log.info("--- Running: test_create_access_token_custom_expiry ---")
    custom_delta = timedelta(hours=1)
    token = security.create_access_token(
        data=TEST_DATA_PAYLOAD, expires_delta=custom_delta
    )
    log.debug(f"Generated Token: {token}")

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        log.debug(f"Decoded Payload: {payload}")

        assert payload["sub"] == TEST_USERNAME
        assert payload["type"] == "access"

        expected_expiry = datetime.now(timezone.utc) + custom_delta
        actual_expiry = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert abs(expected_expiry - actual_expiry) < timedelta(
            seconds=10
        ), "Thời gian hết hạn tùy chỉnh không khớp (sai số > 10s)"

    except JWTError as e:
        pytest.fail(f"Không thể decode token hợp lệ: {e}")

    log.info("Custom expiry check passed.")
    log.info("--- Finished: test_create_access_token_custom_expiry ---")


# ==================================
# Tests cho Refresh Token
# ==================================


def test_create_refresh_token_default_expiry():
    """
    Kiểm tra tạo refresh token:
    - Thời gian hết hạn mặc định.
    - Cấu trúc payload chuẩn (sub, exp, jti, type).
    """
    log.info("--- Running: test_create_refresh_token_default_expiry ---")
    token = security.create_refresh_token(data=TEST_DATA_PAYLOAD)
    log.debug(f"Generated Token: {token}")

    assert isinstance(token, str)

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        log.debug(f"Decoded Payload: {payload}")

        # --- Assertions Nội Dung Payload ---
        assert isinstance(payload, dict)
        required_keys = {"sub", "exp", "jti", "type"}
        assert required_keys.issubset(payload.keys())
        assert payload["sub"] == TEST_USERNAME
        assert payload["type"] == "refresh", "Refresh token phải có type='refresh'"
        assert isinstance(payload["exp"], int)
        assert isinstance(payload["jti"], str)
        uuid.UUID(payload["jti"])  # Kiểm tra format JTI

        # Kiểm tra thời gian hết hạn (gần đúng)
        expected_expiry = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        actual_expiry = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert abs(expected_expiry - actual_expiry) < timedelta(
            seconds=10
        ), "Thời gian hết hạn mặc định không khớp (sai số > 10s)"

    except JWTError as e:
        pytest.fail(f"Không thể decode refresh token hợp lệ: {e}")
    except ValueError:
        pytest.fail(f"Invalid JTI format in refresh token: {payload.get('jti')}")

    log.info("Default expiry check and payload structure passed.")
    log.info("--- Finished: test_create_refresh_token_default_expiry ---")


def test_create_refresh_token_custom_expiry():
    """Kiểm tra tạo refresh token với thời gian hết hạn tùy chỉnh."""
    log.info("--- Running: test_create_refresh_token_custom_expiry ---")
    custom_delta = timedelta(days=7)
    token = security.create_refresh_token(
        data=TEST_DATA_PAYLOAD, expires_delta=custom_delta
    )
    log.debug(f"Generated Token: {token}")

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        log.debug(f"Decoded Payload: {payload}")

        assert payload["sub"] == TEST_USERNAME
        assert payload["type"] == "refresh"

        expected_expiry = datetime.now(timezone.utc) + custom_delta
        actual_expiry = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert abs(expected_expiry - actual_expiry) < timedelta(
            seconds=10
        ), "Thời gian hết hạn tùy chỉnh không khớp (sai số > 10s)"

    except JWTError as e:
        pytest.fail(f"Không thể decode refresh token hợp lệ: {e}")

    log.info("Custom expiry check passed.")
    log.info("--- Finished: test_create_refresh_token_custom_expiry ---")


# ==================================
# Tests cho Password Reset Token
# ==================================


def test_create_and_verify_password_reset_token_success():
    """Kiểm tra tạo và xác thực token reset mật khẩu thành công."""
    log.info("--- Running: test_create_and_verify_password_reset_token_success ---")
    email = TEST_EMAIL  # Sử dụng email từ constant
    token = security.create_password_reset_token(email=email)
    log.debug(f"Generated Reset Token: {token}")

    assert isinstance(token, str)

    # --- Assertions Nội Dung Response (Token Payload - Gián tiếp qua verify) ---
    # Kiểm tra payload gián tiếp bằng cách verify token
    verified_email = security.verify_password_reset_token(token)
    assert (
        verified_email == email
    ), f"Expected verified email '{email}', got '{verified_email}'"

    # Decode thêm để kiểm tra scope và exp (nếu cần)
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        assert (
            payload.get("scope") == "password_reset"
        ), "Scope phải là 'password_reset'"
        assert "exp" in payload, "Token reset phải có 'exp'"
        # Kiểm tra thời gian hết hạn (30 phút theo code)
        expected_expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
        actual_expiry = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert abs(expected_expiry - actual_expiry) < timedelta(seconds=10)

    except JWTError as e:
        pytest.fail(f"Không thể decode token reset hợp lệ: {e}")

    log.info("Token creation and verification successful.")
    log.info("--- Finished: test_create_and_verify_password_reset_token_success ---")


def test_verify_password_reset_token_invalid_string():
    """Kiểm tra xác thực token reset mật khẩu với chuỗi không hợp lệ."""
    log.info("--- Running: test_verify_password_reset_token_invalid_string ---")
    invalid_token = SecurityConstants.INVALID_TOKEN_STRING  # Dùng constant
    verified_email = security.verify_password_reset_token(invalid_token)

    # --- Assertion Kết Quả ---
    assert verified_email is None, "Hàm verify phải trả về None cho token không hợp lệ"

    # --- Assertion Thông Báo Lỗi Cụ Thể (Không áp dụng trực tiếp) ---
    # Hàm verify_password_reset_token bắt JWTError và trả về None, không ném lỗi ra ngoài.
    # Chúng ta chỉ có thể assert kết quả là None.

    log.info("Invalid token string correctly identified as None.")
    log.info("--- Finished: test_verify_password_reset_token_invalid_string ---")


@patch(
    "jose.jwt.decode", side_effect=JWTError("Simulated Token has expired")
)  # Mock lỗi decode
def test_verify_password_reset_token_expired(mock_decode):
    """Kiểm tra xác thực token reset mật khẩu đã hết hạn (mock JWTError)."""
    log.info("--- Running: test_verify_password_reset_token_expired ---")
    expired_token = "any.expired.token"  # Nội dung không quan trọng vì decode bị mock

    verified_email = security.verify_password_reset_token(expired_token)

    # --- Assertion Kết Quả ---
    assert verified_email is None, "Hàm verify phải trả về None khi JWTError (hết hạn)"

    # --- Assertion Mock Call ---
    mock_decode.assert_called_once_with(
        expired_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )

    log.info("Expired token correctly identified as None due to JWTError.")
    log.info("--- Finished: test_verify_password_reset_token_expired ---")


def test_verify_password_reset_token_wrong_scope():
    """Kiểm tra xác thực token không phải là token reset mật khẩu (sai scope)."""
    log.info("--- Running: test_verify_password_reset_token_wrong_scope ---")
    email = TEST_EMAIL
    # Tạo token với scope khác
    expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
    wrong_scope_payload = {"exp": expiry, "sub": email, "scope": "login"}  # Sai scope
    wrong_scope_token = jwt.encode(
        wrong_scope_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    log.debug(f"Generated Wrong Scope Token: {wrong_scope_token}")

    verified_email = security.verify_password_reset_token(wrong_scope_token)

    # --- Assertion Kết Quả ---
    assert verified_email is None, "Hàm verify phải trả về None khi scope không đúng"

    log.info("Token with wrong scope correctly identified as None.")
    log.info("--- Finished: test_verify_password_reset_token_wrong_scope ---")


# ==================================
# Tests cho decode_token_for_invalidation
# ==================================


def test_decode_token_for_invalidation_success():
    """Kiểm tra lấy JTI và TTL từ token hợp lệ."""
    log.info("--- Running: test_decode_token_for_invalidation_success ---")
    delta = timedelta(minutes=15)
    token = security.create_access_token(data=TEST_DATA_PAYLOAD, expires_delta=delta)

    # Decode gốc để lấy JTI mong đợi
    try:
        original_payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        expected_jti = original_payload.get("jti")
        assert expected_jti is not None, "Token gốc phải có JTI"
    except JWTError:
        pytest.fail("Không thể decode token gốc để lấy expected JTI")

    # --- Action ---
    jti, ttl = security.decode_token_for_invalidation(token)

    # --- Assertions Kết Quả ---
    assert jti == expected_jti, f"Expected JTI '{expected_jti}', got '{jti}'"
    assert ttl is not None, "TTL không nên là None cho token có exp"
    # TTL phải xấp xỉ 15 phút * 60 giây, cho phép sai số nhỏ
    expected_ttl_seconds = delta.total_seconds()
    # TTL trả về là số nguyên (giây còn lại), nên so sánh số nguyên
    assert isinstance(ttl, int), "TTL trả về phải là integer"
    assert (
        abs(ttl - int(expected_ttl_seconds)) <= 10
    ), f"TTL ({ttl}s) không nằm trong khoảng mong đợi (~{int(expected_ttl_seconds)}s +/- 10s)"
    assert ttl >= 0, "TTL không được âm"

    log.info(f"Successfully decoded JTI ({jti}) and TTL ({ttl}).")
    log.info("--- Finished: test_decode_token_for_invalidation_success ---")


def test_decode_token_for_invalidation_invalid_token_string():
    """Kiểm tra decode token với chuỗi không hợp lệ."""
    log.info("--- Running: test_decode_token_for_invalidation_invalid_token_string ---")
    jti, ttl = security.decode_token_for_invalidation(
        SecurityConstants.INVALID_TOKEN_STRING
    )  # Dùng constant

    # --- Assertions Kết Quả ---
    assert jti is None, "JTI phải là None cho token không hợp lệ"
    assert ttl is None, "TTL phải là None cho token không hợp lệ"

    log.info("Invalid token string correctly returned None, None.")
    log.info(
        "--- Finished: test_decode_token_for_invalidation_invalid_token_string ---"
    )


def test_decode_token_for_invalidation_expired_token():
    """Kiểm tra decode token đã hết hạn (vẫn lấy được JTI, TTL <= 0)."""
    log.info("--- Running: test_decode_token_for_invalidation_expired_token ---")
    # Tạo token đã hết hạn
    delta = timedelta(seconds=-60)  # Hết hạn 60 giây trước
    expired_token = security.create_access_token(
        data=TEST_DATA_PAYLOAD, expires_delta=delta
    )

    # Decode gốc để lấy JTI mong đợi
    try:
        original_payload = jwt.decode(
            expired_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )  # Tắt kiểm tra hết hạn
        expected_jti = original_payload.get("jti")
        assert expected_jti is not None
    except JWTError:
        pytest.fail("Không thể decode token gốc (đã hết hạn) để lấy expected JTI")

    # --- Action ---
    jti, ttl = security.decode_token_for_invalidation(expired_token)

    # --- Assertions Kết Quả ---
    assert jti == expected_jti, "JTI vẫn phải lấy được từ token hết hạn"
    assert ttl is not None, "TTL không nên là None cho token có exp (dù đã hết hạn)"
    assert isinstance(ttl, int), "TTL trả về phải là integer"
    assert (
        ttl <= 0
    ), f"TTL cho token đã hết hạn phải <= 0, got {ttl}"  # TTL còn lại phải là 0 hoặc âm

    log.info(
        f"Expired token correctly returned JTI ({jti}) and non-positive TTL ({ttl})."
    )
    log.info("--- Finished: test_decode_token_for_invalidation_expired_token ---")


def test_decode_token_for_invalidation_no_exp():
    """Kiểm tra decode token không có trường 'exp'."""
    log.info("--- Running: test_decode_token_for_invalidation_no_exp ---")
    # Tạo token không có 'exp' (thủ công)
    test_jti = str(uuid.uuid4())
    payload_no_exp = {"sub": TEST_USERNAME, "jti": test_jti, "type": "access"}
    token_no_exp = jwt.encode(
        payload_no_exp, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )

    # --- Action ---
    jti, ttl = security.decode_token_for_invalidation(token_no_exp)

    # --- Assertions Kết Quả ---
    assert jti == test_jti, "JTI phải được lấy đúng"
    assert ttl is None, "TTL phải là None vì token không có trường 'exp'"

    log.info("Token without 'exp' correctly returned JTI and ttl=None.")
    log.info("--- Finished: test_decode_token_for_invalidation_no_exp ---")
