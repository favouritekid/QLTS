# tests/services/test_auth_security_hardening.py
"""
Security hardening tests for auth flow.

Covers:
1. Reset token lifecycle — only latest token accepted, older ones rejected
2. Reset password fail-closed — rollback when session invalidation fails
3. Account lockout fail-closed — login blocked when Redis is down
4. Forgot-password throttling fail-closed — silently blocked when Redis is down
"""
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app import models
from app.security import get_password_hash, create_password_reset_token
from app.services import user_service
from app.services.auth_service import verify_password_reset_token


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def reset_user(db: AsyncSession) -> models.User:
    """Create a user for password reset tests."""
    user = models.User(
        username="reset_test_user",
        email="reset_test@example.com",
        password_hash=get_password_hash("OldPassword123!"),
        role="user",
        status="active",
        full_name="Reset Test User",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# =============================================================================
# 1. RESET TOKEN LIFECYCLE
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestResetTokenLifecycle:
    """Only the latest reset token should be accepted."""

    async def test_verify_token_returns_dict_with_gen(self):
        """verify_password_reset_token returns dict with email and gen."""
        token = create_password_reset_token("test@example.com", generation=3)
        result = verify_password_reset_token(token)

        assert result is not None
        assert result["email"] == "test@example.com"
        assert result["gen"] == 3

    async def test_verify_token_without_gen_defaults_to_1(self):
        """Legacy tokens without gen field default to generation 1."""
        # Simulate legacy token (no gen claim)
        import jwt
        from app.config import settings

        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "sub": "legacy@example.com",
            "scope": "password_reset",
            # no "gen" field
        }
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        result = verify_password_reset_token(token)

        assert result is not None
        assert result["email"] == "legacy@example.com"
        assert result["gen"] == 1

    async def test_stale_token_rejected_when_newer_exists(self, db: AsyncSession, reset_user: models.User):
        """Older reset token is rejected when a newer one was requested."""
        from app.database import safe_redis_set

        # Simulate generation counter at 2 (user requested reset twice)
        gen_key = f"reset_gen:{reset_user.id}"
        await safe_redis_set(gen_key, "2", ex=1800)

        # Create token with generation 1 (the older request)
        old_token = create_password_reset_token(reset_user.email, generation=1)

        with pytest.raises(Exception) as exc_info:
            await user_service.reset_password(db, token=old_token, new_password="NewSecure123!")

        assert "superseded" in str(exc_info.value).lower() or "InvalidToken" in type(exc_info.value).__name__

    async def test_latest_token_accepted(self, db: AsyncSession, reset_user: models.User):
        """Latest generation reset token is accepted."""
        from app.database import safe_redis_set

        gen_key = f"reset_gen:{reset_user.id}"
        await safe_redis_set(gen_key, "2", ex=1800)

        # Create token with current generation
        token = create_password_reset_token(reset_user.email, generation=2)

        # Mock HIBP to avoid external call
        with patch("app.services.user_service.check_password_breached", new_callable=AsyncMock, return_value=(False, 0)):
            user, callback = await user_service.reset_password(
                db, token=token, new_password="BrandNewPass123!"
            )
            assert user.id == reset_user.id

    async def test_token_single_use_enforced(self, db: AsyncSession, reset_user: models.User):
        """Token cannot be used twice — marked used BEFORE flush, not in callback."""
        from app.database import safe_redis_set

        gen_key = f"reset_gen:{reset_user.id}"
        await safe_redis_set(gen_key, "1", ex=1800)

        token = create_password_reset_token(reset_user.email, generation=1)

        # First use succeeds — token is marked used during reset_password (before flush)
        with patch("app.services.user_service.check_password_breached", new_callable=AsyncMock, return_value=(False, 0)):
            user, callback = await user_service.reset_password(
                db, token=token, new_password="FirstNewPass123!"
            )
            # Token is already marked used in Redis at this point (not waiting for callback)

        # Second use fails immediately (token already marked used)
        with pytest.raises(Exception) as exc_info:
            await user_service.reset_password(
                db, token=token, new_password="SecondNewPass123!"
            )
        assert "already been used" in str(exc_info.value).lower()

    async def test_token_claimed_atomically_via_set_nx(self, db: AsyncSession, reset_user: models.User):
        """Token is claimed atomically via SET NX at the start of reset_password().
        Even if the function crashes later, the token is already consumed."""
        from app.database import safe_redis_set, safe_redis_get
        import hashlib

        gen_key = f"reset_gen:{reset_user.id}"
        await safe_redis_set(gen_key, "1", ex=1800)

        token = create_password_reset_token(reset_user.email, generation=1)
        token_hash = hashlib.sha256(token.encode()).hexdigest()[:32]
        used_key = f"reset_token_used:{token_hash}"

        # Before reset: key should not exist
        assert await safe_redis_get(used_key) is None

        with patch("app.services.user_service.check_password_breached", new_callable=AsyncMock, return_value=(False, 0)):
            await user_service.reset_password(db, token=token, new_password="TestPass123!")

        # After reset (before commit): used key should already exist (SET NX at top)
        used_value = await safe_redis_get(used_key)
        assert used_value is not None, "Token should be claimed atomically via SET NX"


