"""ADM-023 (2026-04-29): integration tests for the magic-link cooldown
ladder + hard-lock contract in ``verify_and_confirm``.

Pin the four risk-surface scenarios called out by Q9:
1. Repeated CCCD failures step the ladder (5 → 30 → 120 → 1440 min)
   and stamp ``lock_until`` accordingly.
2. ≥30 failures hard-lock the token (``locked_at`` set, ``lock_count``
   incremented, audit row written, hard-lock event dispatched).
3. After ``lock_until`` elapses, the next attempt is admitted again
   (only the SLIDING cooldown — hard lock is permanent).
4. Successful confirmation does not reset the lock counters
   retroactively (current spec: success is terminal — token consumed,
   future attempts hit ``confirmed_at IS NOT NULL`` branch first).

Test pattern mirrors ``tests/integration/test_admission_confirm_lock``:
use ``AsyncSessionLocal`` directly so the lock + audit semantics are
exercised end-to-end at the service boundary, not mocked out.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import admission_service
from app.services.admission_confirmation_cooldown import HARD_LOCK_THRESHOLD
from app.utils.exceptions import BadRequest

from tests.integration.test_admission_state_transitions import (
    create_test_lead,
    create_admission_profile,
)


pytestmark = pytest.mark.asyncio


# Citizen id chosen so last 4 digits ≠ "0000" — the bad input we'll
# feed in to drive the ladder. Token TTL stays at default 7d.
_CITIZEN_ID = "001202999999"  # last 4: 9999
_CORRECT_DIGITS = "9999"
_WRONG_DIGITS = "0000"


async def _seed_token(unit_id: int, admin_user_id: int) -> tuple[int, str]:
    """Create lead + approved profile + active confirmation token.

    ``admin_user_id`` is needed because ``create_admission_profile``
    falls back to ``approved_by_id=1`` for approved+ status when not
    given an explicit user — and the test DB doesn't seed user 1.
    Pass the ``admin_user_in_db`` fixture id through.
    """
    lead_id = await create_test_lead(unit_id)
    profile = await create_admission_profile(
        lead_id,
        status="approved",
        citizen_id=_CITIZEN_ID,
        approved_by_id=admin_user_id,
    )
    token_value = secrets.token_urlsafe(32)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                models.AdmissionConfirmationToken(
                    profile_id=profile.id,
                    token=token_value,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                )
            )
    return profile.id, token_value


async def _reload_token(token_value: str) -> models.AdmissionConfirmationToken:
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == token_value
            )
        )
        return row.scalar_one()


# ============================================================================
# Cooldown ladder
# ============================================================================


class TestCooldownLadder:
    """Repeated wrong CCCD walks the 5/30/120/1440-min ladder."""

    @pytest.mark.parametrize(
        "attempts,expected_min",
        [
            (1, 5),
            (2, 5),
            (3, 30),
            (5, 120),
            (7, 1440),
            (29, 1440),
        ],
    )
    async def test_lock_until_steps_with_attempt_count(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        attempts,
        expected_min,
    ):
        """After ``attempts`` consecutive bad attempts, ``lock_until``
        is ~``expected_min`` minutes in the future and ``attempt_count``
        equals ``attempts``."""
        profile_id, token_value = await _seed_token(seed_lead_dependencies["unit_id"], admin_user_in_db["id"])

        # Walk the ladder: each call raises BadRequest because we're
        # supplying a wrong CCCD. We expect the LAST call's lock_until
        # to reflect the matching ladder rung. Between calls we have
        # to clear lock_until manually because the ladder gates ANY
        # further attempt while lock_until is in the future — the
        # whole point of the rung is to slow down the attacker — but
        # for the LADDER test we want to walk all the way through
        # without sleeping. Setting ``lock_until = NULL`` between
        # attempts is the test scaffold; production code never does.
        for i in range(attempts):
            async with AsyncSessionLocal() as session:
                # Clear sliding cooldown so the next attempt isn't
                # rejected at the lock_until gate.
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.token == token_value
                    )
                )
                tok_row = (
                    await session.execute(
                        select(models.AdmissionConfirmationToken).where(
                            models.AdmissionConfirmationToken.token == token_value
                        )
                    )
                ).scalar_one()
                tok_row.lock_until = None
                await session.commit()

            async with AsyncSessionLocal() as session:
                with pytest.raises(BadRequest):
                    await admission_service.verify_and_confirm(
                        db=session,
                        token_value=token_value,
                        last_digits=_WRONG_DIGITS,
                    )
                await session.commit()

        token = await _reload_token(token_value)
        assert token.attempt_count == attempts, (
            f"attempt_count expected {attempts}, got {token.attempt_count}"
        )
        # Last attempt set lock_until — sanity-check it's in the future
        # AND within ~1 minute of the expected rung. Allow generous
        # slack to absorb test-runner scheduling jitter.
        now = datetime.now(timezone.utc)
        assert token.lock_until is not None, "lock_until must be set after a failed attempt"
        delta_min = (token.lock_until - now).total_seconds() / 60
        assert abs(delta_min - expected_min) <= 1, (
            f"lock_until ~{expected_min}m expected, got {delta_min:.2f}m"
        )

    async def test_lock_until_blocks_until_elapsed(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """While ``lock_until > now()`` further attempts are rejected
        with the cooldown-retry message — the ladder is enforced, not
        just stamped."""
        profile_id, token_value = await _seed_token(seed_lead_dependencies["unit_id"], admin_user_in_db["id"])

        # First wrong attempt sets a 5-minute cooldown.
        async with AsyncSessionLocal() as session:
            with pytest.raises(BadRequest):
                await admission_service.verify_and_confirm(
                    db=session,
                    token_value=token_value,
                    last_digits=_WRONG_DIGITS,
                )
            await session.commit()

        # Second attempt during the cooldown — even with the CORRECT
        # digits — must be rejected.
        async with AsyncSessionLocal() as session:
            with pytest.raises(BadRequest) as exc_info:
                await admission_service.verify_and_confirm(
                    db=session,
                    token_value=token_value,
                    last_digits=_CORRECT_DIGITS,
                )
            assert "thử lại sau" in str(exc_info.value).lower()


# ============================================================================
# Hard lock at ≥30
# ============================================================================


class TestHardLock:
    """Crossing the 30-attempt threshold flips ``locked_at`` permanently."""

    async def test_30_attempts_hard_locks_with_audit_row(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """Drive attempts straight to the threshold, then verify the
        token state and audit log."""
        profile_id, token_value = await _seed_token(seed_lead_dependencies["unit_id"], admin_user_in_db["id"])

        # Pre-stage attempt_count just below the threshold so we hit
        # the hard lock on the 30th increment WITHOUT walking the full
        # 30-attempt ladder in real time. ``lock_until = None`` so each
        # service call is admitted past the cooldown gate.
        async with AsyncSessionLocal() as session:
            tok = (
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.token == token_value
                    )
                )
            ).scalar_one()
            tok.attempt_count = HARD_LOCK_THRESHOLD - 1
            tok.lock_until = None
            await session.commit()

        # The 30th failure crosses the threshold.
        async with AsyncSessionLocal() as session:
            with pytest.raises(BadRequest) as exc_info:
                await admission_service.verify_and_confirm(
                    db=session,
                    token_value=token_value,
                    last_digits=_WRONG_DIGITS,
                )
            await session.commit()
            assert "khóa" in str(exc_info.value).lower()

        token = await _reload_token(token_value)
        assert token.attempt_count >= HARD_LOCK_THRESHOLD
        assert token.locked_at is not None, "locked_at must be set at hard lock"
        assert token.lock_count == 1, (
            f"lock_count expected 1 after first hard lock, got {token.lock_count}"
        )

        # Audit row must persist regardless of the BadRequest rollback —
        # the in-txn audit is committed when the test session.commit()
        # above settles. Probe a fresh session to read it back.
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(models.EntityAuditLog).where(
                        models.EntityAuditLog.entity_type
                        == "AdmissionConfirmationToken",
                        models.EntityAuditLog.entity_id == token.id,
                        models.EntityAuditLog.action == "confirmation_hard_locked",
                    )
                )
            ).scalars().all()
            assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}"
            assert rows[0].changes["lock_count"]["new"] == 1

    async def test_hard_locked_token_cannot_be_used_after(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """Once locked_at is set, even the correct CCCD is refused —
        applicant must request support to unlock."""
        profile_id, token_value = await _seed_token(seed_lead_dependencies["unit_id"], admin_user_in_db["id"])

        async with AsyncSessionLocal() as session:
            tok = (
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.token == token_value
                    )
                )
            ).scalar_one()
            tok.locked_at = datetime.now(timezone.utc)
            tok.lock_count = 1
            await session.commit()

        async with AsyncSessionLocal() as session:
            with pytest.raises(BadRequest) as exc_info:
                await admission_service.verify_and_confirm(
                    db=session,
                    token_value=token_value,
                    last_digits=_CORRECT_DIGITS,
                )
            assert "locked" in str(exc_info.value).lower()


# ============================================================================
# Cooldown elapsed → next attempt admitted
# ============================================================================


class TestCooldownElapsed:
    """After ``lock_until`` passes, the gate re-opens for the
    sliding-cooldown branch (NOT the hard-lock branch)."""

    async def test_lock_until_in_past_admits_next_attempt(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """Manually backdate ``lock_until`` to simulate cooldown
        elapsed, then a correct CCCD must succeed."""
        profile_id, token_value = await _seed_token(seed_lead_dependencies["unit_id"], admin_user_in_db["id"])

        # Stage a previously-failed token: attempts=2, cooldown
        # already elapsed.
        async with AsyncSessionLocal() as session:
            tok = (
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.token == token_value
                    )
                )
            ).scalar_one()
            tok.attempt_count = 2
            tok.lock_until = datetime.now(timezone.utc) - timedelta(minutes=1)
            await session.commit()

        # Correct digits must now succeed.
        async with AsyncSessionLocal() as session:
            profile, post_commit = await admission_service.verify_and_confirm(
                db=session,
                token_value=token_value,
                last_digits=_CORRECT_DIGITS,
            )
            await session.commit()
            assert profile.status == "confirmed"

        token = await _reload_token(token_value)
        assert token.confirmed_at is not None, (
            "Successful confirm must stamp confirmed_at"
        )


# ============================================================================
# Hard-lock notification callback survives BadRequest (P2 review fix)
# ============================================================================


class TestHardLockCallback:
    """The hard-lock branch attaches a notification callback to the
    raised BadRequest. The router commits the lock + audit mutations
    on the BadRequest path, then must await the attached callback so
    operator browser/email reaches them — without this, the
    notification never enqueues and the dispatch becomes a no-op."""

    async def test_badrequest_carries_post_commit_callback(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        profile_id, token_value = await _seed_token(
            seed_lead_dependencies["unit_id"], admin_user_in_db["id"]
        )

        # Stage at threshold-1 so the next bad attempt hard-locks.
        async with AsyncSessionLocal() as session:
            tok = (
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.token == token_value
                    )
                )
            ).scalar_one()
            tok.attempt_count = HARD_LOCK_THRESHOLD - 1
            tok.lock_until = None
            await session.commit()

        # The hard-lock branch raises — assert the exception carries
        # the callback, and that awaiting it (router pattern) does not
        # raise even when no rule is enabled (default seed state).
        async with AsyncSessionLocal() as session:
            with pytest.raises(BadRequest) as exc_info:
                await admission_service.verify_and_confirm(
                    db=session,
                    token_value=token_value,
                    last_digits=_WRONG_DIGITS,
                )
            await session.commit()  # router commits on BadRequest

            callback = getattr(exc_info.value, "post_commit_callback", None)
            assert callback is not None, (
                "Hard-lock BadRequest must carry post_commit_callback "
                "for the router to await after commit"
            )

            # Awaiting must not raise even when the rule is disabled
            # (callback may be a no-op closure).
            await callback()
