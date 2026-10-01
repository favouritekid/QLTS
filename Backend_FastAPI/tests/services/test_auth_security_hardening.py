# tests/services/test_auth_security_hardening.py
"""
Security hardening tests for auth flow.

Covers:
1. Reset token lifecycle — only latest token accepted, older ones rejected
2. Reset password fail-closed — rollback when session invalidation fails
3. Account lockout service contract — "Redis could not answer" is its own
   answer (neither "locked" nor "not locked"); an unreadable attempt counter
   is never reset
4. Forgot-password throttling fail-closed — silently blocked when Redis is down
5. Refresh blocked by the user-level blacklist
6. /auth/login lockout, asserted at the endpoint: a lockout Redis confirmed
   with a real TTL ⇒ 429; a lockout state that cannot be verified (no answer
   to EXISTS or TTL, an unexpected error, a key with no expiry) ⇒ 503
   AUTH_STATE_UNAVAILABLE with nothing created (cookies, body, DB sessions,
   Redis keys, counters); TTL -2 ⇒ not locked. ``AuthStateUnavailable`` is
   the one source of that 503's code and Retry-After.
7. /auth/verify-mfa: the Layer-3 attempt counter is never reset by a read error
8. Strict Redis read helpers (``redis_*_or_raise``)
9. /auth/refresh: Redis not answering the jti-blacklist / user-blacklist /
   session read is a 503 BEFORE any write (never scored as token abuse, never
   a rotation), and it is exactly ``/login``'s 503 (one source:
   ``AuthStateUnavailable``); any OTHER error on the jti-blacklist read is a
   plain 500 (never that retryable 503, never a fall-through); none of these
   paths logs the jti, the key or the exception message
10. ``get_current_user`` (HTTP), Socket.IO connect and ``revalidate_auth``:
   Redis not answering the ``user_blacklist`` read is never "not blacklisted"
   (HTTP 503 ``AUTH_STATE_UNAVAILABLE`` / connection refused / disconnected),
   for a blacklisted and a normal user alike; any other error on that read
   over HTTP is a plain 500
11. ``get_current_user`` STEP 2: Redis not answering the ``blacklist:{access_jti}``
   read is the same 503 (a logged-out and a live token alike), any other error
   a plain 500. ``session:{r_jti}`` (HTTP STEP 4, ``revalidate_auth``) Redis
   cannot answer is neither a miss nor a pass: the DB row decides — live ⇒
   allowed, revoked or unreadable ⇒ refused; an ANSWERED miss is still refused
"""
import hashlib
import logging
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

import pyotp
import pytest
import pytest_asyncio
from aiobreaker import CircuitBreakerState
from cryptography.fernet import Fernet
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app import database as db_module
from app import models
from app.config import settings
from app.security import account_lockout as lockout_module
from app.security import get_password_hash, create_password_reset_token
from app.services import mfa_service, user_service
from app.services.auth_service import verify_password_reset_token
from app.utils.exceptions import AccountLockoutStateUnavailable, AuthStateUnavailable


# =============================================================================
# FIXTURES
# =============================================================================

def _reset_redis_breaker(breaker) -> None:
    """Put the singleton breaker back to its initial state: CLOSED, counter 0.

    Same recipe as ``_force_redis_breaker_closed`` in
    ``tests/services/test_resilience.py``. Without it an OPEN breaker leaks into
    the next test of the same process and every ``safe_redis_*`` there gets
    ``CircuitBreakerError`` for 60 seconds.
    """
    breaker.close()
    breaker._state_storage.reset_counter()
    breaker._state_storage.opened_at = None
    assert breaker.current_state is CircuitBreakerState.CLOSED
    assert breaker.fail_counter == 0


@pytest.fixture
def redis_breaker_reset():
    """Clean breaker BEFORE the test and hand it back clean AFTER (even on red)."""
    breaker = db_module.redis_breaker
    _reset_redis_breaker(breaker)
    try:
        yield breaker
    finally:
        _reset_redis_breaker(breaker)


def _redis_command_failing_on(command: str, key_prefix: str, exc_type, calls: list):
    """Patch ONE client command so it raises ``exc_type`` for keys under ``key_prefix``.

    Every other key goes to the real (fake) server, so exactly one check of the
    code under test sees the outage.

    The failure is injected at the CLIENT (``redis_client.<command>``) with a
    plain ``async def``, never an AsyncMock/MagicMock: ``call_async`` reads
    ``getattr(func, "_ignore_on_call", False)`` and a Mock answers truthy, which
    silently routes the call AROUND the breaker.
    """
    original = getattr(db_module.redis_client, command)

    async def _command(*args, **kwargs):
        key = args[0] if args else None
        if isinstance(key, str) and key.startswith(key_prefix):
            calls.append(key)
            raise exc_type("simulated Redis outage")
        return await original(*args, **kwargs)

    return patch.object(db_module.redis_client, command, _command)


_REDIS_COMMANDS_USED_BY_LOGIN = (
    "get", "exists", "set", "delete", "ttl", "incr", "expire", "getdel", "eval",
)


@contextmanager
def _redis_down(exc_type=RedisConnectionError):
    """Every Redis command used by the login path raises ``exc_type``."""
    calls = []

    async def _command(*args, **kwargs):
        calls.append(args[0] if args else None)
        raise exc_type("simulated Redis outage")

    with ExitStack() as stack:
        for name in _REDIS_COMMANDS_USED_BY_LOGIN:
            stack.enter_context(patch.object(db_module.redis_client, name, _command))
        yield calls


@pytest_asyncio.fixture
async def mfa_login_user(setup_test_database, monkeypatch) -> dict:
    """An ACTIVE user with TOTP MFA enabled, COMMITTED so the app's own sessions see it."""
    monkeypatch.setattr(settings, "MFA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    secret = pyotp.random_base32()
    username = "lockout_mfa_user"
    password = "LockoutMfaPass123!"
    async with db_module.AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username=username,
                email="lockout_mfa_user@example.com",
                password_hash=get_password_hash(password),
                role="user",
                status="active",
                full_name="Lockout MFA User",
                mfa_enabled=True,
                totp_secret_encrypted=mfa_service.encrypt_secret(secret),
            )
            session.add(user)
            await session.flush()
            user_id = user.id
    return {"id": user_id, "username": username, "password": password, "secret": secret}


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
class TestAccountLockoutServiceContract:
    """``AccountLockoutService`` when Redis cannot answer.

    The outage is injected at the Redis CLIENT, not at a ``safe_redis_*``
    wrapper. The previous version of these two tests patched
    ``safe_redis_exists``/``safe_redis_get`` in ``account_lockout`` — names the
    service no longer reads, so such a patch is silently inert (or raises
    ``AttributeError``). It also made the wrapper RAISE, which the real
    wrapper never does: it swallows the error and answers "absent".
    """

    async def test_check_lockout_raises_unavailable_when_exists_unreadable(
        self, clear_redis_keys, redis_breaker_reset
    ):
        """No answer from Redis ⇒ ``AccountLockoutStateUnavailable``, not ``(True, 60)``.

        ``(True, 60)`` made ``/login`` answer every user with the 429 "account
        temporarily locked"; ``(False, None)`` would let the login through.
        """
        from app.security.account_lockout import AccountLockoutService

        calls = []
        with _redis_command_failing_on("exists", "account_lockout:", RedisConnectionError, calls):
            with pytest.raises(AccountLockoutStateUnavailable) as excinfo:
                await AccountLockoutService.check_lockout("test_user")

        assert calls, "the lockout EXISTS never reached the Redis client"
        assert excinfo.value.status_code == 503
        assert excinfo.value.error_code == "AUTH_STATE_UNAVAILABLE"

    async def test_record_failed_attempt_unreadable_counter_is_not_reset(
        self, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """Counter unreadable ⇒ stored count untouched, nothing locked, returns False.

        The return value now means "THIS call wrote the lockout key". The old
        ``True`` claimed "account is now locked" while nothing was locked; both
        callers (``/login``, ``/verify-mfa``) discard the value either way.
        """
        from app.security.account_lockout import AccountLockoutService

        attempts_key = "login_attempts:test_user"
        await test_redis_client.set(attempts_key, "3", ex=1800)

        calls = []
        with _redis_command_failing_on("get", "login_attempts:", RedisConnectionError, calls):
            locked_now = await AccountLockoutService.record_failed_attempt(
                db=AsyncMock(), username="test_user", ip_address="1.2.3.4"
            )

        assert calls, "the attempt-counter GET never reached the Redis client"
        assert locked_now is False
        assert await test_redis_client.get(attempts_key) == "3"
        assert await test_redis_client.exists("account_lockout:test_user") == 0


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


# =============================================================================
# 5. REFRESH ENDPOINT — USER BLACKLIST CHECK
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.security
class TestRefreshBlockedByUserBlacklist:
    """Refresh endpoint must reject requests when user is in global blacklist."""

    async def test_refresh_rejected_when_user_blacklisted(
        self,
        client: AsyncClient,
        regular_user_in_db: dict,
    ):
        """After user_blacklist is set, /auth/refresh must return 401."""
        from app.database import safe_redis_set

        # Login to get valid tokens
        login_res = await client.post("/api/auth/login", data={
            "username": regular_user_in_db["username"],
            "password": regular_user_in_db["password"],
        })
        assert login_res.status_code == 200
        user_data = login_res.json().get("user", {})
        user_id = user_data.get("id")
        assert user_id is not None

        # Simulate password change invalidation: set user_blacklist
        await safe_redis_set(f"user_blacklist:{user_id}", "1", ex=3600)

        # Attempt refresh — should be blocked
        refresh_res = await client.post("/api/auth/refresh")
        assert refresh_res.status_code == 401, \
            f"Refresh should be blocked when user is blacklisted, got {refresh_res.status_code}"


# =============================================================================
# 6. /auth/login LOCKOUT — "LOCKED" (429) vs "CANNOT VERIFY" (503)
# =============================================================================
#
# ``check_lockout`` reads ``account_lockout:{username}`` (EXISTS, then TTL)
# BEFORE the password is checked. Every Redis answer maps to ONE response:
#   * EXISTS=0, or EXISTS=1 then TTL=-2 ⇒ no lockout: correct 200, wrong 401
#   * EXISTS=1 then TTL>=0              ⇒ 429, Retry-After = that TTL
#   * EXISTS=1 then TTL=-1 (no expiry)  ⇒ 503 AUTH_STATE_UNAVAILABLE + alert log
#   * no answer to EXISTS or to TTL     ⇒ 503 AUTH_STATE_UNAVAILABLE
#     (ConnectionError, TimeoutError, breaker OPEN; an unexpected error too,
#     under its own log event, with the traceback)
# Every 503: any password, body exactly {detail, error_code}, Retry-After 60,
# and NOTHING created or changed: no token (cookie, Set-Cookie, body: access,
# refresh or mfa), no DB session, no login_history row, no ``session:*`` key,
# no counter write.
#
# Before (9028b26b): TTL unreadable ⇒ 429 with Retry-After 900 (a duration
# nobody read); TTL -1 ⇒ "not locked" ⇒ 200. Before that (base): no answer to
# EXISTS ⇒ ``(True, 60)`` ⇒ the 429 "Tài khoản tạm thời bị khóa..." to everyone.

LOGIN_URL = "/api/auth/login"
VERIFY_MFA_URL = "/api/auth/verify-mfa"
WRONG_PASSWORD = "Definitely-Wrong-Password-1!"
# Owner policy values, pinned as literals here; ``AuthStateUnavailable`` is
# checked against them (TestAuthStateUnavailableSingleSource).
AUTH_STATE_ERROR_CODE = "AUTH_STATE_UNAVAILABLE"
AUTH_STATE_RETRY_AFTER = "60"
# A lockout TTL that no code path produces on its own (not 60, not the full
# duration), so the header shows WHICH value the endpoint used.
LOCKOUT_KEY_TTL = 777
PRESET_ATTEMPTS = "2"
_TOKEN_NAMES = ("access_token", "refresh_token", "mfa_token")
# Log events of ``app.security.account_lockout`` for a lockout state it could
# not verify. Two causes, two events: they must never be merged.
_EVENT_OUTAGE = "account_lockout_state_unavailable"
_EVENT_UNEXPECTED = "account_lockout_check_unexpected_error"
_EVENT_NO_EXPIRY = "account_lockout_key_without_expiry"


async def _post_login(client: AsyncClient, username: str, password: str):
    client.cookies.clear()
    res = await client.post(LOGIN_URL, data={"username": username, "password": password})
    client.cookies.clear()
    return res


async def _post_verify_mfa(client: AsyncClient, mfa_token: str, code: str):
    client.cookies.clear()
    res = await client.post(VERIFY_MFA_URL, json={"mfa_token": mfa_token, "code": code})
    client.cookies.clear()
    return res


async def _live_session_count(user_id: int) -> int:
    """Non-revoked DB session rows of ``user_id`` — what a successful login creates."""
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count())
            .select_from(models.UserSession)
            .where(
                models.UserSession.user_id == user_id,
                models.UserSession.revoked_at.is_(None),
            )
        )
        return result.scalar_one()


async def _login_history_count(user_id: int) -> int:
    async with db_module.AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count())
            .select_from(models.LoginHistory)
            .where(models.LoginHistory.user_id == user_id)
        )
        return result.scalar_one()


