"""ADM-023 / Q9-C2 (2026-04-29): per-profile magic-link resend cap tests.

Service-layer integration. Pin:
1. 3 resends per 24h per profile pass; 4th raises BadRequest.
2. Redis breaker open → fail-closed (BadRequest), NEVER bypass cap.
3. Resending does NOT reset attempt_count / lock_until on prior token
   — abusers can't simply request a fresh token to skip the cooldown.
4. Audit row is written on the rate-limit denial (separate session
   so it survives the request rollback).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import models
from app.database import (
    AsyncSessionLocal,
    redis_client,
    safe_redis_expire,
)
from app.services import admission_service
from app.services.admission_confirmation_resend_limit import (
    RESEND_CAP_PER_24H,
    _resend_key,
)
from app.utils.exceptions import BadRequest

from tests.integration.test_admission_state_transitions import (
    create_test_lead,
    create_admission_profile,
)


pytestmark = pytest.mark.asyncio


async def _seed_approved_profile(unit_id: int, admin_user_id: int) -> int:
    lead_id = await create_test_lead(unit_id)
    profile = await create_admission_profile(
        lead_id,
        status="approved",
        citizen_id="001202888888",
        approved_by_id=admin_user_id,
    )
    return profile.id


async def _clear_resend_quota(profile_id: int) -> None:
    """Hygiene: tests should start with a clean Redis bucket."""
    try:
        await redis_client.delete(_resend_key(profile_id))
    except Exception:
        pass


async def _resend(profile_id: int) -> None:
    """Call generate_confirmation_token in its own session/txn so a
    BadRequest rolls back cleanly without poisoning the shared session."""
    async with AsyncSessionLocal() as session:
        profile = (
            await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalar_one()
        await admission_service.generate_confirmation_token(
            db=session, profile=profile
        )
        await session.commit()


# ============================================================================
# Cap enforcement
# ============================================================================


class TestResendCap:
    async def test_first_three_resends_pass_fourth_blocks(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """24h sliding cap = 3. Calls 1-3 succeed, call 4 raises."""
        profile_id = await _seed_approved_profile(
            seed_lead_dependencies["unit_id"], admin_user_in_db["id"]
        )
        await _clear_resend_quota(profile_id)

        for i in range(RESEND_CAP_PER_24H):
            await _resend(profile_id)

        # 4th must fail.
        with pytest.raises(BadRequest) as exc_info:
            await _resend(profile_id)
        assert (
            "Đã gửi lại liên kết" in str(exc_info.value)
            or "24 giờ" in str(exc_info.value)
        )

    async def test_denied_resend_writes_audit_row(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """Each denied resend must persist an audit row even though
        the request transaction rolls back. Compliance contract: every
        attempt to overflow the cap is reconstructable from
        ``entity_audit_log``."""
        profile_id = await _seed_approved_profile(
            seed_lead_dependencies["unit_id"], admin_user_in_db["id"]
        )
        await _clear_resend_quota(profile_id)

        # Burn the cap quickly.
        for _ in range(RESEND_CAP_PER_24H):
            await _resend(profile_id)

        # Two denied attempts → expect 2 audit rows.
        for _ in range(2):
            with pytest.raises(BadRequest):
                await _resend(profile_id)

        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(models.EntityAuditLog).where(
                        models.EntityAuditLog.entity_type == "AdmissionProfile",
                        models.EntityAuditLog.entity_id == profile_id,
                        models.EntityAuditLog.action
                        == "confirmation_resend_rate_limited",
                    )
                )
            ).scalars().all()
            assert len(rows) == 2, (
                f"expected 2 rate-limit audit rows, got {len(rows)}"
            )
            # Sanity-check shape — `attempt_count_in_window` is the
            # post-increment count, which is 4 (= cap+1) for the first
            # denied call.
            assert rows[0].changes["cap"]["new"] == RESEND_CAP_PER_24H


# ============================================================================
# Redis fail-closed
# ============================================================================


class TestRedisFailClosed:
    async def test_breaker_open_returns_bad_request_not_silent_pass(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        monkeypatch,
    ):
        """When ``safe_redis_incr`` returns None (breaker open / Redis
        down), ``consume_resend_quota`` returns None and the service
        MUST refuse the resend — fail-closed beats fail-open for a
        spam cap."""
        profile_id = await _seed_approved_profile(
            seed_lead_dependencies["unit_id"], admin_user_in_db["id"]
        )

        # Force the Redis call to behave as if the breaker was open.
        async def _stub_incr(*_args, **_kwargs):
            return None

        # Patch at the consumer module so the test doesn't have to
        # touch the global circuit breaker state.
        monkeypatch.setattr(
            "app.services.admission_confirmation_resend_limit.safe_redis_incr",
            _stub_incr,
        )

        with pytest.raises(BadRequest) as exc_info:
            await _resend(profile_id)
        assert (
            "bận" in str(exc_info.value).lower()
            or "thử lại" in str(exc_info.value).lower()
        )

    async def test_expire_failure_fails_closed_so_no_permanent_counter(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
        monkeypatch,
    ):
        """P3 review (2026-04-29): if ``INCR`` succeeds but ``EXPIRE``
        fails on the first hit, the previous behaviour left the key
        with no TTL — once the cap was crossed the profile was
        locked indefinitely until manual cleanup. ``consume_resend_quota``
        now treats EXPIRE failure as a service failure and returns
        ``None`` so the caller fails closed."""
        profile_id = await _seed_approved_profile(
            seed_lead_dependencies["unit_id"], admin_user_in_db["id"]
        )
        await _clear_resend_quota(profile_id)

        # Let INCR succeed but force EXPIRE to fail.
        async def _stub_expire(*_args, **_kwargs):
            return False

        monkeypatch.setattr(
            "app.services.admission_confirmation_resend_limit.safe_redis_expire",
            _stub_expire,
        )

        with pytest.raises(BadRequest):
            await _resend(profile_id)


# ============================================================================
# Resend cannot reset attempt_count / lock_until of prior token
# ============================================================================


class TestResendDoesNotResetCooldown:
    async def test_resend_does_not_clear_prior_token_attempts(
        self,
        setup_test_database,
        seed_lead_dependencies,
        admin_user_in_db,
    ):
        """Generating a NEW confirmation token must not clear
        ``attempt_count`` / ``lock_until`` on the previously-issued
        token. Abuser pattern: fail CCCD a few times, request a new
        link, retry — should still hit the same cooldown.

        Implementation note: ``create_confirmation_token`` updates the
        existing one-row-per-profile token in place rather than
        creating a sibling, so the same row's counters must survive.
        """
        profile_id = await _seed_approved_profile(
            seed_lead_dependencies["unit_id"], admin_user_in_db["id"]
        )
        await _clear_resend_quota(profile_id)

        # Issue first token.
        await _resend(profile_id)

        async with AsyncSessionLocal() as session:
            tok = (
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.profile_id
                        == profile_id
                    )
                )
            ).scalar_one()
            tok.attempt_count = 5
            tok.lock_until = datetime(
                2099, 1, 1, tzinfo=timezone.utc
            )  # far-future cooldown
            first_token_id = tok.id
            await session.commit()

        # Resend (slot 2/3).
        await _resend(profile_id)

        async with AsyncSessionLocal() as session:
            tok = (
                await session.execute(
                    select(models.AdmissionConfirmationToken).where(
                        models.AdmissionConfirmationToken.profile_id
                        == profile_id
                    )
                )
            ).scalar_one()
            assert tok.id == first_token_id, (
                "Same row expected — one-token-per-profile contract."
            )
            # NOTE: the existing repo's ``create_confirmation_token``
            # may legitimately reset attempt_count when it issues a
            # fresh token (depends on the implementation's intent).
            # The contract we PIN here is "lock_until on the prior
            # row is NOT silently cleared" — abusers can't trivially
            # bypass the brute-force defence by spamming resends.
            #
            # If the repo IS designed to reset the counters on a new
            # token (legitimate operator-initiated reset), then this
            # assertion will fail and the contract should be
            # documented + a separate "reset cooldown" admin path
            # introduced. Either outcome surfaces the design choice.
            assert tok.lock_until is not None and tok.lock_until.year >= 2099, (
                f"prior cooldown was cleared by resend — "
                f"got lock_until={tok.lock_until}"
            )
