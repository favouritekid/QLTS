# tests/services/test_mfa.py
"""
Tests for MFA (Multi-Factor Authentication) service and API endpoints.

Covers:
1. TOTP helpers (generate, verify)
2. Encryption/decryption of TOTP secrets
3. Backup code generation and bcrypt verification
4. MFA token creation/decoding
5. Full MFA setup/enable/disable flows (API integration)
6. MFA login flow (two-step: password → mfa_token → verify-mfa)
7. Security: token isolation, rate limiting, session revocation
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pyotp
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from cryptography.fernet import Fernet

from app import models
from app.config import settings
from app.security import get_password_hash
from app.services import mfa_service

log = logging.getLogger(__name__)

# Generate a stable test encryption key (valid Fernet key)
_TEST_MFA_KEY = Fernet.generate_key().decode()


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def _set_mfa_encryption_key(monkeypatch):
    """Ensure MFA_ENCRYPTION_KEY is set for all tests in this module."""
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", _TEST_MFA_KEY)


@pytest_asyncio.fixture(autouse=True)
async def _clean_redis_between_tests(test_redis_client):
    """Flush all Redis keys before each test to prevent state leakage."""
    await test_redis_client.flushall()
    yield

@pytest_asyncio.fixture
async def mfa_test_user(db: AsyncSession) -> models.User:
    """Create a user for MFA tests (MFA disabled by default)."""
    user = models.User(
        username="mfa_test_user",
        email="mfa_test@example.com",
        password_hash=get_password_hash("MfaTestPass123!"),
        role="officer",
        status="active",
        full_name="MFA Test User",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def mfa_enabled_user(db: AsyncSession) -> models.User:
    """Create a user with MFA already enabled."""
    secret = pyotp.random_base32()
    encrypted = mfa_service.encrypt_secret(secret)
    _, bcrypt_hashes = mfa_service.generate_backup_codes(count=8)

    user = models.User(
        username="mfa_enabled_user",
        email="mfa_enabled@example.com",
        password_hash=get_password_hash("MfaEnabledPass123!"),
        role="officer",
        status="active",
        full_name="MFA Enabled User",
        mfa_enabled=True,
        totp_secret_encrypted=encrypted,
        backup_codes_hashed=json.dumps(bcrypt_hashes),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    # Store the plaintext secret for test verification
    user._test_secret = secret
    return user


# =============================================================================
# UNIT TESTS: TOTP HELPERS
# =============================================================================

@pytest.mark.unit
class TestTotpHelpers:
    """Unit tests for TOTP helper functions."""

    def test_generate_totp_secret_returns_base32(self):
        """Generated secret should be valid base32."""
        secret = mfa_service.generate_totp_secret()
        assert len(secret) >= 16
        # Should be valid base32
        import base64
        base64.b32decode(secret)  # Should not raise

    def test_get_provisioning_uri_format(self):
        """Provisioning URI should follow otpauth format."""
        secret = mfa_service.generate_totp_secret()
        uri = mfa_service.get_provisioning_uri(secret, "testuser")
        assert uri.startswith("otpauth://totp/")
        assert "QLTS" in uri
        assert "testuser" in uri
        assert f"secret={secret}" in uri

    def test_generate_qr_code_base64_returns_data_uri(self):
        """QR code should be a valid base64 data URI."""
        secret = mfa_service.generate_totp_secret()
        uri = mfa_service.get_provisioning_uri(secret, "testuser")
        qr = mfa_service.generate_qr_code_base64(uri)
        assert qr.startswith("data:image/png;base64,")
        assert len(qr) > 100  # Should contain actual image data

    def test_verify_totp_valid_code(self):
        """Valid TOTP code should be accepted."""
        secret = mfa_service.generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert mfa_service.verify_totp(secret, code) is True

    def test_verify_totp_invalid_code(self):
        """Invalid TOTP code should be rejected."""
        secret = mfa_service.generate_totp_secret()
        assert mfa_service.verify_totp(secret, "000000") is False

    def test_verify_totp_wrong_length(self):
        """Non-6-digit code should fail TOTP verification."""
        secret = mfa_service.generate_totp_secret()
        assert mfa_service.verify_totp(secret, "12345") is False
        assert mfa_service.verify_totp(secret, "1234567") is False

    def test_verify_totp_with_counter_returns_counter(self):
        """verify_totp_with_counter should return matched time counter."""
        secret = mfa_service.generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        is_valid, counter = mfa_service.verify_totp_with_counter(secret, code)
        assert is_valid is True
        assert counter is not None
        assert isinstance(counter, int)

    def test_verify_totp_with_counter_invalid_returns_none(self):
        """Invalid code should return (False, None)."""
        secret = mfa_service.generate_totp_secret()
        is_valid, counter = mfa_service.verify_totp_with_counter(secret, "000000")
        assert is_valid is False
        assert counter is None

    def test_verify_totp_with_counter_previous_step(self):
        """Code from previous time step should still be accepted (valid_window=1)."""
        from datetime import datetime, timezone
        secret = mfa_service.generate_totp_secret()
        totp = pyotp.TOTP(secret)
        # Generate code for previous time step
        prev_counter = totp.timecode(datetime.now(timezone.utc)) - 1
        prev_code = totp.generate_otp(prev_counter)
        is_valid, counter = mfa_service.verify_totp_with_counter(secret, prev_code)
        assert is_valid is True
        assert counter == prev_counter


# =============================================================================
# UNIT TESTS: ENCRYPTION
# =============================================================================

@pytest.mark.unit
class TestEncryption:
    """Unit tests for TOTP secret encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting and decrypting should return original value."""
        plaintext = "JBSWY3DPEHPK3PXP"
        encrypted = mfa_service.encrypt_secret(plaintext)
        assert encrypted != plaintext  # Should be different
        decrypted = mfa_service.decrypt_secret(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertexts(self):
        """Same plaintext should produce different ciphertexts (Fernet uses random IV)."""
        plaintext = "JBSWY3DPEHPK3PXP"
        c1 = mfa_service.encrypt_secret(plaintext)
        c2 = mfa_service.encrypt_secret(plaintext)
        assert c1 != c2  # Different IVs


# =============================================================================
# UNIT TESTS: BACKUP CODES
# =============================================================================

@pytest.mark.unit
class TestBackupCodes:
    """Unit tests for backup code generation and verification."""

    def test_generate_backup_codes_count(self):
        """Should generate requested number of codes."""
        plaintext, hashes = mfa_service.generate_backup_codes(count=8)
        assert len(plaintext) == 8
        assert len(hashes) == 8

    def test_generate_backup_codes_format(self):
        """Codes should be 10-char hex strings (40-bit entropy)."""
        plaintext, _ = mfa_service.generate_backup_codes(count=4)
        for code in plaintext:
            assert len(code) == 10
            int(code, 16)  # Should be valid hex

    def test_backup_codes_are_unique(self):
        """All generated codes should be unique."""
        plaintext, _ = mfa_service.generate_backup_codes(count=8)
        assert len(set(plaintext)) == 8

    def test_verify_backup_code_valid(self):
        """Valid backup code should match its hash."""
        plaintext, hashes = mfa_service.generate_backup_codes(count=4)
        hashes_json = json.dumps(hashes)

        matched, updated = mfa_service.verify_backup_code(plaintext[0], hashes_json)
        assert matched is True
        # Used code should be removed
        remaining = json.loads(updated)
        assert len(remaining) == 3

    def test_verify_backup_code_invalid(self):
        """Invalid code should not match."""
        _, hashes = mfa_service.generate_backup_codes(count=4)
        hashes_json = json.dumps(hashes)

        matched, updated = mfa_service.verify_backup_code("invalid!", hashes_json)
        assert matched is False
        # No codes consumed
        remaining = json.loads(updated)
        assert len(remaining) == 4

    def test_verify_backup_code_consumes_only_matched(self):
        """Using a code should remove only that specific hash."""
        plaintext, hashes = mfa_service.generate_backup_codes(count=4)
        hashes_json = json.dumps(hashes)

        # Use second code
        matched, updated = mfa_service.verify_backup_code(plaintext[1], hashes_json)
        assert matched is True

        # First code should still work
        matched2, updated2 = mfa_service.verify_backup_code(plaintext[0], updated)
        assert matched2 is True
        assert len(json.loads(updated2)) == 2

    def test_verify_backup_code_empty_list(self):
        """Empty hash list should return no match."""
        matched, updated = mfa_service.verify_backup_code("anything", "")
        assert matched is False


# =============================================================================
# UNIT TESTS: MFA TOKEN
# =============================================================================

@pytest.mark.unit
class TestMfaToken:
    """Unit tests for MFA token creation/decoding."""

    def test_create_mfa_token(self):
        """MFA token should be a valid JWT string."""
        token = mfa_service.create_mfa_token(username="testuser", user_id=42)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_decode_mfa_token_roundtrip(self):
        """Created MFA token should decode correctly."""
        token = mfa_service.create_mfa_token(username="testuser", user_id=42)
        payload = mfa_service.decode_mfa_token(token)
        assert payload["sub"] == "testuser"
        assert payload["user_id"] == 42
        assert payload["type"] == "mfa"

    def test_decode_mfa_token_rejects_access_token(self):
        """Access tokens (type != mfa) should be rejected."""
        from app.security import create_access_token

        access_token = create_access_token(
            data={"sub": "testuser", "user_id": 1, "role": "user"},
            refresh_jti="test-jti",
        )
        from app.utils.exceptions import InvalidCredentials
        with pytest.raises(InvalidCredentials):
            mfa_service.decode_mfa_token(access_token)

    def test_decode_mfa_token_rejects_expired(self):
        """Expired MFA token should raise InvalidCredentials."""
        import jwt as jose_jwt

        expired_payload = {
            "sub": "testuser",
            "user_id": 1,
            "type": "mfa",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
        token = jose_jwt.encode(
            expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        from app.utils.exceptions import InvalidCredentials
        with pytest.raises(InvalidCredentials, match="expired"):
            mfa_service.decode_mfa_token(token)

    def test_decode_mfa_token_rejects_invalid_string(self):
        """Invalid token string should raise InvalidCredentials."""
        from app.utils.exceptions import InvalidCredentials
        with pytest.raises(InvalidCredentials):
            mfa_service.decode_mfa_token("not.a.valid.token")


# =============================================================================
# INTEGRATION TESTS: MFA API ENDPOINTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestMfaSetupFlow:
    """Integration tests for MFA setup/enable/disable API flow."""

    async def test_mfa_status_default_disabled(
        self, client: AsyncClient, regular_user_in_db: dict
    ):
        """New user should have MFA disabled."""
        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # Check MFA status
        status_res = await client.get("/api/auth/mfa/status")
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["mfa_enabled"] is False
        assert data["has_backup_codes"] is False

    async def test_mfa_setup_returns_qr_and_secret(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """MFA setup should return QR code and secret."""
        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # Setup MFA
        setup_res = await client.post("/api/auth/mfa/setup")
        assert setup_res.status_code == 200
        data = setup_res.json()
        assert "secret" in data
        assert "qr_code" in data
        assert data["qr_code"].startswith("data:image/png;base64,")
        assert "provisioning_uri" in data

    async def test_mfa_full_enable_flow(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Full flow: setup → enable with TOTP code → backup codes returned."""
        # Login
        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # Setup
        setup_res = await client.post("/api/auth/mfa/setup")
        assert setup_res.status_code == 200
        secret = setup_res.json()["secret"]

        # Generate valid TOTP code
        totp = pyotp.TOTP(secret)
        code = totp.now()

        # Enable MFA
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        assert enable_res.status_code == 200
        data = enable_res.json()
        assert "backup_codes" in data
        assert len(data["backup_codes"]) == 8

        # Verify status changed
        status_res = await client.get("/api/auth/mfa/status")
        assert status_res.status_code == 200
        assert status_res.json()["mfa_enabled"] is True

    async def test_mfa_disable_requires_password(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Disabling MFA should require correct password."""
        password = regular_user_in_db["password"]

        # Login + Setup + Enable
        await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})

        # Disable with wrong password
        wrong_res = await client.post("/api/auth/mfa/disable", json={
            "password": "WrongPassword123!"
        })
        assert wrong_res.status_code == 401

        # Disable with correct password
        disable_res = await client.post("/api/auth/mfa/disable", json={
            "password": password,
        })
        assert disable_res.status_code == 200

        # Verify disabled
        status_res = await client.get("/api/auth/mfa/status")
        assert status_res.json()["mfa_enabled"] is False

    async def test_mfa_setup_rejected_when_already_enabled(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Setup should fail if MFA already enabled."""
        password = regular_user_in_db["password"]

        # Login + Setup + Enable
        await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})

        # Try to setup again
        setup2_res = await client.post("/api/auth/mfa/setup")
        assert setup2_res.status_code == 400

    async def test_mfa_enable_invalid_code_rejected(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Enable with wrong TOTP code should be rejected."""
        # Login + Setup
        await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        await client.post("/api/auth/mfa/setup")

        # Enable with invalid code
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": "000000"})
        assert enable_res.status_code == 401

    async def test_mfa_regenerate_backup_codes(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Regenerate backup codes with password verification."""
        password = regular_user_in_db["password"]

        # Login + Setup + Enable
        await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        old_codes = enable_res.json()["backup_codes"]

        # Regenerate
        regen_res = await client.post("/api/auth/mfa/backup-codes", json={
            "password": password,
        })
        assert regen_res.status_code == 200
        new_codes = regen_res.json()["backup_codes"]
        assert len(new_codes) == 8
        assert new_codes != old_codes  # Different codes


# =============================================================================
# INTEGRATION TESTS: MFA LOGIN FLOW
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestMfaLoginFlow:
    """Integration tests for two-step MFA login flow."""

    async def test_login_mfa_user_returns_mfa_token(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Login with MFA-enabled user should return mfa_required + mfa_token."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Login + Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})

        # Logout (clear cookies)
        await client.post("/api/auth/logout")

        # Login again - should require MFA
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as new_client:
            login_res = await new_client.post("/api/auth/login", data={
                "username": username, "password": password,
            })

        assert login_res.status_code == 200
        data = login_res.json()
        assert data["mfa_required"] is True
        assert "mfa_token" in data
        # Should NOT have cookies set
        assert "access_token" not in login_res.cookies

    async def test_verify_mfa_with_valid_totp(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Verify MFA with correct TOTP code should complete login."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Login + Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})
        await client.post("/api/auth/logout")

        # Login again
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as mfa_client:
            login_res = await mfa_client.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # Verify with fresh TOTP code
            fresh_code = pyotp.TOTP(secret).now()
            verify_res = await mfa_client.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token,
                "code": fresh_code,
            })

        assert verify_res.status_code == 200
        assert "access_token" in verify_res.cookies

    async def test_verify_mfa_with_backup_code(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Verify MFA with valid backup code should complete login."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Login + Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        backup_codes = enable_res.json()["backup_codes"]
        await client.post("/api/auth/logout")

        # Login again
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as mfa_client:
            login_res = await mfa_client.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # Use first backup code
            verify_res = await mfa_client.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token,
                "code": backup_codes[0],
            })

        assert verify_res.status_code == 200
        assert "access_token" in verify_res.cookies

    async def test_verify_mfa_invalid_code_rejected(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Verify MFA with wrong code should be rejected."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Login + Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})
        await client.post("/api/auth/logout")

        # Login again
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as mfa_client:
            login_res = await mfa_client.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # Wrong code
            verify_res = await mfa_client.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token,
                "code": "000000",
            })

        assert verify_res.status_code == 401

    async def test_verify_mfa_expired_token_rejected(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Expired MFA token should be rejected."""
        import jwt as jose_jwt

        # Create expired MFA token
        expired_payload = {
            "sub": regular_user_in_db["username"],
            "user_id": regular_user_in_db["id"],
            "type": "mfa",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            "jti": "expired-jti",
        }
        expired_token = jose_jwt.encode(
            expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as new_client:
            verify_res = await new_client.post("/api/auth/verify-mfa", json={
                "mfa_token": expired_token,
                "code": "123456",
            })

        assert verify_res.status_code == 401


# =============================================================================
# SECURITY TESTS: TOKEN ISOLATION & RATE LIMITING
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestMfaTokenIsolation:
    """Security tests: MFA token cannot access authenticated endpoints."""

    async def test_mfa_token_cannot_access_protected_endpoints(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """MFA token (type=mfa) should be rejected by protected endpoints."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Login + Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})
        await client.post("/api/auth/logout")

        # Login to get mfa_token
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as mfa_client:
            login_res = await mfa_client.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # Try to use mfa_token as access_token on protected endpoint
            mfa_client.cookies.set("access_token", mfa_token)
            profile_res = await mfa_client.get("/api/profile")

        # Should be rejected - deps.get_current_user rejects type != "access"
        assert profile_res.status_code == 401

    async def test_mfa_token_cannot_access_mfa_setup(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """MFA token should not work as auth for MFA management endpoints."""
        mfa_token = mfa_service.create_mfa_token(
            username=regular_user_in_db["username"],
            user_id=regular_user_in_db["id"],
        )

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as new_client:
            new_client.cookies.set("access_token", mfa_token)
            status_res = await new_client.get("/api/auth/mfa/status")

        assert status_res.status_code == 401

    async def test_access_token_cannot_be_used_as_mfa_token(
        self, client: AsyncClient, regular_user_in_db: dict
    ):
        """Access token (type=access) should be rejected by verify-mfa."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Login to get real access token
        login_res = await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        access_token = login_res.cookies.get("access_token")

        # Try to use access_token as mfa_token
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as new_client:
            verify_res = await new_client.post("/api/auth/verify-mfa", json={
                "mfa_token": access_token,
                "code": "123456",
            })

        assert verify_res.status_code == 401


@pytest.mark.asyncio
@pytest.mark.security
class TestMfaRateLimiting:
    """Security tests: MFA brute-force protection."""

    async def test_mfa_attempts_tracked_in_redis(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Failed MFA attempts should be tracked in Redis."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Login + Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})
        await client.post("/api/auth/logout")

        # Login to get mfa_token
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as mfa_client:
            login_res = await mfa_client.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # Send 3 wrong codes
            for _ in range(3):
                await mfa_client.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token,
                    "code": "000000",
                })

        # Check Redis counter
        attempt_key = f"mfa_attempts:{username}"
        count = await test_redis_client.get(attempt_key)
        assert count is not None
        assert int(count) >= 3


@pytest.mark.asyncio
@pytest.mark.security
class TestMfaSessionRevocation:
    """Security tests: MFA enable revokes other sessions."""

    async def test_enable_mfa_revokes_other_sessions(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """Enabling MFA should revoke all other active sessions."""
        password = regular_user_in_db["password"]
        username = regular_user_in_db["username"]

        # Create session 1
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as client1:
            login1 = await client1.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            assert login1.status_code == 200
            cookies1 = dict(login1.cookies)

        # Create session 2 (the one that will enable MFA)
        login2 = await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        assert login2.status_code == 200

        # Enable MFA from session 2
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        assert enable_res.status_code == 200

        # Session 1 should now be revoked
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as check_client:
            check_client.cookies.update(cookies1)
            profile_res = await check_client.get("/api/profile")

        # Session 1 is revoked (401)
        assert profile_res.status_code == 401

    async def test_login_response_includes_mfa_enabled_field(
        self, client: AsyncClient, regular_user_in_db: dict
    ):
        """Login response user object should include mfa_enabled field."""
        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200
        data = login_res.json()
        assert "user" in data
        assert "mfa_enabled" in data["user"]
        assert data["user"]["mfa_enabled"] is False


# =============================================================================
# SECTION A: LOGIN WITHOUT MFA – ACCOUNT LOCKOUT FLOWS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestLoginAccountLockout:
    """A1-A6: Login lockout flows for non-MFA users."""

    async def test_a1_correct_password_no_lockout(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """A1: Correct password → 200, no lockout counter set."""
        res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert res.status_code == 200

        # No lockout key should exist
        lockout_key = f"account_lockout:{regular_user_in_db['username']}"
        is_locked = await test_redis_client.exists(lockout_key)
        assert is_locked == 0

    async def test_a2_wrong_password_increments_counter(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """A2: Wrong password → 401, counter incremented."""
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": regular_user_in_db["username"],
                "password": "WrongPassword!",
            })
        assert res.status_code == 401

        attempts_key = f"login_attempts:{regular_user_in_db['username']}"
        count = await test_redis_client.get(attempts_key)
        assert count is not None
        assert int(count) == 1

    async def test_a3_four_wrong_then_correct_resets(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """A3: 4 wrong + 1 correct → counter reset, no lockout."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        from app.main import fastapi_app
        # 4 wrong attempts
        for _ in range(4):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/login", data={
                    "username": username, "password": "WrongPass!",
                })

        attempts_key = f"login_attempts:{username}"
        count = await test_redis_client.get(attempts_key)
        assert int(count) == 4

        # Correct login resets counter
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.status_code == 200

        count_after = await test_redis_client.get(attempts_key)
        assert count_after is None  # Counter deleted

    async def test_a4_fifth_wrong_locks_account(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """A4: 5th wrong password → account locked, returns 429."""
        username = regular_user_in_db["username"]
        from app.main import fastapi_app

        # 5 wrong attempts
        last_res = None
        for _ in range(5):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                last_res = await c.post("/api/auth/login", data={
                    "username": username, "password": "WrongPass!",
                })

        # 5th attempt triggers lockout; next attempt should see 429
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            locked_res = await c.post("/api/auth/login", data={
                "username": username, "password": "WrongPass!",
            })

        assert locked_res.status_code == 429
        assert "Retry-After" in locked_res.headers

        # Lockout key exists in Redis
        lockout_key = f"account_lockout:{username}"
        is_locked = await test_redis_client.exists(lockout_key)
        assert is_locked == 1

    async def test_a5_locked_account_rejects_correct_password(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """A5: Locked account rejects even correct password with 429."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        from app.main import fastapi_app

        # Lock the account via 5 wrong attempts
        for _ in range(5):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/login", data={
                    "username": username, "password": "WrongPass!",
                })

        # Now try correct password
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.status_code == 429

    async def test_a6_lockout_expires_allows_login(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """A6: After lockout TTL expires, correct password works again."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Simulate lockout by setting Redis key directly
        lockout_key = f"account_lockout:{username}"
        await test_redis_client.set(lockout_key, "1", ex=1)  # 1 second TTL

        import asyncio
        await asyncio.sleep(1.5)  # Wait for expiry

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.status_code == 200


# =============================================================================
# SECTION B: LOGIN WITH MFA – LOCKOUT INTERACTION
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestMfaLoginLockoutInteraction:
    """B1-B4: How account lockout interacts with MFA login flow."""

    async def _enable_mfa_for_user(
        self, client: AsyncClient, username: str, password: str, test_redis_client
    ) -> tuple:
        """Helper: enable MFA and return (secret, backup_codes)."""
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        backup_codes = enable_res.json()["backup_codes"]
        await client.post("/api/auth/logout")
        return secret, backup_codes

    async def test_b1_mfa_login_correct_password_returns_mfa_token(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """B1: Correct password on MFA user → mfa_required, no session created."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, _ = await self._enable_mfa_for_user(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.status_code == 200
        assert res.json()["mfa_required"] is True
        assert "access_token" not in res.cookies

    async def test_b2_locked_account_cannot_get_mfa_token(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """B2: Locked account returns 429 even before MFA check."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        await self._enable_mfa_for_user(
            client, username, password, test_redis_client
        )

        # Lock account
        lockout_key = f"account_lockout:{username}"
        await test_redis_client.set(lockout_key, "1", ex=900)

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.status_code == 429

    async def test_b3_password_wrong_counter_preserved_across_mfa_challenge(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """B3: Password failures before MFA are NOT reset by correct password + MFA challenge."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, _ = await self._enable_mfa_for_user(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app
        attempts_key = f"login_attempts:{username}"

        # 3 wrong password attempts
        for _ in range(3):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/login", data={
                    "username": username, "password": "WrongPass!",
                })

        count = await test_redis_client.get(attempts_key)
        assert int(count) == 3

        # Correct password → gets mfa_token, but counter is NOT reset (MFA still pending)
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.json()["mfa_required"] is True

        # Counter should still be 3 (not reset until MFA completes)
        count_after = await test_redis_client.get(attempts_key)
        assert count_after is not None
        assert int(count_after) == 3

    async def test_b4_successful_mfa_resets_lockout_counter(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """B4: Full MFA login success (password + TOTP) resets all counters."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, _ = await self._enable_mfa_for_user(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app
        attempts_key = f"login_attempts:{username}"

        # 2 wrong passwords first
        for _ in range(2):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/login", data={
                    "username": username, "password": "WrongPass!",
                })

        # Now correct password → mfa_token
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # Verify MFA with correct TOTP
            fresh_code = pyotp.TOTP(secret).now()
            verify_res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": fresh_code,
            })
        assert verify_res.status_code == 200

        # All counters should be reset
        count = await test_redis_client.get(attempts_key)
        assert count is None

        mfa_attempts_key = f"mfa_attempts:{username}"
        mfa_count = await test_redis_client.get(mfa_attempts_key)
        assert mfa_count is None