async def _auth_state(test_redis_client, user: dict) -> dict:
    """Everything a login attempt can create or change, read around the request.

    Read through ``test_redis_client`` (same fake server, NOT the app's client,
    so an injected outage or an OPEN breaker does not hide what is stored).
    """
    username = user["username"]
    return {
        "live_db_sessions": await _live_session_count(user["id"]),
        "login_history_rows": await _login_history_count(user["id"]),
        "session_keys": sorted(await test_redis_client.keys("session:*")),
        "login_attempts": await test_redis_client.get(f"login_attempts:{username}"),
        "account_lockout": await test_redis_client.get(f"account_lockout:{username}"),
        "mfa_attempts": await test_redis_client.get(f"mfa_attempts:{username}"),
    }


def _assert_no_tokens(res) -> None:
    """No token in a cookie, a Set-Cookie header, or the body."""
    for name in ("access_token", "refresh_token"):
        assert name not in res.cookies, res.headers
    for header in res.headers.get_list("set-cookie"):
        assert not header.startswith(("access_token=", "refresh_token=")), header
    for name in _TOKEN_NAMES:
        assert name not in res.text, res.text


def _assert_auth_state_unavailable(res) -> None:
    """The 503 of "lockout state could not be verified", and nothing else."""
    assert res.status_code == 503, res.text
    body = res.json()
    assert body == {
        "detail": AuthStateUnavailable.detail,
        "error_code": AUTH_STATE_ERROR_CODE,
    }, body
    assert res.headers.get("retry-after") == AUTH_STATE_RETRY_AFTER, res.headers
    _assert_no_tokens(res)


def _assert_locked_429(res) -> None:
    assert res.status_code == 429, res.text
    assert set(res.json()) == {"detail"}, res.text
    assert "khóa" in res.json()["detail"], res.text
    _assert_no_tokens(res)


def _password_for(user: dict, kind: str) -> str:
    return user["password"] if kind == "correct" else WRONG_PASSWORD


def _wrong_totp(secret: str) -> str:
    """A 6-digit code that is NOT valid anywhere near now (verify window is ±1 step)."""
    totp = pyotp.TOTP(secret)
    now = totp.timecode(datetime.now(timezone.utc))
    near = {totp.generate_otp(now + k) for k in range(-3, 4)}
    for candidate in ("000000", "111111", "222222", "333333", "444444", "555555",
                      "666666", "777777", "888888"):
        if candidate not in near:
            return candidate
    raise AssertionError("no wrong TOTP candidate available")


async def _preset_attempts(test_redis_client, username: str) -> None:
    await test_redis_client.set(f"login_attempts:{username}", PRESET_ATTEMPTS, ex=1800)


async def _lock(test_redis_client, username: str) -> None:
    await test_redis_client.set(f"account_lockout:{username}", "1", ex=LOCKOUT_KEY_TTL)


async def _lock_without_expiry(test_redis_client, username: str) -> None:
    key = f"account_lockout:{username}"
    await test_redis_client.set(key, "1")
    assert await test_redis_client.ttl(key) == -1


@contextmanager
def _lockout_expires_before_ttl_read(calls: list):
    """EXISTS still sees the lockout key; it expires right before TTL is read.

    Redis then really answers TTL=-2 ("no such key"). This is the race of a
    lockout that ends between the two reads of ``check_lockout``.
    """
    original_ttl = db_module.redis_client.ttl
    original_delete = db_module.redis_client.delete

    async def _ttl(*args, **kwargs):
        key = args[0] if args else None
        if isinstance(key, str) and key.startswith("account_lockout:"):
            await original_delete(key)
            answer = await original_ttl(*args, **kwargs)
            calls.append((key, answer))
            return answer
        return await original_ttl(*args, **kwargs)

    with patch.object(db_module.redis_client, "ttl", _ttl):
        yield calls


@contextmanager
def _lockout_log():
    """Record what ``app.security.account_lockout`` logs during the block."""
    recorder = _LogRecorder()
    with patch.object(lockout_module, "log", recorder):
        yield recorder


def _only_event(recorder, event: str):
    """``(level, kwargs)`` of the ONE record of ``event``; fails on 0 or 2+."""
    records = recorder.by_event().get(event, [])
    assert len(records) == 1, (event, recorder.events)
    return records[0]