# =============================================================================
# 2. RESET PASSWORD FAIL-CLOSED
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestResetPasswordFailClosed:
    """Password reset should rollback if session invalidation fails."""

    async def test_reset_password_rollback_preserves_old_password(
        self,
        db: AsyncSession,
        reset_user: models.User,
    ):
        """After flush + rollback, the DB still has the old password hash.

        This proves the fail-closed contract: if session invalidation fails
        and router rolls back, the password change is undone.

        We test the service layer directly: change_password() has the same
        flush-only contract and doesn't need Redis token infrastructure.
        """
        from app.security import verify_password
        from sqlalchemy import select

        user_id = reset_user.id
        # Commit user first so it survives a rollback
        await db.commit()

        # Use change_password (same flush-only contract, no Redis token needed)
        with patch("app.services.user_service.check_password_breached", new_callable=AsyncMock, return_value=(False, 0)):
            _, callback = await user_service.change_password(
                db,
                user=reset_user,
                old_password="OldPassword123!",
                new_password="FailClosedTest123!",
            )

        # After flush: in-memory hash is updated
        assert not verify_password("OldPassword123!", reset_user.password_hash), \
            "In-memory hash should be updated after flush"

        # Simulate router fail-closed: session invalidation failed → rollback
        await db.rollback()

        # Re-read from DB to verify persisted state
        result = await db.execute(
            select(models.User.password_hash).where(models.User.id == user_id)
        )
        persisted_hash = result.scalar_one()
        assert verify_password("OldPassword123!", persisted_hash), \
            "After rollback, DB must still have the old password hash"


# =============================================================================
# 3. ACCOUNT LOCKOUT FAIL-CLOSED
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestAccountLockoutFailClosed:
    """Account lockout should fail-closed when Redis is unavailable."""

    async def test_check_lockout_returns_locked_on_redis_failure(self):
        """When Redis fails, check_lockout should report locked (fail-closed)."""
        from app.security.account_lockout import AccountLockoutService

        with patch("app.security.account_lockout.safe_redis_exists", side_effect=ConnectionError("Redis down")):
            is_locked, remaining = await AccountLockoutService.check_lockout("test_user")

        assert is_locked is True
        assert remaining == 60  # Temporary lockout

    async def test_record_failed_attempt_returns_locked_on_redis_failure(self):
        """When Redis fails to record attempt, account should be treated as locked."""
        from app.security.account_lockout import AccountLockoutService

        with patch("app.security.account_lockout.safe_redis_get", side_effect=ConnectionError("Redis down")):
            is_locked = await AccountLockoutService.record_failed_attempt(
                db=AsyncMock(), username="test_user", ip_address="1.2.3.4"
            )

        assert is_locked is True


# =============================================================================
# 4. FORGOT-PASSWORD THROTTLING FAIL-CLOSED
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestForgotPasswordThrottlingFailClosed:
    """Forgot-password per-email throttling should fail-closed when Redis is down."""

    async def test_forgot_password_blocked_when_redis_down(
        self,
        db: AsyncSession,
        reset_user: models.User,
    ):
        """When Redis is down, forgot-password should silently block (no email sent)."""
        # safe_redis_get is called first in the rate-limit check; if it raises,
        # the function should return early (fail-closed) without sending email.
        with (
            patch("app.database.redis_breaker.call_async", side_effect=ConnectionError("Redis down")),
            patch("app.services.user_service.create_password_reset_token") as mock_token,
        ):
            await user_service.handle_forgot_password(db, email_in=reset_user.email)

        # Token should NOT have been created (blocked before reaching that point)
        mock_token.assert_not_called()

    async def test_forgot_password_no_email_when_gen_bump_fails(
        self,
        db: AsyncSession,
        reset_user: models.User,
    ):
        """If generation bump fails, email should NOT be sent (fail-closed).

        The rate-limit pipeline runs first, so we must let it succeed.
        Only the second pipeline call (gen bump) should fail.
        """
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        call_count = 0

        @asynccontextmanager
        async def selective_pipeline_mock(**kwargs):
            """First call (rate-limit) succeeds, second call (gen bump) fails."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Rate-limit pipeline — return a mock pipe that works
                pipe = MagicMock()
                pipe.incr = MagicMock()
                pipe.expire = MagicMock()
                pipe.execute = AsyncMock(return_value=[1, True])
                yield pipe
            else:
                # Gen bump pipeline — fail
                raise ConnectionError("Redis pipeline down for gen bump")

        with (
            # Let safe_redis_get work normally (rate-limit GET check)
            patch("app.services.user_service.safe_redis_get", return_value=None),
            patch("app.services.user_service.safe_redis_pipeline", side_effect=selective_pipeline_mock),
            patch("app.services.user_service.create_password_reset_token") as mock_token,
        ):
            await user_service.handle_forgot_password(db, email_in=reset_user.email)

        # Token should NOT have been created (gen bump failed → no email)
        mock_token.assert_not_called()