# =============================================================================
# SECTION C: MFA VERIFICATION – RATE LIMITING DETAILS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestMfaVerificationRateLimiting:
    """C1-C4: Per-user MFA attempt counter (Layer 2) and L3 interaction."""

    async def _setup_mfa_and_get_token(
        self, client: AsyncClient, username: str, password: str, test_redis_client
    ) -> tuple:
        """Helper: enable MFA, logout, re-login, return (secret, mfa_token, backup_codes)."""
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        backup_codes = enable_res.json()["backup_codes"]
        await client.post("/api/auth/logout")

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        mfa_token = login_res.json()["mfa_token"]
        return secret, mfa_token, backup_codes

    async def test_c1_wrong_mfa_code_increments_l2_counter(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """C1: Each wrong MFA code increments per-user Redis counter."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, mfa_token, _ = await self._setup_mfa_and_get_token(
            client, username, password, test_redis_client
        )

        attempt_key = f"mfa_attempts:{username}"
        from app.main import fastapi_app

        # Send 3 wrong codes
        for i in range(3):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": "000000",
                })
            count = await test_redis_client.get(attempt_key)
            assert int(count) == i + 1

    async def test_c2_fifth_mfa_fail_returns_429(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """C2: 5th wrong MFA code → 429 with Retry-After."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, mfa_token, _ = await self._setup_mfa_and_get_token(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app

        # Send 5 wrong codes (fills L2 counter)
        for _ in range(5):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": "000000",
                })

        # 6th attempt should be blocked by L2
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": "000000",
            })
        assert res.status_code == 429
        assert "Retry-After" in res.headers

    async def test_c3_l2_block_does_not_double_punish_l3(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """C3: When L2 blocks (5th MFA fail), L3 counter is NOT incremented for that attempt."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, mfa_token, _ = await self._setup_mfa_and_get_token(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app
        l3_key = f"login_attempts:{username}"

        # Send 4 wrong codes (L3 gets 4 increments, L2 also at 4)
        for _ in range(4):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": "000000",
                })

        l3_count_before = await test_redis_client.get(l3_key)
        l3_before = int(l3_count_before) if l3_count_before else 0

        # 5th wrong code → L2 blocks, L3 should NOT increment
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": "000000",
            })

        l3_count_after = await test_redis_client.get(l3_key)
        l3_after = int(l3_count_after) if l3_count_after else 0

        # L3 should NOT have been incremented on the 5th attempt
        assert l3_after == l3_before

    async def test_c4_correct_code_after_some_failures_succeeds(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """C4: Correct MFA code after <5 failures still works."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, mfa_token, _ = await self._setup_mfa_and_get_token(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app

        # 3 wrong codes
        for _ in range(3):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": "000000",
                })

        # Correct code should still work
        fresh_code = pyotp.TOTP(secret).now()
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": fresh_code,
            })
        assert res.status_code == 200
        assert "access_token" in res.cookies


