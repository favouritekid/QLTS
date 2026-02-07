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
        import time
        secret = mfa_service.generate_totp_secret()
        totp = pyotp.TOTP(secret)
        # Generate code for previous time step
        prev_counter = totp.timecode(time.time()) - 1
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
        """Codes should be 8-char hex strings."""
        plaintext, _ = mfa_service.generate_backup_codes(count=4)
        for code in plaintext:
            assert len(code) == 8
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
        from jose import jwt as jose_jwt

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
        from jose import jwt as jose_jwt

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
