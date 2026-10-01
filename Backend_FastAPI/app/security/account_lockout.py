# app/security/account_lockout.py
"""
Account Lockout Service

Protects against brute force attacks by temporarily locking accounts
after multiple failed login attempts.

Architecture:
- Uses Redis for fast lockout checks (primary)
- Falls back to database if Redis unavailable
- Configurable lockout duration and max attempts
- Separate tracking for username enumeration prevention
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import (
    RedisUnavailableError,
    redis_exists_or_raise,
    redis_get_or_raise,
    redis_ttl_or_raise,
    safe_redis_delete,
    safe_redis_exists,
    safe_redis_set,
)
from ..models import UserActivityLog
from ..utils.exceptions import AccountLockoutStateUnavailable

log = structlog.get_logger(__name__)

# Label logged by the strict Redis helpers instead of the key itself.
_LOCKOUT_KEY_LABEL = "auth.account_lockout"


async def _read_lockout_state(step: str, username: str, reader, lockout_key: str):
    """One strict read of the lockout key; ANY failure raises ``AccountLockoutStateUnavailable``.

    Two kinds of failure, two log events, one answer (fail-closed):

    - ``RedisUnavailableError``: Redis did not answer (connection/timeout
      error, breaker OPEN). An outage, expected to happen, no traceback.
    - anything else: NOT an outage (a bug, an unexpected reply). Its own event
      WITH the traceback, so a programming error is never filed as "Redis was
      down".

    Neither event carries the Redis key: the account is identified by
    ``username``, as in every other event of this module.
    """
    try:
        return await reader(lockout_key, _LOCKOUT_KEY_LABEL)
    except RedisUnavailableError as exc:
        log.error(
            "account_lockout_state_unavailable",
            username=username,
            step=step,
            reason=str(exc),
        )
        raise AccountLockoutStateUnavailable() from exc
    except Exception as exc:
        log.error(
            "account_lockout_check_unexpected_error",
            username=username,
            step=step,
            error_type=type(exc).__name__,
            exc_info=True,
        )
        raise AccountLockoutStateUnavailable() from exc


# Configuration now comes from settings (see config.py)
# These can be overridden via environment variables:
#   ACCOUNT_LOCKOUT_MAX_ATTEMPTS, ACCOUNT_LOCKOUT_DURATION_MINUTES, ACCOUNT_LOCKOUT_WINDOW_MINUTES


class AccountLockoutService:
    """Service for managing account lockout due to failed login attempts."""

    @staticmethod
    async def check_lockout(username: str) -> Tuple[bool, Optional[int]]:
        """
        Check if account is locked out.

        Args:
            username: Username to check

        Returns:
            Tuple of (is_locked, remaining_seconds), ONLY when Redis answered
            with a state this service can act on:
            - (False, None): there is no lockout. Redis answered EXISTS=0, or
              EXISTS=1 and then TTL=-2 (the key expired between the reads).
            - (True, seconds): the lockout key exists and Redis answered its
              remaining TTL (``seconds`` >= 0, the real value).

        Raises:
            AccountLockoutStateUnavailable: the lockout state could not be
                verified. Redis did not answer EXISTS or TTL (connection or
                timeout error, breaker OPEN), the check failed unexpectedly, or
                the key exists with no expiry (TTL -1).
                SECURITY: the caller must refuse the login (fail-closed) and
                must NOT report a lockout — nothing says the account is locked.

        Example:
            >>> is_locked, ttl = await AccountLockoutService.check_lockout("admin")
            >>> if is_locked:
            ...     print(f"Account locked for {ttl} more seconds")
        """
        lockout_key = f"account_lockout:{username}"

        # 1. Is the account locked? Strict read: an outage must not come back
        #    as "key absent" (False) and be read as "not locked", nor be
        #    reported as a lockout. It is its own answer.
        is_locked = await _read_lockout_state(
            "exists", username, redis_exists_or_raise, lockout_key
        )
        if not is_locked:
            return False, None

        # 2. For how long? Same strict read: a lock is only acted on with a TTL
        #    Redis actually answered. No invented duration.
        remaining_seconds = await _read_lockout_state(
            "ttl", username, redis_ttl_or_raise, lockout_key
        )

        if remaining_seconds == -2:
            # Redis ANSWERED: the key expired between EXISTS and TTL. There is
            # no lockout any more, so the login goes on like any unlocked one.
            # (Owner confirmation point: -2 is an answer, not an outage.)
            return False, None

        if remaining_seconds < 0:
            # -1: the key exists with NO expiry. This service always writes the
            # lockout with an expiry, so this is not one of its lockouts and it
            # would never end on its own. Neither "locked" (a 429 with no real
            # Retry-After) nor "not locked" (fail-open): refuse and alert.
            log.error(
                "account_lockout_key_without_expiry",
                username=username,
                ttl=remaining_seconds,
            )
            raise AccountLockoutStateUnavailable()

        log.warning(
            "Account lockout check: Account is locked",
            username=username,
            remaining_seconds=remaining_seconds,
        )

        return True, remaining_seconds

    @staticmethod
    async def record_failed_attempt(
        db: AsyncSession, username: str, ip_address: Optional[str] = None
    ) -> bool:
        """
        Record a failed login attempt and lock account if threshold exceeded.

        Args:
            db: Database session
            username: Username that failed to authenticate
            ip_address: IP address of the attempt (for logging)

        Returns:
            True only when THIS call's SET of the lockout key returned
            successfully (Redis acknowledged the lock). False otherwise. False
            does NOT prove the account is unlocked or that the stored counter
            is unchanged: when a Redis write fails (e.g. a timeout) its outcome
            is ambiguous — Redis may still have applied it.

        Example:
            >>> is_locked = await AccountLockoutService.record_failed_attempt(
            ...     db, "admin", "192.168.1.1"
            ... )
            >>> if is_locked:
            ...     # Send alert email
        """
        attempts_key = f"login_attempts:{username}"
        lockout_key = f"account_lockout:{username}"
        locked_now = False

        try:
            # Increment failed attempts counter. Strict read: an unreadable
            # counter must not be taken as 0 and written back as 1 — that
            # would wipe the attempts already counted.
            attempts_str = await redis_get_or_raise(attempts_key, "auth.login_attempts")
            current_attempts = int(attempts_str) if attempts_str else 0
            current_attempts += 1

            # Store updated counter with expiration
            await safe_redis_set(
                attempts_key, str(current_attempts), ex=settings.ACCOUNT_LOCKOUT_WINDOW_MINUTES * 60
            )

            log.info(
                "Failed login attempt recorded",
                username=username,
                ip_address=ip_address,
                attempt_count=current_attempts,
                max_attempts=settings.ACCOUNT_LOCKOUT_MAX_ATTEMPTS,
            )

            # Check if threshold exceeded
            if current_attempts >= settings.ACCOUNT_LOCKOUT_MAX_ATTEMPTS:
                # Lock the account
                lockout_duration_seconds = settings.ACCOUNT_LOCKOUT_DURATION_MINUTES * 60
                await safe_redis_set(lockout_key, "1", ex=lockout_duration_seconds)
                locked_now = True

                # Reset attempts counter (start fresh after lockout expires)
                await safe_redis_delete(attempts_key)

                log.warning(
                    "SECURITY ALERT: Account locked due to excessive failed attempts",
                    username=username,
                    ip_address=ip_address,
                    failed_attempts=current_attempts,
                    lockout_duration_minutes=settings.ACCOUNT_LOCKOUT_DURATION_MINUTES,
                )

                # ✅ Log to database for audit trail
                try:
                    activity = UserActivityLog(
                        actor_id=None,  # Unknown user (failed login)
                        action="account_locked",
                        resource_type="account",
                        resource_id=None,
                        changes={
                            "username": username,
                            "reason": "excessive_failed_login_attempts",
                            "failed_attempts": current_attempts,
                            "lockout_duration_minutes": settings.ACCOUNT_LOCKOUT_DURATION_MINUTES,
                            "ip_address": ip_address,
                        },
                        ip_address=ip_address,
                    )
                    db.add(activity)
                    await db.commit()
                except Exception as db_error:
                    log.error(
                        "Failed to log account lockout to database",
                        username=username,
                        error=str(db_error),
                    )
                    # Don't fail lockout if audit log fails
                    await db.rollback()

                return True  # Account is now locked

            return False  # Not locked yet

        except Exception as e:
            log.error(
                "Failed to record failed login attempt",
                username=username,
                account_locked=locked_now,
                error=str(e),
                exc_info=True,
            )
            # What is known after a failure here:
            # - ``locked_now`` is True only if the SET of the lockout key
            #   returned successfully before the failure.
            # - If reading or parsing the counter failed, this call issued no
            #   write (the stored count is never reset to 1).
            # - If the counter SET failed, this attempt may or may not have
            #   been counted.
            # - If only the lockout SET failed, the counter may already have
            #   been incremented (its SET returned), but the lock is not
            #   confirmed.
            # - A timeout after a write does not show whether Redis applied it.
            # The caller's answer does not change (the credential was wrong).
            #
            # Known OPEN debt, fail-open counting: while no lockout key exists,
            # Redis keeps answering reads and the counter SETs are really
            # refused or lost (e.g. MISCONF), failed logins MAY go uncounted and
            # the lockout may never be reached. For reference, check_lockout
            # answers "not locked" when the lockout key is absent or its TTL is
            # -2; it refuses the login with AccountLockoutStateUnavailable when
            # the state cannot be read, the check fails unexpectedly, or the key
            # has no expiry (TTL -1).
            return locked_now

    @staticmethod
    async def reset_attempts(username: str):
        """
        Reset failed login attempts counter (after successful login).

        Args:
            username: Username to reset

        Example:
            >>> await AccountLockoutService.reset_attempts("admin")
        """
        attempts_key = f"login_attempts:{username}"

        try:
            await safe_redis_delete(attempts_key)

            log.info("Login attempts counter reset after successful login", username=username)

        except Exception as e:
            log.error(
                "Failed to reset login attempts counter",
                username=username,
                error=str(e),
            )
            # Non-critical error, just log it

    @staticmethod
    async def unlock_account(username: str) -> bool:
        """
        Manually unlock a locked account (admin override).

        Args:
            username: Username to unlock

        Returns:
            True if account was locked and is now unlocked

        Example:
            >>> was_locked = await AccountLockoutService.unlock_account("admin")
            >>> if was_locked:
            ...     log.info("Admin unlocked account manually")
        """
        lockout_key = f"account_lockout:{username}"
        attempts_key = f"login_attempts:{username}"

        try:
            # Check if account was locked
            was_locked = await safe_redis_exists(lockout_key)

            if was_locked:
                # Remove lockout
                await safe_redis_delete(lockout_key)
                await safe_redis_delete(attempts_key)

                log.warning(
                    "Account manually unlocked (admin override)", username=username
                )

                return True

            return False

        except Exception as e:
            log.error(
                "Failed to unlock account", username=username, error=str(e), exc_info=True
            )
            return False