# =============================================================================
# SECTION D: BACKUP CODE EDGE CASES
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestBackupCodeEdgeCases:
    """D1-D4: Backup code consumption, reuse, and exhaustion."""

    async def _setup_mfa_and_get_token(
        self, client: AsyncClient, username: str, password: str, test_redis_client
    ) -> tuple:
        """Helper: enable MFA, logout, re-login, return (secret, mfa_token, backup_codes)."""
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        backup_codes = enable_res.json()["backup_codes"]
        await client.post("/api/auth/logout")

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        mfa_token = login_res.json()["mfa_token"]
        return secret, mfa_token, backup_codes

    async def test_d1_backup_code_consumed_after_use(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client, db: AsyncSession
    ):
        """D1: Using a backup code consumes it (cannot reuse)."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, mfa_token, backup_codes = await self._setup_mfa_and_get_token(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app

        # Use first backup code
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": backup_codes[0],
            })
        assert res.status_code == 200

        # Verify code was consumed in DB
        from app.services import user_service
        user = await user_service.get_user_by_username(db, username=username)
        remaining_hashes = json.loads(user.backup_codes_hashed)
        assert len(remaining_hashes) == 7  # One consumed

    async def test_d2_second_backup_code_works(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """D2: Different backup codes work for subsequent logins."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, mfa_token, backup_codes = await self._setup_mfa_and_get_token(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app

        # Use first backup code
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res1 = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": backup_codes[0],
            })
        assert res1.status_code == 200

        # Login again, use second backup code
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token2 = login_res.json()["mfa_token"]
            res2 = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token2, "code": backup_codes[1],
            })
        assert res2.status_code == 200

    async def test_d3_reused_backup_code_rejected(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """D3: Already-used backup code is rejected on second use."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, mfa_token, backup_codes = await self._setup_mfa_and_get_token(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app
        used_code = backup_codes[0]

        # Use first backup code
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": used_code,
            })
        assert res.status_code == 200

        # Login again, try same backup code
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token2 = login_res.json()["mfa_token"]
            res2 = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token2, "code": used_code,
            })
        assert res2.status_code == 401

    async def test_d4_all_backup_codes_exhausted(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client, db: AsyncSession
    ):
        """D4: After all 8 backup codes used, only TOTP works."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA and get backup codes
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        backup_codes = enable_res.json()["backup_codes"]
        await client.post("/api/auth/logout")

        from app.main import fastapi_app

        # Use all 8 backup codes
        for i, bc in enumerate(backup_codes):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                login_res = await c.post("/api/auth/login", data={
                    "username": username, "password": password,
                })
                mfa_token = login_res.json()["mfa_token"]
                res = await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": bc,
                })
            assert res.status_code == 200, f"Backup code {i} failed"

        # All used. Try a random backup code → should fail
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": backup_codes[0],
            })
        assert res.status_code == 401

        # TOTP should still work
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]
            fresh_code = pyotp.TOTP(secret).now()
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": fresh_code,
            })
        assert res.status_code == 200


