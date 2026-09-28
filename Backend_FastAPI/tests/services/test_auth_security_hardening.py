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
"""
import hashlib
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