@pytest.mark.asyncio
@pytest.mark.security
class TestLoginLockoutAnswered:
    """Controls: Redis ANSWERED. These pin the two sides the 503 must not widen into."""

    async def test_not_locked_correct_password_logs_in(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        user = regular_user_in_db

        res = await _post_login(client, user["username"], user["password"])

        assert res.status_code == 200, res.text
        assert "access_token" in res.cookies and "refresh_token" in res.cookies
        state = await _auth_state(test_redis_client, user)
        assert state["live_db_sessions"] == 1
        assert len(state["session_keys"]) == 1

    async def test_not_locked_wrong_password_is_401_and_counted(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        user = regular_user_in_db
        await _preset_attempts(test_redis_client, user["username"])

        res = await _post_login(client, user["username"], WRONG_PASSWORD)

        assert res.status_code == 401, res.text
        _assert_no_tokens(res)
        assert await test_redis_client.get(f"login_attempts:{user['username']}") == "3"

    @pytest.mark.parametrize("password_kind", ["correct", "wrong"])
    async def test_locked_is_429_with_real_ttl(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, password_kind,
    ):
        """A lockout Redis CONFIRMED ⇒ 429, ``Retry-After`` = the key's real TTL."""
        user = regular_user_in_db
        await _lock(test_redis_client, user["username"])
        await _preset_attempts(test_redis_client, user["username"])
        before = await _auth_state(test_redis_client, user)

        res = await _post_login(client, user["username"], _password_for(user, password_kind))

        _assert_locked_429(res)
        assert LOCKOUT_KEY_TTL - 60 < int(res.headers["retry-after"]) <= LOCKOUT_KEY_TTL, res.headers
        after = await _auth_state(test_redis_client, user)
        assert after == before, (before, after)


@pytest.mark.asyncio
@pytest.mark.security
class TestLoginLockoutStateUnavailable:
    """Redis did NOT answer the lockout EXISTS ⇒ 503, for any password, nothing created."""

    @pytest.mark.parametrize("password_kind", ["correct", "wrong"])
    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    async def test_exists_unreadable_is_503(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, exc_type, password_kind,
    ):
        """Breaker still CLOSED, only the lockout EXISTS fails.

        Before: 429 "account temporarily locked" for both passwords. A wrong
        password must not be recorded either: the request never reaches the
        credential check, so the preset counter stays exactly as it was.
        """
        user = regular_user_in_db
        await _preset_attempts(test_redis_client, user["username"])
        before = await _auth_state(test_redis_client, user)

        calls = []
        with _redis_command_failing_on("exists", "account_lockout:", exc_type, calls):
            res = await _post_login(client, user["username"], _password_for(user, password_kind))

        assert calls, "the lockout EXISTS never reached the Redis client"
        assert redis_breaker_reset.current_state is CircuitBreakerState.CLOSED
        _assert_auth_state_unavailable(res)
        after = await _auth_state(test_redis_client, user)
        assert after == before, (before, after)
        assert after["login_attempts"] == PRESET_ATTEMPTS

    async def test_exists_unreadable_on_a_locked_account_is_503(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """Even when the account IS locked in Redis: unverifiable ⇒ 503 (never 200)."""
        user = regular_user_in_db
        await _lock(test_redis_client, user["username"])
        before = await _auth_state(test_redis_client, user)

        calls = []
        with _redis_command_failing_on("exists", "account_lockout:", RedisConnectionError, calls):
            res = await _post_login(client, user["username"], user["password"])

        assert calls
        _assert_auth_state_unavailable(res)
        assert await _auth_state(test_redis_client, user) == before

    async def test_mfa_user_gets_no_mfa_token(
        self, client, mfa_login_user, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """MFA user, correct password: 503 comes BEFORE the mfa_token is minted."""
        user = mfa_login_user
        before = await _auth_state(test_redis_client, user)

        calls = []
        with _redis_command_failing_on("exists", "account_lockout:", RedisConnectionError, calls):
            res = await _post_login(client, user["username"], user["password"])

        assert calls
        _assert_auth_state_unavailable(res)
        assert await _auth_state(test_redis_client, user) == before

    async def test_mfa_user_control_gets_mfa_token(
        self, client, mfa_login_user, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """Control for the case above: with Redis answering, the same request mints one."""
        user = mfa_login_user

        res = await _post_login(client, user["username"], user["password"])

        assert res.status_code == 200, res.text
        assert res.json().get("mfa_required") is True
        assert res.json().get("mfa_token")

    @pytest.mark.parametrize("password_kind", ["correct", "wrong"])
    async def test_breaker_open_is_503(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, password_kind,
    ):
        """Breaker OPEN ⇒ the same 503 as a CLOSED-breaker outage: one outage, one answer."""
        user = regular_user_in_db
        await _preset_attempts(test_redis_client, user["username"])
        before = await _auth_state(test_redis_client, user)
        redis_breaker_reset.open()

        res = await _post_login(client, user["username"], _password_for(user, password_kind))

        assert redis_breaker_reset.current_state is CircuitBreakerState.OPEN
        _assert_auth_state_unavailable(res)
        assert await _auth_state(test_redis_client, user) == before

    async def test_redis_down_is_never_429(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """Control: every Redis command fails, account NOT locked, correct password.

        The one status this must never be is 429 — 429 is reserved for a
        lockout Redis confirmed.
        """
        user = regular_user_in_db
        before = await _auth_state(test_redis_client, user)

        with _redis_down() as calls:
            res = await _post_login(client, user["username"], user["password"])

        assert calls, "state 'down' was never exercised: no Redis call was made"
        assert res.status_code != 429, res.text
        _assert_auth_state_unavailable(res)
        assert await _auth_state(test_redis_client, user) == before

    async def test_outage_is_logged_as_outage_without_traceback(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """Control for the next test: a Redis outage has ITS event, no traceback, no key."""
        user = regular_user_in_db

        calls = []
        with _redis_command_failing_on("exists", "account_lockout:", RedisConnectionError, calls), \
                _lockout_log() as recorder:
            res = await _post_login(client, user["username"], user["password"])

        assert calls
        _assert_auth_state_unavailable(res)
        level, fields = _only_event(recorder, _EVENT_OUTAGE)
        assert level == "error"
        assert fields["step"] == "exists"
        assert not fields.get("exc_info"), fields
        assert _EVENT_UNEXPECTED not in recorder.by_event(), recorder.events
        # The real key (the label "auth.account_lockout" is fine: it names no account).
        assert f"account_lockout:{user['username']}" not in repr(recorder.events), recorder.events

    @pytest.mark.parametrize("password_kind", ["correct", "wrong"])
    @pytest.mark.parametrize(
        "exc_type", [RuntimeError, RedisResponseError], ids=["bug", "unexpected-reply"]
    )
    async def test_unexpected_error_is_503_with_its_own_log(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, exc_type, password_kind,
    ):
        """NOT an outage (a bug, an unexpected reply) ⇒ still the same 503, but
        logged as its OWN event WITH the traceback, never filed as "Redis down".
        """
        user = regular_user_in_db
        await _preset_attempts(test_redis_client, user["username"])
        before = await _auth_state(test_redis_client, user)

        calls = []
        with _redis_command_failing_on("exists", "account_lockout:", exc_type, calls), \
                _lockout_log() as recorder:
            res = await _post_login(client, user["username"], _password_for(user, password_kind))

        assert calls, "the lockout EXISTS never reached the Redis client"
        _assert_auth_state_unavailable(res)
        assert await _auth_state(test_redis_client, user) == before
        level, fields = _only_event(recorder, _EVENT_UNEXPECTED)
        assert level == "error"
        assert fields.get("exc_info") is True, fields
        assert fields["step"] == "exists"
        assert fields["error_type"] == exc_type.__name__
        assert _EVENT_OUTAGE not in recorder.by_event(), recorder.events


@pytest.mark.asyncio
@pytest.mark.security
class TestLoginLockoutTtlUnverifiable:
    """EXISTS answered "locked", but no usable TTL came back ⇒ 503, never 429, never 200.

    Before (9028b26b): TTL unreadable ⇒ 429 with the full lockout duration as
    Retry-After (a duration nobody read); TTL -1 ⇒ "not locked" ⇒ 200 and
    tokens for an account Redis holds a lock for.
    """

    @pytest.mark.parametrize("password_kind", ["correct", "wrong"])
    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    async def test_ttl_unreadable_is_503(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, exc_type, password_kind,
    ):
        user = regular_user_in_db
        await _lock(test_redis_client, user["username"])
        await _preset_attempts(test_redis_client, user["username"])
        before = await _auth_state(test_redis_client, user)

        calls = []
        with _redis_command_failing_on("ttl", "account_lockout:", exc_type, calls), \
                _lockout_log() as recorder:
            res = await _post_login(client, user["username"], _password_for(user, password_kind))

        assert calls, "the lockout TTL never reached the Redis client"
        assert redis_breaker_reset.current_state is CircuitBreakerState.CLOSED
        _assert_auth_state_unavailable(res)
        assert await _auth_state(test_redis_client, user) == before
        level, fields = _only_event(recorder, _EVENT_OUTAGE)
        assert fields["step"] == "ttl"

    @pytest.mark.parametrize("password_kind", ["correct", "wrong"])
    async def test_key_without_expiry_is_503_and_alerts_without_the_key(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, password_kind,
    ):
        """TTL -1: a lock that never ends and that this service did not write.

        Refused (503) and alerted. The log names the account (``username``,
        like every event of the module), never the Redis key.
        """
        user = regular_user_in_db
        await _lock_without_expiry(test_redis_client, user["username"])
        await _preset_attempts(test_redis_client, user["username"])
        before = await _auth_state(test_redis_client, user)

        with _lockout_log() as recorder:
            res = await _post_login(client, user["username"], _password_for(user, password_kind))

        _assert_auth_state_unavailable(res)
        assert await _auth_state(test_redis_client, user) == before
        level, fields = _only_event(recorder, _EVENT_NO_EXPIRY)
        assert level == "error"
        assert fields == {"username": user["username"], "ttl": -1}, fields
        # The real key (the label "auth.account_lockout" is fine: it names no account).
        assert f"account_lockout:{user['username']}" not in repr(recorder.events), recorder.events


@pytest.mark.asyncio
@pytest.mark.security
class TestLoginLockoutExpiredBetweenReads:
    """EXISTS=1, then TTL=-2: Redis ANSWERED that the lockout is gone ⇒ not locked.

    OWNER-CONFIRMATION POINT: -2 is an answer ("no such key"), not an outage,
    so the login goes on like any unlocked one: correct 200, wrong 401 and
    counted. A 503 here would refuse a user whose lockout has just ended.
    """

    async def test_correct_password_logs_in(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        user = regular_user_in_db
        await _lock(test_redis_client, user["username"])

        calls = []
        with _lockout_expires_before_ttl_read(calls):
            res = await _post_login(client, user["username"], user["password"])

        assert calls == [(f"account_lockout:{user['username']}", -2)], calls
        assert res.status_code == 200, res.text
        assert "access_token" in res.cookies and "refresh_token" in res.cookies
        state = await _auth_state(test_redis_client, user)
        assert state["live_db_sessions"] == 1
        assert len(state["session_keys"]) == 1
        assert state["account_lockout"] is None

    async def test_wrong_password_is_401_and_counted(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        user = regular_user_in_db
        await _lock(test_redis_client, user["username"])
        await _preset_attempts(test_redis_client, user["username"])

        calls = []
        with _lockout_expires_before_ttl_read(calls):
            res = await _post_login(client, user["username"], WRONG_PASSWORD)

        assert calls == [(f"account_lockout:{user['username']}", -2)], calls
        assert res.status_code == 401, res.text
        _assert_no_tokens(res)
        state = await _auth_state(test_redis_client, user)
        assert state["login_attempts"] == str(int(PRESET_ATTEMPTS) + 1)
        assert state["live_db_sessions"] == 0
        assert state["session_keys"] == []
        assert state["account_lockout"] is None


@pytest.mark.asyncio
@pytest.mark.security
class TestAuthStateUnavailableSingleSource:
    """``AuthStateUnavailable`` is the ONE source of the 503's code, text and Retry-After."""

    async def test_contract_values(self):
        assert AuthStateUnavailable.status_code == 503
        assert AuthStateUnavailable.error_code == AUTH_STATE_ERROR_CODE
        assert str(AuthStateUnavailable.retry_after_seconds) == AUTH_STATE_RETRY_AFTER
        assert AuthStateUnavailable().headers == {"Retry-After": AUTH_STATE_RETRY_AFTER}
        assert issubclass(AccountLockoutStateUnavailable, AuthStateUnavailable)
        exc = AccountLockoutStateUnavailable()
        assert (exc.status_code, exc.error_code, exc.detail, exc.headers) == (
            503,
            AUTH_STATE_ERROR_CODE,
            AuthStateUnavailable.detail,
            {"Retry-After": AUTH_STATE_RETRY_AFTER},
        )

    async def test_endpoint_takes_everything_from_the_class(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, monkeypatch,
    ):
        """Change the class and the endpoint's 503 must follow.

        A router, a handler or a subclass that re-declares the code, the text or
        the header value answers with the SAME values as the class today, so
        only a changed class tells the copy apart from the source.
        """
        monkeypatch.setattr(AuthStateUnavailable, "error_code", "AUTH_STATE_SOURCE_PROBE")
        monkeypatch.setattr(AuthStateUnavailable, "detail", "single-source probe")
        monkeypatch.setattr(AuthStateUnavailable, "retry_after_seconds", 137)
        user = regular_user_in_db
        redis_breaker_reset.open()

        res = await _post_login(client, user["username"], user["password"])

        assert res.status_code == 503, res.text
        assert res.json() == {
            "detail": "single-source probe",
            "error_code": "AUTH_STATE_SOURCE_PROBE",
        }, res.text
        assert res.headers.get("retry-after") == "137", res.headers
        _assert_no_tokens(res)


@pytest.mark.asyncio
@pytest.mark.security
class TestLoginAttemptCounterUnreadable:
    """P5 on /auth/login: an unreadable counter is never written back as "1"."""

    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    async def test_counter_unreadable_is_not_reset(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client,
        redis_breaker_reset, exc_type,
    ):
        """Only the counter GET fails ⇒ 401 (the password WAS wrong), count still 3.

        Before: ``safe_redis_get`` answered ``None`` ⇒ ``0 + 1`` ⇒ ``SET "1"``.
        """
        user = regular_user_in_db
        attempts_key = f"login_attempts:{user['username']}"
        await test_redis_client.set(attempts_key, "3", ex=1800)

        calls = []
        with _redis_command_failing_on("get", "login_attempts:", exc_type, calls):
            res = await _post_login(client, user["username"], WRONG_PASSWORD)

        assert calls, "the attempt-counter GET never reached the Redis client"
        assert res.status_code == 401, res.text
        _assert_no_tokens(res)
        assert await test_redis_client.get(attempts_key) == "3"
        assert await test_redis_client.exists(f"account_lockout:{user['username']}") == 0

    async def test_unreadable_counter_does_not_buy_extra_attempts(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """Endpoint effect: one short of the threshold + one unreadable read, then
        one more wrong password (Redis healthy) still locks; the correct password
        afterwards gets 429 and no tokens.
        """
        max_attempts = settings.ACCOUNT_LOCKOUT_MAX_ATTEMPTS
        assert max_attempts >= 3, "the scenario needs room below the threshold"
        user = regular_user_in_db
        attempts_key = f"login_attempts:{user['username']}"
        await test_redis_client.set(attempts_key, str(max_attempts - 1), ex=1800)

        calls = []
        with _redis_command_failing_on("get", "login_attempts:", RedisConnectionError, calls):
            first = await _post_login(client, user["username"], WRONG_PASSWORD)
        assert calls, "the attempt-counter GET never reached the Redis client"
        assert first.status_code == 401, first.text

        second = await _post_login(client, user["username"], WRONG_PASSWORD)
        assert second.status_code == 401, second.text

        res = await _post_login(client, user["username"], user["password"])

        _assert_locked_429(res)
        assert await _live_session_count(user["id"]) == 0


# =============================================================================
# 7. /auth/verify-mfa — LAYER-3 ATTEMPT COUNTER
# =============================================================================
#
# /verify-mfa feeds a wrong code into ``record_failed_attempt`` (Layer 3, the
# same ``login_attempts:{username}`` counter as /login). It does not call
# ``check_lockout``: an unreadable Redis there is refused by the Layer-2
# reservation (503, existing behaviour, not changed here).

@pytest.mark.asyncio
@pytest.mark.security
class TestVerifyMfaAttemptCounter:

    async def test_wrong_code_is_counted_control(
        self, client, mfa_login_user, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        """Control: Redis healthy, wrong code ⇒ 401 and the Layer-3 counter goes 3 → 4."""
        user = mfa_login_user
        attempts_key = f"login_attempts:{user['username']}"
        await test_redis_client.set(attempts_key, "3", ex=1800)
        mfa_token = mfa_service.create_mfa_token(username=user["username"], user_id=user["id"])

        res = await _post_verify_mfa(client, mfa_token, _wrong_totp(user["secret"]))

        assert res.status_code == 401, res.text
        _assert_no_tokens(res)
        assert await test_redis_client.get(attempts_key) == "4"

    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    async def test_counter_unreadable_is_not_reset(
        self, client, mfa_login_user, clear_redis_keys, test_redis_client,
        redis_breaker_reset, exc_type,
    ):
        """Wrong code + unreadable Layer-3 counter ⇒ 401, count still 3, nothing created."""
        user = mfa_login_user
        attempts_key = f"login_attempts:{user['username']}"
        await test_redis_client.set(attempts_key, "3", ex=1800)
        mfa_token = mfa_service.create_mfa_token(username=user["username"], user_id=user["id"])

        calls = []
        with _redis_command_failing_on("get", "login_attempts:", exc_type, calls):
            res = await _post_verify_mfa(client, mfa_token, _wrong_totp(user["secret"]))

        assert calls, "the attempt-counter GET never reached the Redis client"
        assert res.status_code == 401, res.text
        _assert_no_tokens(res)
        state = await _auth_state(test_redis_client, user)
        assert state["login_attempts"] == "3"
        assert state["account_lockout"] is None
        assert state["live_db_sessions"] == 0
        assert state["session_keys"] == []


# =============================================================================
# 8. STRICT REDIS READS
# =============================================================================

class _LogRecorder:
    """Stands in for a module's structlog ``log``: records every call, formats nothing."""

    def __init__(self):
        self.events = []

    def _level(level):  # noqa: N805 — class-body factory, deleted below
        def _record(self, event, *args, **kwargs):
            self.events.append((level, event, args, kwargs))
        return _record

    error = _level("error")
    warning = _level("warning")
    info = _level("info")
    debug = _level("debug")
    critical = _level("critical")
    exception = _level("exception")
    del _level

    def by_event(self) -> dict:
        """``{event: [(level, kwargs), ...]}``."""
        grouped = {}
        for level, event, _args, kwargs in self.events:
            grouped.setdefault(event, []).append((level, kwargs))
        return grouped


@pytest.mark.asyncio
@pytest.mark.security
class TestStrictRedisReads:
    """``redis_*_or_raise``: a value ONLY when Redis answered, otherwise one exception."""

    _KEY = "login_attempts:strict-read-probe-user"

    async def test_answered_absent_is_a_value_not_an_error(
        self, clear_redis_keys, redis_breaker_reset
    ):
        assert await db_module.redis_get_or_raise(self._KEY, "test.label") is None
        assert await db_module.redis_exists_or_raise(self._KEY, "test.label") is False
        assert await db_module.redis_ttl_or_raise(self._KEY, "test.label") == -2

    async def test_answered_present_is_returned(
        self, clear_redis_keys, test_redis_client, redis_breaker_reset
    ):
        await test_redis_client.set(self._KEY, "42", ex=300)
        assert await db_module.redis_get_or_raise(self._KEY, "test.label") == "42"
        assert await db_module.redis_exists_or_raise(self._KEY, "test.label") is True
        assert 0 < await db_module.redis_ttl_or_raise(self._KEY, "test.label") <= 300

    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    @pytest.mark.parametrize("command", ["get", "exists", "ttl"])
    async def test_client_error_raises_unavailable(
        self, clear_redis_keys, redis_breaker_reset, command, exc_type
    ):
        """Outage ⇒ ``RedisUnavailableError``, counted by the breaker, key never echoed."""
        helper = getattr(db_module, f"redis_{command}_or_raise")
        calls = []
        recorder = _LogRecorder()
        with _redis_command_failing_on(command, "login_attempts:", exc_type, calls), \
                patch.object(db_module, "log", recorder):
            with pytest.raises(db_module.RedisUnavailableError) as excinfo:
                await helper(self._KEY, "test.label")

        assert calls
        assert redis_breaker_reset.current_state is CircuitBreakerState.CLOSED
        assert redis_breaker_reset.fail_counter == 1, "the read did not go through the breaker"
        message = str(excinfo.value)
        assert "test.label" in message
        assert self._KEY not in message and "simulated" not in message
        assert recorder.events, "the outage was not logged"
        logged = repr(recorder.events)
        assert self._KEY not in logged and "simulated" not in logged, logged

    @pytest.mark.parametrize("command", ["get", "exists", "ttl"])
    async def test_breaker_open_raises_unavailable(
        self, clear_redis_keys, redis_breaker_reset, command
    ):
        helper = getattr(db_module, f"redis_{command}_or_raise")
        redis_breaker_reset.open()
        with pytest.raises(db_module.RedisUnavailableError):
            await helper(self._KEY, "test.label")




# =============================================================================
# 9. REFRESH — "REDIS DID NOT ANSWER" IS A 503, NEVER A VERDICT ON THE TOKEN
# =============================================================================
#
# Three Redis reads decide whether ``POST /auth/refresh`` may rotate a token:
# ``blacklist:{jti}`` (EXISTS, STEP 2, before the DB is even read),
# ``user_blacklist:{user_id}`` (EXISTS) and ``session:{jti}`` (GET). All three
# go through the strict helpers of ``app/database.py``. When Redis does not answer
# (ConnectionError / TimeoutError while the breaker is CLOSED, or an OPEN
# breaker) the endpoint raises ``RefreshStateUnavailable`` BEFORE any write,
# and the global handler answers the SAME 503 as ``/login``'s (section 6):
# code, text and ``Retry-After`` all come from ``AuthStateUnavailable``:
#   * nothing is counted in ``refresh_fail:{username}`` and
#     ``invalidate_all_sessions`` never runs, however often it repeats;
#   * the jti is not blacklisted, ``session:{jti}`` is untouched, the DB session
#     row is untouched and no cookie is set;
#   * the SAME token rotates once Redis answers again.
# The frontend classifies exactly this pair as ``safe-retryable`` (the only 5xx
# it retries) BECAUSE of "before any write", so that property is pinned here
# from the outside: a Redis write recorder, the auth keys' values and TTLs, the
# DB rows and ``Set-Cookie``. The 503s raised AFTER the rotation started (Redis
# rotate / DB commit failure) must keep a DIFFERENT code, or the frontend would
# retry a token the server may already have rotated.
#
# An ANSWERED blacklist / miss / mismatch keeps the old contract: 401, counted,
# and at ``REFRESH_MAX_FAILURES`` ``invalidate_all_sessions`` runs once.
#
# Uses the module-level helpers of this file (breaker reset, Redis failure
# injection, the 503 assertion) — one copy each.

import jwt  # noqa: E402

from app.utils.exceptions import RefreshStateUnavailable  # noqa: E402


@pytest.mark.asyncio
@pytest.mark.security
class TestRefreshRedisStateUnavailable:
    """``POST /auth/refresh`` must tell "Redis did not answer" from "token is bad"."""

    REFRESH_URL = "/api/auth/refresh"
    LOGIN_URL = "/api/auth/login"
    LOGOUT_URL = "/api/auth/logout"
    # The wire contract with the frontend (``safe-retry.ts`` retries exactly
    # this pair) is pinned by the module literals ``AUTH_STATE_ERROR_CODE`` /
    # ``AUTH_STATE_RETRY_AFTER``, shared with the ``/login`` tests.
    AUTH_KEY_PATTERNS = ("session:*", "blacklist:*", "refresh_fail:*", "user_blacklist:*")
    # Every client command that can change a key, plus ``pipeline`` (the rotation
    # and its compensation are both pipelines).
    WRITE_COMMANDS = ("set", "setex", "delete", "expire", "incr", "getdel", "eval")
    ALL_COMMANDS = (
        "get", "exists", "set", "setex", "delete", "ttl", "incr", "expire", "getdel", "eval",
    )

    # --- fixtures & helpers (local to this class) ---------------------------------

    @pytest.fixture
    def breaker(self, redis_breaker_reset):
        """The module's ``redis_breaker_reset``: clean before AND after, even on red."""
        return redis_breaker_reset

    @pytest_asyncio.fixture
    async def logged_in(self, client, regular_user_in_db, clear_redis_keys, breaker):
        """Log in with Redis healthy; return the user plus both tokens."""
        user = regular_user_in_db
        client.cookies.clear()
        res = await client.post(
            self.LOGIN_URL, data={"username": user["username"], "password": user["password"]}
        )
        client.cookies.clear()
        assert res.status_code == 200, res.text
        access, refresh = res.cookies.get("access_token"), res.cookies.get("refresh_token")
        assert access and refresh, "login did not set both auth cookies"
        return {"user": user, "access": access, "refresh": refresh, "jti": self._jti(refresh)}

    async def _refresh(self, client, refresh: str):
        client.cookies.clear()
        res = await client.post(self.REFRESH_URL, headers={"Cookie": f"refresh_token={refresh}"})
        client.cookies.clear()
        return res

    @staticmethod
    def _jti(refresh: str) -> str:
        payload = jwt.decode(refresh, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        assert payload.get("type") == "refresh"
        return payload["jti"]

    @staticmethod
    async def _session_rows(user_id: int) -> list:
        """Every DB session row of the user, as comparable tuples."""
        async with db_module.AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.UserSession)
                .where(models.UserSession.user_id == user_id)
                .order_by(models.UserSession.id)
            )
            return [
                (row.id, row.refresh_jti, row.revoked_at, row.last_activity_at)
                for row in result.scalars()
            ]

    async def _auth_keys(self, redis) -> dict:
        """``{key: (value, ttl)}`` for every auth key, read through the test client."""
        snapshot = {}
        for pattern in self.AUTH_KEY_PATTERNS:
            async for key in redis.scan_iter(match=pattern):
                snapshot[key] = (await redis.get(key), await redis.ttl(key))
        return snapshot

    @staticmethod
    def _assert_auth_keys_unchanged(before: dict, after: dict) -> None:
        assert sorted(after) == sorted(before), (before, after)
        for key, (value, ttl) in before.items():
            after_value, after_ttl = after[key]
            assert after_value == value, (key, value, after_value)
            assert ttl - 5 <= after_ttl <= ttl, (key, ttl, after_ttl)

    @contextmanager
    def _redis_all_down(self, exc_type=RedisConnectionError):
        calls = []

        async def _down(*args, **kwargs):
            calls.append(args[0] if args else None)
            raise exc_type("simulated Redis outage")

        with ExitStack() as stack:
            for name in self.ALL_COMMANDS:
                stack.enter_context(patch.object(db_module.redis_client, name, _down))
            yield calls

    @contextmanager
    def _record_redis_writes(self):
        """Record every write command and every pipeline the app issues."""
        client = db_module.redis_client
        writes = []
        with ExitStack() as stack:
            for name in self.WRITE_COMMANDS:
                original = getattr(client, name)

                async def _recording(*args, _cmd=name, _orig=original, **kwargs):
                    writes.append((_cmd, args[0] if args else None))
                    return await _orig(*args, **kwargs)

                stack.enter_context(patch.object(client, name, _recording))

            original_pipeline = client.pipeline

            def _pipeline(*args, **kwargs):
                writes.append(("pipeline", None))
                return original_pipeline(*args, **kwargs)

            stack.enter_context(patch.object(client, "pipeline", _pipeline))
            yield writes

    @staticmethod
    @contextmanager
    def _spy_revocations():
        """Record every ``invalidate_all_sessions`` call, then run the real one."""
        original = user_service.invalidate_all_sessions
        calls = []

        async def _spy(*args, **kwargs):
            calls.append(args)
            return await original(*args, **kwargs)

        with patch.object(user_service, "invalidate_all_sessions", _spy):
            yield calls

    @staticmethod
    def _assert_state_unavailable(res) -> None:
        """Exactly ``/login``'s 503 (section 6), and not a single cookie set."""
        _assert_auth_state_unavailable(res)
        assert res.headers.get_list("set-cookie") == [], res.headers.get_list("set-cookie")

    async def _assert_rotates(self, client, refresh: str, user_id: int) -> None:
        """The SAME token rotates: 200, a new refresh cookie, the DB row follows it."""
        res = await self._refresh(client, refresh)
        assert res.status_code == 200, res.text
        new_refresh = res.cookies.get("refresh_token")
        assert new_refresh and new_refresh != refresh
        new_jti = self._jti(new_refresh)
        assert [row[1] for row in await self._session_rows(user_id)] == [new_jti]

    # --- controls: Redis ANSWERED ------------------------------------------------

    async def test_valid_token_rotates(self, client, logged_in, test_redis_client):
        """Redis healthy + valid token ⇒ 200 rotation; the old jti is retired."""
        jti = logged_in["jti"]

        await self._assert_rotates(client, logged_in["refresh"], logged_in["user"]["id"])

        assert await test_redis_client.exists(f"session:{jti}") == 0
        assert await test_redis_client.get(f"blacklist:{jti}") == "rotated"
        username = logged_in["user"]["username"]
        assert await test_redis_client.exists(f"refresh_fail:{username}") == 0

    async def test_answered_user_blacklist_is_401_and_counted(
        self, client, logged_in, test_redis_client
    ):
        """Redis ANSWERED "user blacklisted" ⇒ 401 INVALID_TOKEN + counted, as before."""
        user = logged_in["user"]
        await test_redis_client.set(
            f"user_blacklist:{user['id']}", "sessions_invalidated", ex=3600
        )

        res = await self._refresh(client, logged_in["refresh"])

        assert res.status_code == 401, res.text
        assert res.json().get("error_code") == "INVALID_TOKEN", res.text
        assert "refresh_token" not in res.cookies
        assert await test_redis_client.get(f"refresh_fail:{user['username']}") == "1"

    @pytest.mark.parametrize("answer", ["miss", "mismatch"])
    async def test_answered_session_miss_or_mismatch_is_reuse_and_counted(
        self, client, logged_in, test_redis_client, answer
    ):
        """Redis ANSWERED "no such session" / "another user's" ⇒ 401 + reuse + counted."""
        user, jti = logged_in["user"], logged_in["jti"]
        if answer == "miss":
            assert await test_redis_client.delete(f"session:{jti}") == 1
        else:
            await test_redis_client.set(f"session:{jti}", str(user["id"] + 1000), ex=3600)

        res = await self._refresh(client, logged_in["refresh"])

        assert res.status_code == 401, res.text
        assert res.json().get("error_code") == "INVALID_TOKEN", res.text
        assert "refresh_token" not in res.cookies
        assert await test_redis_client.get(f"blacklist:{jti}") == "reuse_attempt"
        assert await test_redis_client.get(f"refresh_fail:{user['username']}") == "1"

    async def test_answered_misses_revoke_exactly_once_at_threshold(
        self, client, logged_in, test_redis_client
    ):
        """``REFRESH_MAX_FAILURES`` ANSWERED misses ⇒ ``invalidate_all_sessions`` once.

        Also proves the spy used by the outage tests below CAN see the call.
        """
        assert await test_redis_client.delete(f"session:{logged_in['jti']}") == 1

        with self._spy_revocations() as revoked:
            statuses = [
                (await self._refresh(client, logged_in["refresh"])).status_code
                for _ in range(settings.REFRESH_MAX_FAILURES)
            ]

        assert statuses == [401] * settings.REFRESH_MAX_FAILURES, statuses
        assert len(revoked) == 1, revoked

    # --- Redis did NOT answer ------------------------------------------------------

    async def _assert_outage_is_state_unavailable(
        self, client, logged_in, test_redis_client, failing
    ) -> None:
        """Run ``REFRESH_MAX_FAILURES + 1`` refreshes under ``failing`` and pin the contract."""
        user, refresh, jti = logged_in["user"], logged_in["refresh"], logged_in["jti"]
        attempts = settings.REFRESH_MAX_FAILURES + 1
        rows_before = await self._session_rows(user["id"])
        keys_before = await self._auth_keys(test_redis_client)
        assert rows_before and keys_before.get(f"session:{jti}"), "precondition: live session"

        failed = []
        with self._spy_revocations() as revoked, self._record_redis_writes() as writes:
            with failing(failed):
                responses = [await self._refresh(client, refresh) for _ in range(attempts)]

        # Headline invariant first, so a red run names the real damage.
        statuses = [res.status_code for res in responses]
        assert revoked == [], (
            f"invalidate_all_sessions ran {len(revoked)}x; statuses={statuses}"
        )
        for res in responses:
            self._assert_state_unavailable(res)
        assert len(failed) == attempts, failed  # every refresh met the outage
        # Nothing written: no counter, no reuse blacklist, no rotation pipeline.
        assert writes == [], writes
        self._assert_auth_keys_unchanged(keys_before, await self._auth_keys(test_redis_client))
        assert await self._session_rows(user["id"]) == rows_before

    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    async def test_session_unreadable_is_503_never_scored_then_rotates(
        self, client, logged_in, test_redis_client, breaker, exc_type
    ):
        """``session:{jti}`` GET gets no answer, more times than the abuse threshold."""
        await self._assert_outage_is_state_unavailable(
            client, logged_in, test_redis_client,
            lambda failed: _redis_command_failing_on("get", "session:", exc_type, failed),
        )
        # Each failing read sits between answered ones, and an answer resets a
        # CLOSED breaker: this partial outage never opens it, so every refresh
        # above met the ConnectionError/TimeoutError path, not the OPEN one.
        assert breaker.current_state is CircuitBreakerState.CLOSED

        await self._assert_rotates(client, logged_in["refresh"], logged_in["user"]["id"])

    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    async def test_user_blacklist_unreadable_is_503_never_scored_then_rotates(
        self, client, logged_in, test_redis_client, breaker, exc_type
    ):
        """``user_blacklist:{id}`` EXISTS gets no answer, more times than the threshold."""
        await self._assert_outage_is_state_unavailable(
            client, logged_in, test_redis_client,
            lambda failed: _redis_command_failing_on("exists", "user_blacklist:", exc_type, failed),
        )
        assert breaker.current_state is CircuitBreakerState.CLOSED

        await self._assert_rotates(client, logged_in["refresh"], logged_in["user"]["id"])

    STEP3_REFUSED_EVENT = "Refresh refused: user blacklist check failed"

    @pytest.mark.parametrize(
        "exc_type", [RedisResponseError, TypeError], ids=["response_error", "type_error"]
    )
    async def test_user_blacklist_other_error_is_500_fail_closed(
        self, client, logged_in, test_redis_client, breaker, exc_type
    ):
        """STEP 3 like STEP 2: not "Redis did not answer" ⇒ a plain 500, never counted.

        Before, ``except Exception`` answered it with the counted 401: an ACL
        ``NOPERM`` on ``user_blacklist:`` scored every refresh as token abuse
        and, at the threshold, ran ``invalidate_all_sessions``.
        """
        user = logged_in["user"]
        attempts = settings.REFRESH_MAX_FAILURES + 1
        rows_before = await self._session_rows(user["id"])
        keys_before = await self._auth_keys(test_redis_client)

        failed = []
        with ExitStack() as stack:
            revoked = stack.enter_context(self._spy_revocations())
            writes = stack.enter_context(self._record_redis_writes())
            stack.enter_context(
                _redis_command_failing_on("exists", "user_blacklist:", exc_type, failed)
            )
            responses = [
                await self._refresh(client, logged_in["refresh"]) for _ in range(attempts)
            ]

        statuses = [res.status_code for res in responses]
        assert revoked == [], f"invalidate_all_sessions ran; statuses={statuses}"
        for res in responses:
            self._assert_fail_closed_500(res)
        assert len(failed) == attempts, failed
        assert writes == [], writes
        assert await test_redis_client.get(f"refresh_fail:{user['username']}") is None
        self._assert_auth_keys_unchanged(keys_before, await self._auth_keys(test_redis_client))
        assert await self._session_rows(user["id"]) == rows_before
        assert breaker.current_state is CircuitBreakerState.CLOSED

        await self._assert_rotates(client, logged_in["refresh"], user["id"])

    @pytest.mark.parametrize("fault", ["response_error", "type_error"])
    async def test_step3_error_log_carries_no_jti_key_or_message(
        self, client, logged_in, test_redis_client, breaker, caplog, fault
    ):
        """STEP 3's refusal logs event/action, user_id and the exception CLASS.

        Never the JTI, the Redis key or the exception message.
        The injected message is a canary (the old arm logged ``error=str(e)``);
        the key and the jti must not ride on the refusal event either.
        Asserting the event first proves the capture sees these logs at all.
        """
        user = logged_in["user"]
        key = f"user_blacklist:{user['id']}"
        message = f"CANARYMSG{uuid.uuid4().hex}"
        exc_type = {"response_error": RedisResponseError, "type_error": TypeError}[fault]
        original = db_module.redis_client.exists
        hits = []

        async def _exists(*args, **kwargs):
            if args and args[0] == key:
                hits.append(key)
                raise exc_type(message)
            return await original(*args, **kwargs)

        caplog.set_level(logging.DEBUG)
        with patch.object(db_module.redis_client, "exists", _exists):
            res = await self._refresh(client, logged_in["refresh"])

        self._assert_fail_closed_500(res)
        assert hits == [key], hits
        lines = [record.getMessage() for record in caplog.records]
        refused = [line for line in lines if self.STEP3_REFUSED_EVENT in line]
        assert refused, lines
        assert all(exc_type.__name__ in line for line in refused), refused
        for line in refused:
            assert key not in line, line
            assert logged_in["jti"] not in line, line
        for text in lines + [caplog.text]:
            assert message[:9] not in text, text

    async def test_blacklisted_user_unreadable_is_503_then_401_once_answered(
        self, client, logged_in, test_redis_client
    ):
        """User REALLY blacklisted but EXISTS unanswered ⇒ 503 (never 200); answered ⇒ 401."""
        user = logged_in["user"]
        await test_redis_client.set(
            f"user_blacklist:{user['id']}", "sessions_invalidated", ex=3600
        )

        failed = []
        with _redis_command_failing_on("exists", "user_blacklist:", RedisConnectionError, failed):
            res = await self._refresh(client, logged_in["refresh"])

        assert failed, "the user-blacklist EXISTS never reached the Redis client"
        self._assert_state_unavailable(res)
        assert await test_redis_client.exists(f"refresh_fail:{user['username']}") == 0

        after = await self._refresh(client, logged_in["refresh"])
        assert after.status_code == 401, after.text
        assert await test_redis_client.get(f"refresh_fail:{user['username']}") == "1"

    async def test_breaker_open_is_503_never_scored_then_rotates(
        self, client, logged_in, test_redis_client, breaker
    ):
        """Breaker OPEN ⇒ 503 (was 401 ⇒ client logout); the same token rotates after."""
        user = logged_in["user"]
        rows_before = await self._session_rows(user["id"])
        keys_before = await self._auth_keys(test_redis_client)

        breaker.open()
        with self._spy_revocations() as revoked, self._record_redis_writes() as writes:
            responses = [
                await self._refresh(client, logged_in["refresh"])
                for _ in range(settings.REFRESH_MAX_FAILURES + 1)
            ]
        assert breaker.current_state is CircuitBreakerState.OPEN

        assert revoked == []
        for res in responses:
            self._assert_state_unavailable(res)
        assert writes == [], writes
        _reset_redis_breaker(breaker)
        self._assert_auth_keys_unchanged(keys_before, await self._auth_keys(test_redis_client))
        assert await self._session_rows(user["id"]) == rows_before

        await self._assert_rotates(client, logged_in["refresh"], user["id"])

    # --- STEP 2: the jti blacklist read, the FIRST of the three -----------------
    #
    # ``blacklist:{jti}`` is read before the DB is touched. Logout, session
    # revocation, re-login on the same device, the session cap and a detected
    # reuse all write it; when such a revocation could not delete
    # ``session:{jti}`` nor revoke the DB row, this key is the ONLY record that
    # the token is dead (``_seed_revoked_but_live``). The lenient read answered
    # an outage with "not blacklisted" and that dead token rotated. Now:
    #   * no answer (ConnectionError / TimeoutError / OPEN breaker) ⇒ the 503,
    #     decided AT STEP 2, before any write and before the DB is read;
    #   * any other error (a Redis ``ResponseError``, a bug) ⇒ a plain 500:
    #     never the retryable 503 pair, never a fall-through;
    #   * an ANSWERED "blacklisted" ⇒ 401, counted, as before;
    # and none of it logs the jti, the key or the exception message.

    STEP2_DEFERRED_EVENT = "Refresh deferred: jti blacklist unreadable"
    STEP2_REFUSED_EVENT = "Refresh refused: jti blacklist check failed"
    STEP2_BLACKLISTED_EVENT = "Refresh token is blacklisted"

    @staticmethod
    @contextmanager
    def _spy_user_lookups():
        """Record every ``get_user_for_refresh`` call: the first DB read after STEP 2."""
        original = user_service.get_user_for_refresh
        calls = []

        async def _spy(*args, **kwargs):
            calls.append(args)
            return await original(*args, **kwargs)

        with patch.object(user_service, "get_user_for_refresh", _spy):
            yield calls

    @staticmethod
    @contextmanager
    def _step2_exists_trips_breaker(breaker, seen: list):
        """STEP 2's EXISTS fails as the ``fail_max``-th consecutive failure.

        The counter is raised to ``fail_max - 1`` INSIDE the call, standing in
        for concurrent failures of other requests: the answered ``refresh_fail``
        GET just before STEP 2 resets a CLOSED breaker's counter, so setting it
        ahead of the request would not survive to STEP 2. Records the breaker
        (state, counter) at the moment STEP 2 fails.
        """
        original = db_module.redis_client.exists

        async def _exists(*args, **kwargs):
            key = args[0] if args else None
            if isinstance(key, str) and key.startswith("blacklist:"):
                storage = breaker._state_storage
                while breaker.fail_counter < breaker.fail_max - 1:
                    storage.increment_counter()
                seen.append((breaker.current_state, breaker.fail_counter))
                raise RedisConnectionError("simulated Redis outage")
            return await original(*args, **kwargs)

        with patch.object(db_module.redis_client, "exists", _exists):
            yield seen

    @staticmethod
    @contextmanager
    def _fail_exists_with(exact_key: str, exc: BaseException, hits: list):
        """EXISTS of exactly ``exact_key`` raises ``exc``; every other key is real."""
        original = db_module.redis_client.exists

        async def _exists(*args, **kwargs):
            if args and args[0] == exact_key:
                hits.append("exists:blacklist")
                raise exc
            return await original(*args, **kwargs)

        with patch.object(db_module.redis_client, "exists", _exists):
            yield hits

    async def _seed_revoked_but_live(self, test_redis_client, logged_in) -> None:
        """What a revocation leaves when its session DELETE and its DB write failed.

        ``blacklist:{jti}`` set, ``session:{jti}`` still there, DB row live:
        only STEP 2 can tell that the token is dead.
        """
        jti = logged_in["jti"]
        await test_redis_client.set(f"blacklist:{jti}", "revoked", ex=3600)
        assert await test_redis_client.exists(f"session:{jti}") == 1
        rows = await self._session_rows(logged_in["user"]["id"])
        assert [(row[1], row[2]) for row in rows] == [(jti, None)], rows

    @staticmethod
    def _assert_fail_closed_500(res) -> None:
        """A plain 500: NOT the retryable 503 pair, no Retry-After, no cookie, no token."""
        assert res.status_code == 500, res.text
        assert res.json() == {
            "detail": "An unexpected error occurred",
            "error_code": "HTTP_500",
        }, res.text
        assert "retry-after" not in res.headers, dict(res.headers)
        assert res.headers.get_list("set-cookie") == [], res.headers.get_list("set-cookie")
        _assert_no_tokens(res)

    @pytest.mark.parametrize("token", ["live", "revoked_session_left"])
    @pytest.mark.parametrize(
        "exc_type", [RedisConnectionError, RedisTimeoutError], ids=["connection", "timeout"]
    )
    async def test_jti_blacklist_unreadable_is_503_never_scored(
        self, client, logged_in, test_redis_client, breaker, exc_type, token
    ):
        """``blacklist:{jti}`` EXISTS gets no answer ⇒ the 503, never a rotation.

        ``revoked_session_left`` is the fail-open this pins: the lenient read
        fell through, STEP 4 found the session and the revoked token rotated
        into a usable pair. Once Redis answers, the SAME token is judged on the
        facts: a live one rotates, a revoked one is a counted 401.
        """
        user = logged_in["user"]
        if token == "revoked_session_left":
            await self._seed_revoked_but_live(test_redis_client, logged_in)

        with self._spy_user_lookups() as looked_up:
            await self._assert_outage_is_state_unavailable(
                client, logged_in, test_redis_client,
                lambda failed: _redis_command_failing_on("exists", "blacklist:", exc_type, failed),
            )
        assert looked_up == [], "STEP 2 must refuse before the DB is read"
        # Each failing read sits between answered ones and an answer resets a
        # CLOSED breaker: every refresh above met the ConnectionError /
        # TimeoutError path, never the OPEN one.
        assert breaker.current_state is CircuitBreakerState.CLOSED

        if token == "live":
            await self._assert_rotates(client, logged_in["refresh"], user["id"])
        else:
            after = await self._refresh(client, logged_in["refresh"])
            assert after.status_code == 401, after.text
            assert after.json().get("error_code") == "INVALID_TOKEN", after.text
            assert await test_redis_client.get(f"refresh_fail:{user['username']}") == "1"

    @pytest.mark.parametrize("how", ["forced_open", "tripped_by_step2"])
    async def test_jti_blacklist_breaker_open_is_503_decided_at_step2(
        self, client, logged_in, test_redis_client, breaker, how
    ):
        """OPEN breaker at STEP 2 ⇒ the 503, decided there, before the DB is read.

        * ``forced_open``: ``breaker.open()`` before the request, so the
          breaker is OPEN (counter 0) before and after. The lenient
          ``refresh_fail`` read ahead of STEP 2 swallows its
          ``CircuitBreakerError``; STEP 2 is the first read that must decide.
        * ``tripped_by_step2``: CLOSED with ``fail_max - 1`` failures when
          STEP 2's EXISTS fails; that failure opens it (CLOSED before, OPEN
          after) — the request that trips the breaker.

        The lenient read also ended in a 503 here, but only because STEP 3
        happened to be strict: the user row had already been read and locked.
        """
        user = logged_in["user"]
        await self._seed_revoked_but_live(test_redis_client, logged_in)
        rows_before = await self._session_rows(user["id"])
        keys_before = await self._auth_keys(test_redis_client)
        seen = []

        with ExitStack() as stack:
            if how == "forced_open":
                breaker.open()
                seen.append((breaker.current_state, breaker.fail_counter))
            else:
                assert breaker.current_state is CircuitBreakerState.CLOSED
                stack.enter_context(self._step2_exists_trips_breaker(breaker, seen))
            revoked = stack.enter_context(self._spy_revocations())
            writes = stack.enter_context(self._record_redis_writes())
            looked_up = stack.enter_context(self._spy_user_lookups())
            res = await self._refresh(client, logged_in["refresh"])
        state_after = breaker.current_state
        _reset_redis_breaker(breaker)

        if how == "forced_open":
            assert seen == [(CircuitBreakerState.OPEN, 0)], seen
        else:
            assert seen == [(CircuitBreakerState.CLOSED, breaker.fail_max - 1)], seen
        assert state_after is CircuitBreakerState.OPEN, state_after
        self._assert_state_unavailable(res)
        assert looked_up == [], "an OPEN breaker must be decided AT STEP 2"
        assert revoked == [] and writes == [], (revoked, writes)
        self._assert_auth_keys_unchanged(keys_before, await self._auth_keys(test_redis_client))
        assert await self._session_rows(user["id"]) == rows_before

    @pytest.mark.parametrize(
        "exc_type", [RedisResponseError, TypeError], ids=["response_error", "type_error"]
    )
    async def test_jti_blacklist_other_error_is_500_fail_closed(
        self, client, logged_in, test_redis_client, breaker, exc_type
    ):
        """Not "Redis did not answer" ⇒ a plain 500: never the 503, never a fall-through.

        A ``ResponseError`` is Redis ANSWERING with an error (WRONGTYPE,
        NOPERM, OOM …) and a ``TypeError`` is a bug. Neither says that retrying
        is safe and may work, so neither gets the retryable pair; neither lets
        the token through (the lenient read logged both and rotated it).
        """
        user = logged_in["user"]
        await self._seed_revoked_but_live(test_redis_client, logged_in)
        attempts = settings.REFRESH_MAX_FAILURES + 1
        rows_before = await self._session_rows(user["id"])
        keys_before = await self._auth_keys(test_redis_client)

        failed = []
        with ExitStack() as stack:
            revoked = stack.enter_context(self._spy_revocations())
            writes = stack.enter_context(self._record_redis_writes())
            looked_up = stack.enter_context(self._spy_user_lookups())
            stack.enter_context(
                _redis_command_failing_on("exists", "blacklist:", exc_type, failed)
            )
            responses = [
                await self._refresh(client, logged_in["refresh"]) for _ in range(attempts)
            ]

        statuses = [res.status_code for res in responses]
        assert revoked == [], f"invalidate_all_sessions ran; statuses={statuses}"
        for res in responses:
            self._assert_fail_closed_500(res)
        assert len(failed) == attempts, failed
        assert looked_up == [], "STEP 2 must refuse before the DB is read"
        assert writes == [], writes
        self._assert_auth_keys_unchanged(keys_before, await self._auth_keys(test_redis_client))
        assert await self._session_rows(user["id"]) == rows_before
        assert breaker.current_state is CircuitBreakerState.CLOSED

        after = await self._refresh(client, logged_in["refresh"])
        assert after.status_code == 401, after.text

    async def test_answered_jti_blacklist_is_401_and_counted(
        self, client, logged_in, test_redis_client
    ):
        """Redis ANSWERED "blacklisted" ⇒ 401 INVALID_TOKEN + counted, as before.

        ``session:{jti}`` and the DB row are still live, so STEP 2 is the only
        check that can refuse this token.
        """
        user, jti = logged_in["user"], logged_in["jti"]
        await self._seed_revoked_but_live(test_redis_client, logged_in)
        rows_before = await self._session_rows(user["id"])

        with self._record_redis_writes() as writes, self._spy_user_lookups() as looked_up:
            res = await self._refresh(client, logged_in["refresh"])

        assert res.status_code == 401, res.text
        assert res.json().get("error_code") == "INVALID_TOKEN", res.text
        assert "refresh_token" not in res.cookies and "access_token" not in res.cookies
        assert looked_up == [], looked_up
        assert writes == [("set", f"refresh_fail:{user['username']}")], writes
        assert await test_redis_client.get(f"refresh_fail:{user['username']}") == "1"
        assert await test_redis_client.get(f"blacklist:{jti}") == "revoked"
        assert await test_redis_client.exists(f"session:{jti}") == 1
        assert await self._session_rows(user["id"]) == rows_before

    @pytest.mark.parametrize(
        "fault",
        [
            "connection",
            "timeout",
            "breaker_open",
            "response_error",
            "type_error",
            "answered_blacklisted",
        ],
    )
    async def test_step2_logs_carry_no_jti_key_or_message(
        self, client, regular_user_in_db, clear_redis_keys, test_redis_client, breaker,
        caplog, fault,
    ):
        """STEP 2 logs a label and the exception class: never the jti, the key, the message.

        Read from the RENDERED records (structlog → stdlib → ``caplog``, the
        path production logs take). The jti is a canary signed into a real
        refresh token, so a truncated jti (``jti[:8]``) is caught too; the
        injected exception message is a second canary (the lenient read logged
        ``error=str(e)`` plus a traceback). Asserting the expected event first
        proves the capture sees these logs at all.
        """
        user = regular_user_in_db
        jti = f"CANARYJTI{uuid.uuid4().hex}"
        message = f"CANARYMSG{uuid.uuid4().hex}"
        refresh = jwt.encode(
            {
                "sub": user["username"],
                "jti": jti,
                "type": "refresh",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        exc_types = {
            "connection": RedisConnectionError,
            "timeout": RedisTimeoutError,
            "response_error": RedisResponseError,
            "type_error": TypeError,
        }
        status, event = {
            "connection": (503, self.STEP2_DEFERRED_EVENT),
            "timeout": (503, self.STEP2_DEFERRED_EVENT),
            "breaker_open": (503, self.STEP2_DEFERRED_EVENT),
            "response_error": (500, self.STEP2_REFUSED_EVENT),
            "type_error": (500, self.STEP2_REFUSED_EVENT),
            "answered_blacklisted": (401, self.STEP2_BLACKLISTED_EVENT),
        }[fault]
        if fault == "answered_blacklisted":
            await test_redis_client.set(f"blacklist:{jti}", "revoked", ex=3600)

        hits = []
        caplog.set_level(logging.DEBUG)
        with ExitStack() as stack:
            if fault == "breaker_open":
                breaker.open()
            elif fault in exc_types:
                stack.enter_context(
                    self._fail_exists_with(f"blacklist:{jti}", exc_types[fault](message), hits)
                )
            res = await self._refresh(client, refresh)
        _reset_redis_breaker(breaker)

        assert res.status_code == status, res.text
        assert hits == (["exists:blacklist"] if fault in exc_types else []), hits
        lines = [record.getMessage() for record in caplog.records]
        assert any(event in line for line in lines), lines
        if fault in ("response_error", "type_error"):
            assert any(exc_types[fault].__name__ in line for line in lines), lines
        for text in lines + [caplog.text]:
            assert jti[:8] not in text, text
            assert message[:9] not in text, text

    # --- the code is emitted ONLY before the rotation ----------------------------

    @pytest.mark.parametrize("stage", ["redis_rotate", "db_commit"])
    async def test_failure_after_rotation_started_is_not_state_unavailable(
        self, client, logged_in, stage
    ):
        """Both strict reads answered; the rotation itself fails ⇒ 503 WITHOUT the code.

        The frontend retries ``AUTH_STATE_UNAVAILABLE`` because it proves the
        token was never rotated. A failure at STEP 7/8 proves nothing of the
        sort, so it must stay the generic 503 the client treats as ambiguous.
        """
        injected = []
        with ExitStack() as stack:
            if stage == "redis_rotate":
                original_pipeline = db_module.redis_client.pipeline

                def _pipeline(*args, **kwargs):
                    pipe = original_pipeline(*args, **kwargs)
                    if not injected:  # the rotation; the compensation runs for real

                        async def _execute(*_a, **_k):
                            injected.append("execute")
                            raise RedisConnectionError("simulated Redis outage")

                        pipe.execute = _execute
                    return pipe

                stack.enter_context(
                    patch.object(db_module.redis_client, "pipeline", _pipeline)
                )
            else:

                async def _commit(*_a, **_k):
                    injected.append("commit")
                    raise RuntimeError("simulated DB commit failure")

                stack.enter_context(patch.object(AsyncSession, "commit", _commit))
            res = await self._refresh(client, logged_in["refresh"])

        assert injected, "the rotation-stage failure was never reached"
        assert res.status_code == 503, res.text
        assert res.json().get("error_code") != AUTH_STATE_ERROR_CODE, res.text
        assert res.json().get("error_code") == "HTTP_503", res.text

    # --- a logged-out token never rotates ----------------------------------------

    # Which client reads fail in each state. Logout leaves ``blacklist:{jti}``
    # = "revoked", deleted ``session:{jti}`` and a revoked DB row; STEP 2 reads
    # that blacklist FIRST (strict read), so an outage on a later key alone is
    # never reached — the answered STEP 2 already says 401 — and an outage on
    # STEP 2 itself is the 503.
    LOGGED_OUT_OUTAGES = {
        "healthy": [],
        "session_unreadable": [("get", "session:")],
        "user_blacklist_unreadable": [("exists", "user_blacklist:")],
        "jti_blacklist_unreadable": [("exists", "blacklist:")],
        "jti_blacklist_and_session_unreadable": [("exists", "blacklist:"), ("get", "session:")],
        "jti_blacklist_and_user_blacklist_unreadable": [
            ("exists", "blacklist:"),
            ("exists", "user_blacklist:"),
        ],
    }

    @pytest.mark.parametrize(
        "redis_state, expected_status, outage_reached",
        [
            ("healthy", 401, False),
            ("session_unreadable", 401, False),
            ("user_blacklist_unreadable", 401, False),
            # STEP 2 unanswered ⇒ the 503 (strict read). It was a 401 only by
            # luck: the lenient read fell through and STEP 4 found the session
            # gone because logout ALSO deleted it. Where that DELETE had failed,
            # the same outage rotated the logged-out token
            # (``test_jti_blacklist_unreadable_is_503_never_scored``).
            ("jti_blacklist_unreadable", 503, True),
            ("jti_blacklist_and_session_unreadable", 503, True),
            ("jti_blacklist_and_user_blacklist_unreadable", 503, True),
            ("all_down", 503, True),
            ("breaker_open", 503, True),
        ],
    )
    async def test_logged_out_token_never_rotates(
        self, client, logged_in, test_redis_client, breaker,
        redis_state, expected_status, outage_reached,
    ):
        """CONTROL: whatever Redis does, a logged-out refresh token is never rotated."""
        user, refresh, jti = logged_in["user"], logged_in["refresh"], logged_in["jti"]
        client.cookies.clear()
        out = await client.post(
            self.LOGOUT_URL,
            headers={
                "Cookie": f"access_token={logged_in['access']}; refresh_token={refresh}",
                "Authorization": f"Bearer {logged_in['access']}",
            },
        )
        client.cookies.clear()
        assert out.status_code == 204, out.text
        rows_before = await self._session_rows(user["id"])
        assert [row[1] for row in rows_before] == [jti], rows_before
        assert rows_before[0][2] is not None, "precondition: the DB row is revoked"
        assert await test_redis_client.exists(f"session:{jti}") == 0
        assert await test_redis_client.get(f"blacklist:{jti}") == "revoked"

        failed = []
        with ExitStack() as stack:
            if redis_state == "all_down":
                failed = stack.enter_context(self._redis_all_down())
            elif redis_state == "breaker_open":
                breaker.open()
                failed.append("breaker")
            else:
                for command, prefix in self.LOGGED_OUT_OUTAGES[redis_state]:
                    stack.enter_context(
                        _redis_command_failing_on(command, prefix, RedisConnectionError, failed)
                    )
            res = await self._refresh(client, refresh)
        _reset_redis_breaker(breaker)

        assert bool(failed) is outage_reached, (redis_state, failed)
        assert res.status_code == expected_status, res.text
        assert "refresh_token" not in res.cookies and "access_token" not in res.cookies
        assert await self._session_rows(user["id"]) == rows_before
        # ... and once Redis answers again, still no rotation.
        again = await self._refresh(client, refresh)
        assert again.status_code == 401, again.text
        assert await self._session_rows(user["id"]) == rows_before

    # --- ONE source: /refresh's 503 IS /login's 503 --------------------------------

    async def test_refresh_503_is_the_login_503(
        self, client, logged_in, test_redis_client, breaker
    ):
        """Same status, same body, same ``Retry-After`` on both endpoints.

        ``/login`` (lockout EXISTS unanswered) and ``/refresh`` (session GET
        unanswered) raise different subclasses; the client must not be able to
        tell them apart, because it branches on this exact pair.
        """
        user = logged_in["user"]
        login_calls, refresh_calls = [], []
        with _redis_command_failing_on(
            "exists", "account_lockout:", RedisConnectionError, login_calls
        ):
            login_res = await _post_login(client, user["username"], user["password"])
        with _redis_command_failing_on("get", "session:", RedisConnectionError, refresh_calls):
            refresh_res = await self._refresh(client, logged_in["refresh"])

        assert login_calls and refresh_calls, (login_calls, refresh_calls)
        assert (login_res.status_code, refresh_res.status_code) == (503, 503)
        assert refresh_res.json() == login_res.json(), (refresh_res.json(), login_res.json())
        assert refresh_res.headers.get("retry-after") == login_res.headers.get("retry-after")
        self._assert_state_unavailable(refresh_res)
        _assert_auth_state_unavailable(login_res)

    @pytest.mark.parametrize("reader", ["session", "user_blacklist", "breaker_open"])
    async def test_refresh_takes_everything_from_the_class(
        self, client, logged_in, test_redis_client, breaker, monkeypatch, reader
    ):
        """Change ``AuthStateUnavailable`` and ``/refresh``'s 503 must follow.

        A router, a handler or ``RefreshStateUnavailable`` that re-declares the
        code, the text or the header value answers with the SAME values as the
        class today, so only a changed class tells the copy apart from the
        source (same probe as ``TestAuthStateUnavailableSingleSource``).
        """
        assert issubclass(RefreshStateUnavailable, AuthStateUnavailable)
        monkeypatch.setattr(AuthStateUnavailable, "error_code", "AUTH_STATE_SOURCE_PROBE")
        monkeypatch.setattr(AuthStateUnavailable, "detail", "single-source probe")
        monkeypatch.setattr(AuthStateUnavailable, "retry_after_seconds", 137)

        failed = []
        with ExitStack() as stack:
            if reader == "session":
                stack.enter_context(
                    _redis_command_failing_on("get", "session:", RedisConnectionError, failed)
                )
            elif reader == "user_blacklist":
                stack.enter_context(
                    _redis_command_failing_on(
                        "exists", "user_blacklist:", RedisConnectionError, failed
                    )
                )
            else:
                breaker.open()
                failed.append("breaker")
            res = await self._refresh(client, logged_in["refresh"])

        assert failed
        assert res.status_code == 503, res.text
        assert res.json() == {
            "detail": "single-source probe",
            "error_code": "AUTH_STATE_SOURCE_PROBE",
        }, res.text
        assert res.headers.get("retry-after") == "137", dict(res.headers)
        assert res.headers.get_list("set-cookie") == []


# =============================================================================
# 10. get_current_user (HTTP) and Socket.IO: the ``user_blacklist`` read
# =============================================================================
#
# ``user_blacklist:{user_id}`` is what ``invalidate_all_sessions`` leaves when
# it ends every session of a user. The DB revoke that goes with it is only
# staged in the caller's transaction, and a caller that rolls back or never
# commits leaves the key as the ONLY record. So a read Redis did not answer
# (connection/timeout error, breaker OPEN) must never count as "not
# blacklisted". The lenient ``safe_redis_*`` reads did exactly that, and the
# old DB fallback ("the user has SOME active session") passed the user once
# the breaker was OPEN.
#
# While Redis does not answer, nobody can tell a blacklisted user from a
# normal one, so both get the same outcome:
#
# * HTTP (``get_current_user`` STEP 3): 503 ``AUTH_STATE_UNAVAILABLE`` — never
#   200 (blacklisted user), never 401 (normal user: a 401 says the token is
#   bad). Any OTHER error on that read ⇒ a plain 500.
# * Socket connect (``_get_user_from_token``): refused.
# * ``revalidate_auth``: disconnected, ``valid`` False.
#
# Every case keeps the user's DB session row and ``session:{jti}`` LIVE, so the
# blacklist read is the only check left that can refuse, and first asks the
# same question with Redis healthy (the control) so the answer an outage hides
# is known.

from app import socket_manager  # noqa: E402

_BLACKLIST_PREFIX = "user_blacklist:"
_FAULT_EXC = {"connection": RedisConnectionError, "timeout": RedisTimeoutError}


@pytest.mark.asyncio
@pytest.mark.security
class TestUserBlacklistUnreadable:
    """HTTP auth and Socket.IO must tell "Redis did not answer" from "not blacklisted"."""

    CHECK_URL = "/api/auth/check-status"
    SID = "sid-user-blacklist-unreadable"

    @pytest.fixture
    def breaker(self, redis_breaker_reset):
        """The module's ``redis_breaker_reset``: clean before AND after, even on red."""
        return redis_breaker_reset

    @pytest_asyncio.fixture
    async def authed(self, client, regular_user_in_db, clear_redis_keys, breaker):
        """Log in with Redis healthy; return the user, the access token and its session jti."""
        user = regular_user_in_db
        client.cookies.clear()
        res = await client.post(
            "/api/auth/login", data={"username": user["username"], "password": user["password"]}
        )
        client.cookies.clear()
        assert res.status_code == 200, res.text
        access = res.cookies.get("access_token")
        assert access, "login did not set the access cookie"
        payload = jwt.decode(access, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return {"user": user, "access": access, "r_jti": payload["r_jti"]}

    # --- helpers -----------------------------------------------------------------

    async def _check(self, client, access: str):
        client.cookies.clear()
        try:
            return await client.get(self.CHECK_URL, headers={"Cookie": f"access_token={access}"})
        finally:
            client.cookies.clear()

    @staticmethod
    async def _blacklist(redis, user_id: int) -> None:
        await redis.set(f"{_BLACKLIST_PREFIX}{user_id}", "sessions_invalidated", ex=3600)

    @staticmethod
    @contextmanager
    def _blacklist_unreadable(exc_type):
        """GET and EXISTS on ``user_blacklist:*`` raise ``exc_type``; every other key is served.

        Both commands, so the case does not depend on which one the code under
        test reads the key with.
        """
        failed = []
        with ExitStack() as stack:
            for command in ("get", "exists"):
                stack.enter_context(
                    _redis_command_failing_on(command, _BLACKLIST_PREFIX, exc_type, failed)
                )
            yield failed

    @staticmethod
    @contextmanager
    def _breaker_opens_after_session_read(breaker):
        """The ``session:*`` GET is answered, then the breaker is OPEN for what follows.

        Socket connect and ``revalidate_auth`` read ``session:{jti}`` BEFORE the
        blacklist; opening the breaker up front would refuse at that first read
        and never reach the one under test.
        """
        original = db_module.redis_client.get
        opened = []

        async def _get(*args, **kwargs):
            value = await original(*args, **kwargs)
            if args and isinstance(args[0], str) and args[0].startswith("session:"):
                breaker.open()
                opened.append(args[0])
            return value

        with patch.object(db_module.redis_client, "get", _get):
            yield opened

    @contextmanager
    def _http_fault(self, fault, breaker):
        if fault in _FAULT_EXC:
            with self._blacklist_unreadable(_FAULT_EXC[fault]) as failed:
                yield failed
        elif fault == "breaker_open":
            breaker.open()
            yield ["breaker"]
        else:
            assert fault == "all_down", fault
            with _redis_down() as calls:
                yield calls

    @contextmanager
    def _socket_fault(self, fault, breaker):
        if fault in _FAULT_EXC:
            with self._blacklist_unreadable(_FAULT_EXC[fault]) as failed:
                yield failed
        else:
            assert fault == "breaker_open", fault
            with self._breaker_opens_after_session_read(breaker) as opened:
                yield opened

    @staticmethod
    def _fake_sio(user_id: int, jti: str):
        fake = MagicMock()
        fake.get_session = AsyncMock(return_value={"user_id": user_id, "jti": jti})
        fake.disconnect = AsyncMock()
        return fake

    # --- HTTP: get_current_user STEP 3 ---------------------------------------------

    @pytest.mark.parametrize("who", ["blacklisted", "normal"])
    @pytest.mark.parametrize("fault", ["connection", "timeout", "breaker_open", "all_down"])
    async def test_http_unreadable_is_503_whatever_the_answer_would_be(
        self, client, authed, test_redis_client, breaker, who, fault
    ):
        """No answer ⇒ 503: never 200 for the blacklisted user, never 401 for the normal one.

        ``all_down`` is the outage as it starts (breaker CLOSED, every command
        fails); ``breaker_open`` is the outage once it has settled. Nothing the
        outage touches is revoked: the DB row and the Redis session key stay.
        """
        user, access, jti = authed["user"], authed["access"], authed["r_jti"]
        if who == "blacklisted":
            await self._blacklist(test_redis_client, user["id"])
        control = await self._check(client, access)
        assert control.status_code == (401 if who == "blacklisted" else 200), control.text
        rows_before = await TestRefreshRedisStateUnavailable._session_rows(user["id"])

        with self._http_fault(fault, breaker) as failed:
            res = await self._check(client, access)

        assert failed, "the fault never reached Redis"
        _assert_auth_state_unavailable(res)
        _reset_redis_breaker(breaker)
        assert await TestRefreshRedisStateUnavailable._session_rows(user["id"]) == rows_before
        assert await test_redis_client.get(f"session:{jti}") == str(user["id"])

    @pytest.mark.parametrize(
        "exc_type", [RedisResponseError, TypeError], ids=["response_error", "type_error"]
    )
    async def test_http_other_error_is_500_never_200(
        self, client, authed, test_redis_client, breaker, exc_type
    ):
        """Redis ANSWERED with an error (NOPERM, WRONGTYPE…) or a bug ⇒ plain 500, not a pass."""
        user = authed["user"]
        await self._blacklist(test_redis_client, user["id"])

        with self._blacklist_unreadable(exc_type) as failed:
            res = await self._check(client, authed["access"])

        assert failed, "the fault never reached Redis"
        TestRefreshRedisStateUnavailable._assert_fail_closed_500(res)
        assert breaker.current_state is CircuitBreakerState.CLOSED

    @pytest.mark.parametrize("fault", ["connection", "response_error"])
    async def test_http_error_logs_carry_no_key_jti_or_message(
        self, client, authed, test_redis_client, breaker, caplog, fault
    ):
        """The refusal logs event/action, user_id and (500) the exception CLASS.

        Never the Redis key, the session jti or the exception message (a canary).
        Asserting the event first proves the capture sees these logs at all.
        """
        user = authed["user"]
        key = f"{_BLACKLIST_PREFIX}{user['id']}"
        message = f"CANARYMSG{uuid.uuid4().hex}"
        exc_type = {"connection": RedisConnectionError, "response_error": RedisResponseError}[fault]
        event = {
            "connection": "Access deferred: user blacklist unreadable",
            "response_error": "Access refused: user blacklist check failed",
        }[fault]
        original = db_module.redis_client.exists

        async def _exists(*args, **kwargs):
            if args and args[0] == key:
                raise exc_type(message)
            return await original(*args, **kwargs)

        caplog.set_level(logging.DEBUG)
        with patch.object(db_module.redis_client, "exists", _exists):
            res = await self._check(client, authed["access"])

        assert res.status_code == (503 if fault == "connection" else 500), res.text
        lines = [record.getMessage() for record in caplog.records]
        refused = [line for line in lines if event in line]
        assert refused, lines
        for line in refused:
            assert "user_id" in line, line
            assert key not in line, line
            assert authed["r_jti"] not in line, line
        for text in lines + [caplog.text]:
            assert message[:9] not in text, text

    # --- Socket.IO connect: _get_user_from_token -----------------------------------

    @pytest.mark.parametrize("who", ["blacklisted", "normal"])
    @pytest.mark.parametrize("fault", ["connection", "timeout", "breaker_open"])
    async def test_socket_connect_unreadable_is_refused(
        self, authed, test_redis_client, breaker, who, fault
    ):
        """No answer ⇒ the connection is refused, blacklisted or not.

        Before, a connection/timeout error read as "not blacklisted" and an OPEN
        breaker fell back to "the user has SOME active session" — already true
        for the exact-jti DB check that runs just before.
        """
        user, access = authed["user"], authed["access"]
        if who == "blacklisted":
            await self._blacklist(test_redis_client, user["id"])
            with pytest.raises(ConnectionRefusedError):
                await socket_manager._get_user_from_token(access)
        else:
            assert (await socket_manager._get_user_from_token(access)).id == user["id"]

        with self._socket_fault(fault, breaker) as failed:
            with pytest.raises(ConnectionRefusedError):
                await socket_manager._get_user_from_token(access)

        assert failed, "the fault never reached Redis"

    # --- Socket.IO periodic check: revalidate_auth ---------------------------------

    @pytest.mark.parametrize("who", ["blacklisted", "normal"])
    @pytest.mark.parametrize("fault", ["connection", "timeout", "breaker_open"])
    async def test_socket_revalidate_unreadable_disconnects(
        self, authed, test_redis_client, breaker, who, fault
    ):
        """No answer ⇒ ``valid`` False and the socket is disconnected, blacklisted or not.

        Before, a connection/timeout error read as "not blacklisted" and the
        socket stayed connected. For a normal user the frontend treats any
        server disconnect as a logout (``frontend/src/lib/socket/client.ts``);
        that is the price of not serving a socket nobody can vouch for.
        """
        user, jti = authed["user"], authed["r_jti"]
        fake_sio = self._fake_sio(user["id"], jti)
        if who == "blacklisted":
            await self._blacklist(test_redis_client, user["id"])

        with patch.object(socket_manager, "sio", fake_sio):
            control = await socket_manager.revalidate_auth(self.SID)
            assert control["valid"] is (who == "normal"), control
            fake_sio.disconnect.reset_mock()

            with self._socket_fault(fault, breaker) as failed:
                verdict = await socket_manager.revalidate_auth(self.SID)

        assert failed, "the fault never reached Redis"
        assert verdict["valid"] is False, verdict
        fake_sio.disconnect.assert_awaited_once_with(self.SID)


# =============================================================================
# 11. get_current_user STEP 2 (``blacklist:{access_jti}``), and the
#     ``session:{r_jti}`` read of HTTP STEP 4 and ``revalidate_auth``
# =============================================================================
#
# STEP 2 reads a record only Redis may hold: logout writes
# ``blacklist:{access_jti}`` BEFORE its COMMIT, so when that COMMIT fails the
# DB row stays live and only Redis records the logout. No answer ⇒
# the same 503 as STEP 3, for a logged-out and a live token alike; any other
# error ⇒ a plain 500.
#
# ``session:{r_jti}`` is a CACHE of the DB row that deps STEP 4b and the
# exact-jti check of ``revalidate_auth`` read on every path. No answer is
# neither a miss (a 401, or a disconnect the frontend turns into a logout) nor
# a pass: the DB row decides — live ⇒ allowed; revoked, or the DB unreadable
# too ⇒ refused. An ANSWERED miss stays the fast reject.
#
# ``fault``: ``connection``/``timeout`` raise at the CLIENT for GET/EXISTS of
# the keys under test (breaker CLOSED); ``breaker_open`` is the REAL breaker
# OPEN for exactly that read and CLOSED again for the next one, so the read
# under test is the only one Redis does not answer.

from sqlalchemy import update  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.repositories import SessionRepository  # noqa: E402

_READ_COMMANDS = ("get", "exists")


@contextmanager
def _reads_unanswered(fault: str, key_prefix: str, breaker):
    """Redis does not answer GET/EXISTS of keys under ``key_prefix``; every other key is served.

    Yields the keys the fault hit, so a case can prove the fault reached the
    read it is about.
    """
    hit: list = []
    if fault in _FAULT_EXC:
        with ExitStack() as stack:
            for command in _READ_COMMANDS:
                stack.enter_context(
                    _redis_command_failing_on(command, key_prefix, _FAULT_EXC[fault], hit)
                )
            yield hit
        return
    assert fault == "breaker_open", fault
    original = breaker.call_async

    async def _call(func, *args, **kwargs):
        key = args[0] if args else None
        if (
            getattr(func, "__name__", None) in _READ_COMMANDS
            and isinstance(key, str)
            and key.startswith(key_prefix)
        ):
            hit.append(key)
            breaker.open()
            try:
                return await original(func, *args, **kwargs)
            finally:
                _reset_redis_breaker(breaker)
        return await original(func, *args, **kwargs)

    with patch.object(breaker, "call_async", _call):
        yield hit


@contextmanager
def _session_row_unreadable():
    """The exact-jti DB read (``get_by_refresh_jti_and_user``) raises; yields its calls."""
    calls: list = []

    async def _down(self, jti, user_id):
        calls.append((jti, user_id))
        raise OperationalError("SELECT", {}, Exception("injected: DB did not answer"))

    with patch.object(SessionRepository, "get_by_refresh_jti_and_user", _down):
        yield calls


async def _login_tokens(client, user: dict) -> dict:
    """Log in with Redis healthy: the access token, its jti and its session's ``r_jti``."""
    client.cookies.clear()
    res = await client.post(
        "/api/auth/login", data={"username": user["username"], "password": user["password"]}
    )
    client.cookies.clear()
    assert res.status_code == 200, res.text
    access = res.cookies.get("access_token")
    assert access, "login did not set the access cookie"
    payload = jwt.decode(access, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    return {"user": user, "access": access, "access_jti": payload["jti"], "r_jti": payload["r_jti"]}


async def _check_status(client, access: str):
    """``/api/auth/check-status`` with only the access cookie."""
    client.cookies.clear()
    try:
        return await client.get(
            "/api/auth/check-status", headers={"Cookie": f"access_token={access}"}
        )
    finally:
        client.cookies.clear()


async def _revoke_row_in_db_only(jti: str) -> None:
    """Revoke the DB row and commit; ``session:{jti}`` stays in Redis (a stale cache)."""
    async with db_module.AsyncSessionLocal() as session:
        await session.execute(
            update(models.UserSession)
            .where(models.UserSession.refresh_jti == jti)
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await session.commit()


def _assert_401(res) -> None:
    assert (res.status_code, res.json().get("error_code")) == (401, "INVALID_TOKEN"), res.text
    _assert_no_tokens(res)


def _logged(caplog, logger: str, text: str) -> bool:
    return any(text in r.getMessage() for r in caplog.records if r.name == logger)


@pytest.mark.asyncio
@pytest.mark.security
class TestAccessJtiBlacklistUnreadable:
    """HTTP STEP 2 must tell "Redis did not answer" from "not logged out"."""

    PREFIX = "blacklist:"

    @pytest.fixture
    def breaker(self, redis_breaker_reset):
        """The module's ``redis_breaker_reset``: clean before AND after, even on red."""
        return redis_breaker_reset

    @pytest_asyncio.fixture
    async def authed(self, client, regular_user_in_db, clear_redis_keys, breaker):
        return await _login_tokens(client, regular_user_in_db)

    @staticmethod
    async def _log_out_in_redis_only(redis, access_jti: str) -> None:
        """What a logout leaves when its ``session:`` delete was lost and its COMMIT failed.

        ``blacklist:{access_jti}`` is set; the DB row and ``session:{r_jti}``
        stay live, so STEP 2 is the ONLY check that refuses the token.
        """
        await redis.set(f"blacklist:{access_jti}", "revoked", ex=900)

    @pytest.mark.parametrize("who", ["logged_out", "live"])
    @pytest.mark.parametrize("fault", ["connection", "timeout", "breaker_open"])
    async def test_unreadable_is_503_whatever_the_answer_would_be(
        self, client, authed, test_redis_client, breaker, who, fault
    ):
        """No answer ⇒ 503: never 200 for the logged-out token, never 401 for the live one."""
        user, access = authed["user"], authed["access"]
        if who == "logged_out":
            await self._log_out_in_redis_only(test_redis_client, authed["access_jti"])
        control = await _check_status(client, access)
        assert control.status_code == (401 if who == "logged_out" else 200), control.text
        rows_before = await TestRefreshRedisStateUnavailable._session_rows(user["id"])

        with _reads_unanswered(fault, self.PREFIX, breaker) as hit:
            res = await _check_status(client, access)

        assert hit == [f"blacklist:{authed['access_jti']}"], hit
        _assert_auth_state_unavailable(res)
        assert breaker.current_state is CircuitBreakerState.CLOSED
        assert await TestRefreshRedisStateUnavailable._session_rows(user["id"]) == rows_before
        assert await test_redis_client.get(f"session:{authed['r_jti']}") == str(user["id"])

    @pytest.mark.parametrize(
        "exc_type", [RedisResponseError, TypeError], ids=["response_error", "type_error"]
    )
    async def test_other_error_is_500_never_200(
        self, client, authed, test_redis_client, breaker, exc_type
    ):
        """Redis ANSWERED with an error (NOPERM, WRONGTYPE…) or a bug ⇒ plain 500, not a pass."""
        await self._log_out_in_redis_only(test_redis_client, authed["access_jti"])
        hit: list = []
        with ExitStack() as stack:
            for command in _READ_COMMANDS:
                stack.enter_context(
                    _redis_command_failing_on(command, self.PREFIX, exc_type, hit)
                )
            res = await _check_status(client, authed["access"])

        assert hit, "the fault never reached Redis"
        TestRefreshRedisStateUnavailable._assert_fail_closed_500(res)
        assert breaker.current_state is CircuitBreakerState.CLOSED

    @pytest.mark.parametrize("fault", ["connection", "response_error"])
    async def test_error_logs_carry_no_key_jti_or_message(
        self, client, authed, breaker, caplog, fault
    ):
        """The refusal logs event/action and (500) the exception CLASS.

        Never the Redis key, the access jti, the session jti or the exception
        message (a canary). Asserting the event first proves the capture sees
        these logs at all.
        """
        key = f"blacklist:{authed['access_jti']}"
        message = f"CANARYMSG{uuid.uuid4().hex}"
        exc_type = {"connection": RedisConnectionError, "response_error": RedisResponseError}[fault]
        event, action = {
            "connection": (
                "Access deferred: access token blacklist unreadable",
                "auth.access_state_unavailable",
            ),
            "response_error": (
                "Access refused: access token blacklist check failed",
                "auth.access_jti_blacklist_error",
            ),
        }[fault]
        original = db_module.redis_client.exists

        async def _exists(*args, **kwargs):
            if args and args[0] == key:
                raise exc_type(message)
            return await original(*args, **kwargs)

        caplog.set_level(logging.DEBUG)
        with patch.object(db_module.redis_client, "exists", _exists):
            res = await _check_status(client, authed["access"])

        assert res.status_code == (503 if fault == "connection" else 500), res.text
        lines = [record.getMessage() for record in caplog.records]
        refused = [line for line in lines if event in line]
        assert refused, lines
        for line in refused:
            assert action in line, line
            assert key not in line, line
            assert authed["access_jti"] not in line, line
            assert authed["r_jti"] not in line, line
        for text in lines + [caplog.text]:
            assert message[:9] not in text, text


@pytest.mark.asyncio
@pytest.mark.security
class TestSessionCacheUnreadable:
    """``session:{r_jti}`` Redis did not answer: neither a miss nor a pass — the DB row decides."""

    PREFIX = "session:"
    SID = "sid-session-cache-unreadable"

    @pytest.fixture
    def breaker(self, redis_breaker_reset):
        """The module's ``redis_breaker_reset``: clean before AND after, even on red."""
        return redis_breaker_reset

    @pytest_asyncio.fixture
    async def authed(self, client, regular_user_in_db, clear_redis_keys, breaker):
        return await _login_tokens(client, regular_user_in_db)

    # --- HTTP: get_current_user STEP 4 / 4b ----------------------------------------

    @pytest.mark.parametrize("row", ["live", "revoked"])
    @pytest.mark.parametrize("fault", ["connection", "timeout", "breaker_open"])
    async def test_http_unreadable_lets_the_db_row_decide(
        self, client, authed, test_redis_client, breaker, caplog, row, fault
    ):
        """Live row ⇒ 200 (not the 401 of a miss); revoked row ⇒ 401 from STEP 4b.

        The key stays in Redis for the revoked row (a stale cache): with Redis
        healthy that row is refused by STEP 4b too, never by the fast path.
        """
        user, access, jti = authed["user"], authed["access"], authed["r_jti"]
        control = await _check_status(client, access)
        assert control.status_code == 200, control.text
        if row == "revoked":
            await _revoke_row_in_db_only(jti)
        assert await test_redis_client.get(f"session:{jti}") == str(user["id"])

        with caplog.at_level(logging.WARNING, logger="app"):
            with _reads_unanswered(fault, self.PREFIX, breaker) as hit:
                res = await _check_status(client, access)

        assert hit == [f"session:{jti}"], hit
        if row == "live":
            assert res.status_code == 200, res.text
            assert res.json()["user_id"] == user["id"], res.text
        else:
            _assert_401(res)
            assert _logged(caplog, "app.core.deps", "no non-revoked DB row"), (
                "the 401 did not come from the DB row (STEP 4b)"
            )
        assert breaker.current_state is CircuitBreakerState.CLOSED

    @pytest.mark.parametrize("fault", ["connection", "breaker_open"])
    async def test_http_unreadable_and_db_unreadable_is_refused(
        self, client, authed, breaker, fault
    ):
        """Neither Redis nor the DB answered ⇒ refused (STEP 4b's own 401), never 200."""
        with _reads_unanswered(fault, self.PREFIX, breaker) as hit, \
                _session_row_unreadable() as db_calls:
            res = await _check_status(client, authed["access"])

        assert hit == [f"session:{authed['r_jti']}"], hit
        assert db_calls == [(authed["r_jti"], authed["user"]["id"])], db_calls
        _assert_401(res)

    async def test_http_answered_miss_is_still_refused(
        self, client, authed, test_redis_client, breaker
    ):
        """Redis ANSWERED "no such session" ⇒ 401, even though the DB row is live."""
        await test_redis_client.delete(f"session:{authed['r_jti']}")
        rows = await TestRefreshRedisStateUnavailable._session_rows(authed["user"]["id"])
        assert [(row[1], row[2]) for row in rows] == [(authed["r_jti"], None)], rows

        res = await _check_status(client, authed["access"])

        _assert_401(res)

    # --- Socket.IO periodic check: revalidate_auth ---------------------------------

    @pytest.mark.parametrize("who", ["live", "session_revoked", "user_blacklisted"])
    @pytest.mark.parametrize("fault", ["connection", "timeout", "breaker_open"])
    async def test_socket_revalidate_unreadable_lets_the_db_row_decide(
        self, authed, test_redis_client, breaker, caplog, who, fault
    ):
        """No answer ⇒ not "Session revoked": the strict blacklist read and the DB row decide.

        Live ⇒ ``valid`` True and no disconnect (before: disconnected, and the
        frontend logs the user out on that). Revoked row ⇒ refused by the DB
        check; blacklisted user ⇒ refused by the strict ``user_blacklist``
        read. Nothing passes on the unreadable read alone.
        """
        user, jti = authed["user"], authed["r_jti"]
        fake_sio = TestUserBlacklistUnreadable._fake_sio(user["id"], jti)
        expected = {
            "live": {"valid": True},
            "session_revoked": {"valid": False, "reason": "Session revoked"},
            "user_blacklisted": {"valid": False, "reason": "User session invalidated"},
        }[who]

        with patch.object(socket_manager, "sio", fake_sio):
            control = await socket_manager.revalidate_auth(self.SID)
            assert control == {"valid": True}, control
            fake_sio.disconnect.reset_mock()
            if who == "session_revoked":
                await _revoke_row_in_db_only(jti)
            elif who == "user_blacklisted":
                await test_redis_client.set(
                    f"user_blacklist:{user['id']}", "sessions_invalidated", ex=3600
                )

            with caplog.at_level(logging.WARNING, logger="app"):
                with _reads_unanswered(fault, self.PREFIX, breaker) as hit:
                    verdict = await socket_manager.revalidate_auth(self.SID)

        assert hit == [f"session:{jti}"], hit
        assert verdict == expected, verdict
        if who == "live":
            fake_sio.disconnect.assert_not_awaited()
        else:
            fake_sio.disconnect.assert_awaited_once_with(self.SID)
        if who == "session_revoked":
            assert _logged(caplog, "app.socket_manager", "in DB (exact jti)"), (
                "the refusal did not come from the exact-jti DB check"
            )
        assert breaker.current_state is CircuitBreakerState.CLOSED

    @pytest.mark.parametrize("fault", ["connection", "breaker_open"])
    async def test_socket_revalidate_unreadable_and_db_unreadable_disconnects(
        self, authed, breaker, fault
    ):
        """Neither Redis nor the DB answered ⇒ disconnected, never ``valid`` True."""
        user, jti = authed["user"], authed["r_jti"]
        fake_sio = TestUserBlacklistUnreadable._fake_sio(user["id"], jti)

        with patch.object(socket_manager, "sio", fake_sio), \
                _reads_unanswered(fault, self.PREFIX, breaker) as hit, \
                _session_row_unreadable() as db_calls:
            verdict = await socket_manager.revalidate_auth(self.SID)

        assert hit == [f"session:{jti}"], hit
        assert db_calls == [(jti, user["id"])], db_calls
        assert verdict == {"valid": False, "reason": "Validation error"}, verdict
        fake_sio.disconnect.assert_awaited_once_with(self.SID)

    async def test_socket_revalidate_answered_miss_is_still_revoked(
        self, authed, test_redis_client, breaker
    ):
        """Redis ANSWERED "no such session" ⇒ disconnected, even though the DB row is live."""
        user, jti = authed["user"], authed["r_jti"]
        await test_redis_client.delete(f"session:{jti}")
        fake_sio = TestUserBlacklistUnreadable._fake_sio(user["id"], jti)

        with patch.object(socket_manager, "sio", fake_sio):
            verdict = await socket_manager.revalidate_auth(self.SID)

        assert verdict == {"valid": False, "reason": "Session revoked"}, verdict
        fake_sio.disconnect.assert_awaited_once_with(self.SID)