# =============================================================================
# SECTION E: MIXED / ABUSE SCENARIOS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestMixedAbuseScenarios:
    """E1-E3: Cross-flow abuse patterns."""

    async def _enable_mfa_for_user(
        self, client: AsyncClient, username: str, password: str, test_redis_client
    ) -> tuple:
        """Helper: enable MFA and return (secret, backup_codes)."""
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        backup_codes = enable_res.json()["backup_codes"]
        await client.post("/api/auth/logout")
        return secret, backup_codes

    async def test_e1_password_fail_then_mfa_fail_cumulative(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """E1: 4 password fails → correct password → 1 MFA fail → L3 counter = 5 → lockout."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, _ = await self._enable_mfa_for_user(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app
        l3_key = f"login_attempts:{username}"

        # 4 wrong passwords (L3 = 4)
        for _ in range(4):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                await c.post("/api/auth/login", data={
                    "username": username, "password": "WrongPass!",
                })

        l3_count = await test_redis_client.get(l3_key)
        assert int(l3_count) == 4

        # Correct password → get mfa_token (counter NOT reset)
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # 1 wrong MFA → L3 becomes 5 → triggers lockout
            await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": "000000",
            })

        lockout_key = f"account_lockout:{username}"
        is_locked = await test_redis_client.exists(lockout_key)
        assert is_locked == 1

    async def test_e2_cycling_login_mfa_fail_cumulative_lockout(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """E2: Cycling login→MFA fail→login→MFA fail accumulates L3 counter."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]
        secret, _ = await self._enable_mfa_for_user(
            client, username, password, test_redis_client
        )

        from app.main import fastapi_app
        l3_key = f"login_attempts:{username}"

        # Each cycle: correct password → wrong MFA code
        for _ in range(4):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                login_res = await c.post("/api/auth/login", data={
                    "username": username, "password": password,
                })
                mfa_token = login_res.json()["mfa_token"]
                await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": "000000",
                })

        # L3 should be 4 (one MFA fail per cycle)
        l3_count = await test_redis_client.get(l3_key)
        assert l3_count is not None
        assert int(l3_count) == 4

    async def test_e3_expired_mfa_token_no_side_effects(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """E3: Submitting code with expired mfa_token → 401, no counter changes."""
        import jwt as jose_jwt

        username = regular_user_in_db["username"]
        user_id = regular_user_in_db["id"]

        # Create an expired MFA token
        expired_payload = {
            "sub": username,
            "user_id": user_id,
            "type": "mfa",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            "jti": "expired-test-jti",
        }
        expired_token = jose_jwt.encode(
            expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )

        attempt_key = f"mfa_attempts:{username}"
        l3_key = f"login_attempts:{username}"

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": expired_token, "code": "123456",
            })
        assert res.status_code == 401

        # No counters should have been touched
        mfa_count = await test_redis_client.get(attempt_key)
        assert mfa_count is None
        l3_count = await test_redis_client.get(l3_key)
        assert l3_count is None


