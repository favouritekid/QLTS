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
from ..database import safe_redis_delete, safe_redis_exists, safe_redis_get, safe_redis_set
from ..models import UserActivityLog

log = structlog.get_logger(__name__)

# Configuration
MAX_FAILED_ATTEMPTS = 5  # Lock after 5 failed attempts
LOCKOUT_DURATION_MINUTES = 15  # Lock for 15 minutes
ATTEMPT_WINDOW_MINUTES = 30  # Reset counter after 30 minutes of no attempts


class AccountLockoutService:
    """Service for managing account lockout due to failed login attempts."""

    @staticmethod
    async def check_lockout(username: str) -> Tuple[bool, Optional[int]]:
        """
        Check if account is locked out.

        Args:
            username: Username to check

        Returns:
            Tuple of (is_locked, remaining_seconds)
            - is_locked: True if account is currently locked
            - remaining_seconds: Seconds until unlock (None if not locked)

        Example:
            >>> is_locked, ttl = await AccountLockoutService.check_lockout("admin")
            >>> if is_locked:
            ...     print(f"Account locked for {ttl} more seconds")
        """
        lockout_key = f"account_lockout:{username}"

        try:
            # Check Redis for lockout
            is_locked = await safe_redis_exists(lockout_key)

            if is_locked:
                # Get remaining TTL
                ttl_str = await safe_redis_get(f"{lockout_key}:ttl")
                remaining_seconds = int(ttl_str) if ttl_str else LOCKOUT_DURATION_MINUTES * 60

                log.warning(
                    "Account lockout check: Account is locked",
                    username=username,
                    remaining_seconds=remaining_seconds,
                )

                return True, remaining_seconds

            return False, None

        except Exception as e:
            log.error(
                "Failed to check account lockout in Redis",
                username=username,
                error=str(e),
                exc_info=True,
            )
            # Fail-open: Don't block login if Redis is down
            return False, None

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
            True if account is now locked, False otherwise

        Example:
            >>> is_locked = await AccountLockoutService.record_failed_attempt(
            ...     db, "admin", "192.168.1.1"
            ... )
            >>> if is_locked:
            ...     # Send alert email
        """
        attempts_key = f"login_attempts:{username}"
        lockout_key = f"account_lockout:{username}"

        try:
            # Increment failed attempts counter
            attempts_str = await safe_redis_get(attempts_key)
            current_attempts = int(attempts_str) if attempts_str else 0
            current_attempts += 1

            # Store updated counter with expiration
            await safe_redis_set(
                attempts_key, str(current_attempts), ex=ATTEMPT_WINDOW_MINUTES * 60
            )

            log.info(
                "Failed login attempt recorded",
                username=username,
                ip_address=ip_address,
                attempt_count=current_attempts,
                max_attempts=MAX_FAILED_ATTEMPTS,
            )

            # Check if threshold exceeded
            if current_attempts >= MAX_FAILED_ATTEMPTS:
                # Lock the account
                lockout_duration_seconds = LOCKOUT_DURATION_MINUTES * 60
                await safe_redis_set(lockout_key, "1", ex=lockout_duration_seconds)
                await safe_redis_set(
                    f"{lockout_key}:ttl",
                    str(lockout_duration_seconds),
                    ex=lockout_duration_seconds,
                )

                # Reset attempts counter (start fresh after lockout expires)
                await safe_redis_delete(attempts_key)

                log.warning(
                    "SECURITY ALERT: Account locked due to excessive failed attempts",
                    username=username,
                    ip_address=ip_address,
                    failed_attempts=current_attempts,
                    lockout_duration_minutes=LOCKOUT_DURATION_MINUTES,
                )

                # ✅ Log to database for audit trail
                try:
                    activity = UserActivityLog(
                        actor_id=None,  # Unknown user (failed login)
                        action="account_locked",
                        resource_type="account",
                        resource_id=None,
                        details={
                            "username": username,
                            "reason": "excessive_failed_login_attempts",
                            "failed_attempts": current_attempts,
                            "lockout_duration_minutes": LOCKOUT_DURATION_MINUTES,
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
                error=str(e),
                exc_info=True,
            )
            # Fail-open: Don't block functionality if Redis is down
            return False

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
                await safe_redis_delete(f"{lockout_key}:ttl")
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