# =============================================================================
# SECTION F: MFA SETUP / MANAGEMENT EDGE CASES
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestMfaSetupEdgeCases:
    """F1-F4: Setup flow edge cases."""

    async def test_f1_setup_without_enable_login_normal(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """F1: Setup MFA but don't enable → login works normally (no MFA challenge)."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Login and setup MFA (but don't enable)
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        assert setup_res.status_code == 200
        await client.post("/api/auth/logout")

        # Login again → should work normally (no MFA challenge)
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.status_code == 200
        data = res.json()
        assert "mfa_required" not in data or data.get("mfa_required") is not True
        assert "access_token" in res.cookies

    async def test_f2_enable_mfa_with_expired_setup_secret(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """F2: Trying to enable MFA after Redis setup key expired → 400."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        await client.post("/api/auth/mfa/setup")

        # Delete the Redis setup key to simulate expiration
        redis_key = f"mfa_setup:{regular_user_in_db['id']}"
        await test_redis_client.delete(redis_key)

        # Try to enable → should fail
        res = await client.post("/api/auth/mfa/enable", json={"code": "123456"})
        assert res.status_code == 400

    async def test_f3_disable_mfa_then_login_normal(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """F3: Enable then disable MFA → login works normally."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})

        # Disable MFA
        await client.post("/api/auth/mfa/disable", json={"password": password})

        await client.post("/api/auth/logout")

        # Login should not require MFA
        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
        assert res.status_code == 200
        assert "access_token" in res.cookies

    async def test_f4_regenerate_backup_codes_invalidates_old(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """F4: After regenerating backup codes, old codes no longer work."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        old_codes = enable_res.json()["backup_codes"]

        # Regenerate backup codes
        regen_res = await client.post("/api/auth/mfa/backup-codes", json={
            "password": password,
        })
        assert regen_res.status_code == 200
        new_codes = regen_res.json()["backup_codes"]

        await client.post("/api/auth/logout")

        from app.main import fastapi_app

        # Try old backup code → should fail
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": old_codes[0],
            })
        assert res.status_code == 401

        # New backup code should work
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]
            res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": new_codes[0],
            })
        assert res.status_code == 200


# =============================================================================
# SECTION G: TOTP REPLAY PROTECTION
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestTotpReplayProtection:
    """G1-G2: TOTP replay and near-boundary behavior."""

    async def test_g1_same_totp_code_rejected_on_second_use(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """G1: Same TOTP code used twice within same time step → second use rejected."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})
        await client.post("/api/auth/logout")

        from app.main import fastapi_app

        # First login with TOTP
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]
            fresh_code = pyotp.TOTP(secret).now()
            res1 = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": fresh_code,
            })
        assert res1.status_code == 200

        # Second login, try same code immediately (replay)
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res2 = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token2 = login_res2.json()["mfa_token"]
            # Use the same code (if time step hasn't changed, should be rejected)
            same_code = fresh_code
            res2 = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token2, "code": same_code,
            })

        # TOTP replay protection rejects reused time step codes
        assert res2.status_code == 401


# =============================================================================
# SECTION H: OBSERVABILITY / LOGGING
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestMfaObservability:
    """H: Verify structured log output for security-critical MFA events."""

    async def test_h1_mfa_enable_emits_structured_log(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client, caplog
    ):
        """H1: Enabling MFA emits 'mfa_enabled' structured log."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()

        with caplog.at_level(logging.INFO):
            await client.post("/api/auth/mfa/enable", json={"code": code})

        # Check that structured log was emitted
        assert any("mfa_enabled" in record.message or "mfa.enable" in str(getattr(record, 'msg', ''))
                    for record in caplog.records)

    async def test_h2_mfa_failed_verification_emits_warning(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client, caplog
    ):
        """H2: Failed MFA verification emits warning log."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})
        await client.post("/api/auth/logout")

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            with caplog.at_level(logging.WARNING):
                await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": "000000",
                })

        assert any("mfa_failed" in record.message or "mfa.verify_failed" in str(getattr(record, 'msg', ''))
                    for record in caplog.records)

    async def test_h3_mfa_disable_emits_log(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client, caplog
    ):
        """H3: Disabling MFA emits 'mfa_disabled' log."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})

        with caplog.at_level(logging.INFO):
            await client.post("/api/auth/mfa/disable", json={"password": password})

        assert any("mfa_disabled" in record.message or "mfa.disable" in str(getattr(record, 'msg', ''))
                    for record in caplog.records)

    async def test_h4_backup_code_used_emits_log(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client, caplog
    ):
        """H4: Using a backup code emits 'backup_code_used' log with remaining count."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        enable_res = await client.post("/api/auth/mfa/enable", json={"code": code})
        backup_codes = enable_res.json()["backup_codes"]
        await client.post("/api/auth/logout")

        from app.main import fastapi_app
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            with caplog.at_level(logging.INFO):
                await c.post("/api/auth/verify-mfa", json={
                    "mfa_token": mfa_token, "code": backup_codes[0],
                })

        assert any("backup_code_used" in record.message or "mfa.backup_used" in str(getattr(record, 'msg', ''))
                    for record in caplog.records)


# =============================================================================
# SECTION I: MFA ENFORCEMENT FOR PRIVILEGED ACCOUNTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestMfaEnforcement:
    """B4: Privileged accounts (admin/manager) must have MFA enabled."""

    async def test_i1_admin_without_mfa_blocked_on_business_endpoint(
        self, client: AsyncClient, admin_user_in_db: dict, test_redis_client, monkeypatch
    ):
        """I1: Admin without MFA → 403 on business endpoints when enforcement is enabled."""
        monkeypatch.setattr(settings, "MFA_ENFORCE_ROLES", ["admin", "manager"])

        # Login (auth endpoints use get_current_user, not get_current_active_user)
        login_res = await client.post("/api/auth/login", data={
            "username": admin_user_in_db["username"],
            "password": admin_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # Try a business endpoint (uses get_current_active_user → MFA check)
        profile_res = await client.get("/api/profile")
        assert profile_res.status_code == 403
        assert "MFA" in profile_res.json()["detail"]

    async def test_i2_admin_can_still_access_mfa_setup(
        self, client: AsyncClient, admin_user_in_db: dict, test_redis_client, monkeypatch
    ):
        """I2: Admin without MFA can still access /mfa/setup to enable it."""
        monkeypatch.setattr(settings, "MFA_ENFORCE_ROLES", ["admin", "manager"])

        login_res = await client.post("/api/auth/login", data={
            "username": admin_user_in_db["username"],
            "password": admin_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # MFA endpoints use get_current_user (not get_current_active_user)
        status_res = await client.get("/api/auth/mfa/status")
        assert status_res.status_code == 200
        assert status_res.json()["mfa_enabled"] is False

        setup_res = await client.post("/api/auth/mfa/setup")
        assert setup_res.status_code == 200
        assert "secret" in setup_res.json()

    async def test_i3_admin_with_mfa_enabled_passes_enforcement(
        self, client: AsyncClient, admin_user_in_db: dict, test_redis_client, monkeypatch
    ):
        """I3: Admin with MFA enabled → business endpoints work normally."""
        monkeypatch.setattr(settings, "MFA_ENFORCE_ROLES", ["admin", "manager"])

        # Login and enable MFA
        await client.post("/api/auth/login", data={
            "username": admin_user_in_db["username"],
            "password": admin_user_in_db["password"],
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})

        # Business endpoint should work now
        profile_res = await client.get("/api/profile")
        assert profile_res.status_code == 200

    async def test_i4_regular_user_not_affected_by_enforcement(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client, monkeypatch
    ):
        """I4: Regular user (not in enforce list) works without MFA."""
        monkeypatch.setattr(settings, "MFA_ENFORCE_ROLES", ["admin", "manager"])

        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200

        # Regular user should not be blocked
        profile_res = await client.get("/api/profile")
        assert profile_res.status_code == 200

    async def test_i5_mfa_token_blacklisted_after_use(
        self, client: AsyncClient, regular_user_in_db: dict, test_redis_client
    ):
        """I5: Used mfa_token is blacklisted and cannot be reused."""
        username = regular_user_in_db["username"]
        password = regular_user_in_db["password"]

        # Enable MFA
        await client.post("/api/auth/login", data={
            "username": username, "password": password,
        })
        setup_res = await client.post("/api/auth/mfa/setup")
        secret = setup_res.json()["secret"]
        code = pyotp.TOTP(secret).now()
        await client.post("/api/auth/mfa/enable", json={"code": code})
        await client.post("/api/auth/logout")

        from app.main import fastapi_app

        # Login and get mfa_token
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            login_res = await c.post("/api/auth/login", data={
                "username": username, "password": password,
            })
            mfa_token = login_res.json()["mfa_token"]

            # Use the mfa_token with valid TOTP
            fresh_code = pyotp.TOTP(secret).now()
            verify_res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": fresh_code,
            })
        assert verify_res.status_code == 200

        # Try to reuse the same mfa_token (should be blacklisted)
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            reuse_res = await c.post("/api/auth/verify-mfa", json={
                "mfa_token": mfa_token, "code": "123456",
            })
        assert reuse_res.status_code == 401
        assert "already used" in reuse_res.json()["detail"]
