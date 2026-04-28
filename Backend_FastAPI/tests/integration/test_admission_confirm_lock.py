"""
ADM-013 — profile-first FOR UPDATE lock contract tests.

Covers the three concurrent flows that race on a single
AdmissionProfile row:

  - magic-link confirm (verify_and_confirm)
  - admin override (override_profile)
  - admin finalize (finalize_profile)

The repository's ``get_token_for_confirm`` was rewritten to lock
profile FIRST, then token, with FK re-validation. ``override_profile``
and ``finalize_profile`` issue an explicit profile lock at service
entry (reentrant w.r.t. the lock the dep acquires for HTTP callers
but documents the invariant inside the service body).

Tests run two AsyncSession instances through ``asyncio.gather`` so
the lock contract is exercised end-to-end at the service layer —
mirroring the proven pattern in
``tests/integration/test_race_condition_probe.py``. A regression in
locking shows up as either non-deterministic outcome (e.g. both
mutations succeed) or a deadlock; both are caught here.
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal
from app.repositories import AdmissionRepository

from tests.integration.test_admission_state_transitions import (
    create_test_lead,
    create_admission_profile,
)


pytestmark = pytest.mark.asyncio


CITIZEN_ID = "001202999999"  # last 4: 9999
LAST_DIGITS = "9999"


async def _seed_approved_profile_with_token(unit_id: int) -> tuple[int, str, int]:
    """Create lead + approved profile + active confirmation token.

    Returns (profile_id, token_value, version)."""
    lead_id = await create_test_lead(unit_id)
    profile = await create_admission_profile(
        lead_id, status="approved", citizen_id=CITIZEN_ID,
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

    return profile.id, token_value, profile.version


async def _fetch_user(user_id: int) -> models.User:
    async with AsyncSessionLocal() as session:
        return await session.get(models.User, user_id)


async def _final_state(profile_id: int) -> tuple[str, int]:
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(
                models.AdmissionProfile.status,
                models.AdmissionProfile.version,
            ).where(models.AdmissionProfile.id == profile_id)
        )
        return row.one()


async def _token_exists(token_value: str) -> bool:
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(models.AdmissionConfirmationToken.id).where(
                models.AdmissionConfirmationToken.token == token_value
            )
        )
        return row.scalar_one_or_none() is not None


# ============================================================================
# Repository contract
# ============================================================================


class TestRepositoryProfileFirstLock:
    """``AdmissionRepository.get_token_for_confirm`` returns a token
    whose ``profile`` attribute is the same instance the repo just
    locked, not a freshly fetched (unlocked) row."""

    async def test_get_token_for_confirm_binds_locked_profile(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        profile_id, token_value, _ = await _seed_approved_profile_with_token(unit_id)

        async with AsyncSessionLocal() as session:
            repo = AdmissionRepository(session)
            token_obj = await repo.get_token_for_confirm(token_value)

            assert token_obj is not None, "Repo must return token for valid value"
            assert token_obj.profile is not None, (
                "ADM-013: repo must wire profile relationship to the locked "
                "instance so the service does not re-fetch unlocked"
            )
            assert token_obj.profile.id == profile_id
            await session.rollback()

    async def test_get_token_for_confirm_missing_token_returns_none(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        async with AsyncSessionLocal() as session:
            repo = AdmissionRepository(session)
            assert await repo.get_token_for_confirm("nonexistent-token") is None
            await session.rollback()


# ============================================================================
# Concurrency contract — confirm vs confirm
# ============================================================================


class TestDoubleConfirm:
    """Two concurrent confirms on the same token must serialise. Exactly
    one wins; the other surfaces ``BadRequest`` (token already used)."""

    async def test_concurrent_confirm_same_token(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        profile_id, token_value, _ = await _seed_approved_profile_with_token(unit_id)

        async def run_confirm() -> tuple[str, str]:
            async with AsyncSessionLocal() as session:
                try:
                    profile, _cb = await admission_service.verify_and_confirm(
                        db=session,
                        token_value=token_value,
                        last_digits=LAST_DIGITS,
                    )
                    await session.commit()
                    return ("ok", profile.status)
                except Exception as e:
                    await session.rollback()
                    return ("err", type(e).__name__)

        results = await asyncio.gather(run_confirm(), run_confirm())

        ok = [r for r in results if r[0] == "ok"]
        err = [r for r in results if r[0] == "err"]

        assert len(ok) == 1, (
            f"Profile-first lock must let exactly one confirm succeed; "
            f"got {results}"
        )
        assert len(err) == 1, (
            f"Profile-first lock must let exactly one confirm fail; "
            f"got {results}"
        )
        assert ok[0][1] == "confirmed"
        # The losing call surfaces "already used" → BadRequest.
        assert err[0][1] in {"BadRequest"}, (
            f"Loser must surface BadRequest (token already used); "
            f"got {err[0][1]}"
        )

        final_status, _ = await _final_state(profile_id)
        assert final_status == "confirmed"


# ============================================================================
# Concurrency contract — confirm vs override
# ============================================================================


class TestConfirmVsOverride:
    """``confirm`` and ``override`` both target the approved state.
    Whichever locks the profile first wins; the loser sees a state
    that no longer permits its transition."""

    async def test_confirm_vs_override_produces_one_winner(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        profile_id, token_value, version = await _seed_approved_profile_with_token(
            unit_id
        )
        admin = await _fetch_user(admin_user_in_db["id"])

        async def run_confirm() -> tuple[str, str]:
            async with AsyncSessionLocal() as session:
                try:
                    profile, _cb = await admission_service.verify_and_confirm(
                        db=session,
                        token_value=token_value,
                        last_digits=LAST_DIGITS,
                    )
                    await session.commit()
                    return ("ok", profile.status)
                except Exception as e:
                    await session.rollback()
                    return ("err", type(e).__name__)

        async def run_override() -> tuple[str, str]:
            async with AsyncSessionLocal() as session:
                try:
                    # Re-fetch profile inside this session so the
                    # service operates on its own ORM instance — same
                    # contract as the HTTP path.
                    stmt = (
                        select(models.AdmissionProfile)
                        .where(models.AdmissionProfile.id == profile_id)
                        .options(
                            selectinload(models.AdmissionProfile.lead)
                        )
                        .with_for_update()
                    )
                    profile = (await session.execute(stmt)).scalar_one()
                    result, _cb = await admission_service.override_profile(
                        db=session,
                        profile=profile,
                        admin=admin,
                        data={
                            "version": version,
                            "reason": "ADM-013 race override reason",
                            "bypass_rules": [],
                        },
                    )
                    await session.commit()
                    return ("ok", result.status)
                except Exception as e:
                    await session.rollback()
                    return ("err", type(e).__name__)

        results = await asyncio.gather(run_confirm(), run_override())
        ok = [r for r in results if r[0] == "ok"]
        err = [r for r in results if r[0] == "err"]

        assert len(ok) == 1, (
            f"Profile lock must let exactly one of confirm+override "
            f"succeed; got {results}"
        )
        assert len(err) == 1, (
            f"The loser must fail under the same lock; got {results}"
        )
        # Winner status is whichever transition fired first.
        assert ok[0][1] in {"confirmed", "overridden"}, (
            f"Winner must land on a target state; got {ok[0][1]}"
        )
        # Loser surfaces BadRequest (state changed) or ConflictError
        # (version stale, override reads new version after lock).
        assert err[0][1] in {"BadRequest", "ConflictError"}, (
            f"Loser must surface BadRequest/ConflictError; got {err[0][1]}"
        )

        final_status, final_version = await _final_state(profile_id)
        assert final_status in {"confirmed", "overridden"}
        assert final_version == version + 1, (
            "Profile version must bump exactly once across two "
            "concurrent state transitions"
        )

    async def test_override_first_invalidates_token_before_confirm(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Override winner deletes confirmation tokens; the late confirm
        sees the token gone and surfaces ``ResourceNotFoundError``.

        Lock order is identical (profile→token), so this is a clean
        serial outcome — no deadlock, no mid-mutation visibility."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        profile_id, token_value, version = await _seed_approved_profile_with_token(
            unit_id
        )
        admin = await _fetch_user(admin_user_in_db["id"])

        # Run override first to completion.
        async with AsyncSessionLocal() as session:
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .with_for_update()
            )
            profile = (await session.execute(stmt)).scalar_one()
            await admission_service.override_profile(
                db=session,
                profile=profile,
                admin=admin,
                data={
                    "version": version,
                    "reason": "ADM-013 override deletes tokens",
                    "bypass_rules": [],
                },
            )
            await session.commit()

        # Token must be gone — override invalidates_existing_tokens.
        assert not await _token_exists(token_value), (
            "Override must purge active confirmation tokens"
        )

        # Late confirm sees the token vanished. Repo returns None →
        # service raises ResourceNotFoundError.
        async with AsyncSessionLocal() as session:
            with pytest.raises(Exception) as exc_info:
                await admission_service.verify_and_confirm(
                    db=session,
                    token_value=token_value,
                    last_digits=LAST_DIGITS,
                )
            assert type(exc_info.value).__name__ == "ResourceNotFoundError"
            await session.rollback()


# ============================================================================
# Concurrency contract — confirm-then-finalize serialise
# ============================================================================


class TestConfirmThenFinalize:
    """Confirm winner moves profile to ``confirmed``; a follow-up
    finalize must take the lock cleanly, see version+status updated,
    and either succeed (with the bumped version) or surface
    ConflictError (with stale version) — never silently lose state.
    """

    async def test_finalize_after_confirm_serialises_via_profile_lock(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        profile_id, token_value, version = await _seed_approved_profile_with_token(
            unit_id
        )
        admin = await _fetch_user(admin_user_in_db["id"])

        # Phase 1: confirm completes first.
        async with AsyncSessionLocal() as session:
            await admission_service.verify_and_confirm(
                db=session,
                token_value=token_value,
                last_digits=LAST_DIGITS,
            )
            await session.commit()

        confirmed_status, confirmed_version = await _final_state(profile_id)
        assert confirmed_status == "confirmed"
        assert confirmed_version == version + 1

        # Phase 2: finalize with stale version → ConflictError under
        # profile lock.
        async with AsyncSessionLocal() as session:
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .with_for_update()
            )
            profile = (await session.execute(stmt)).scalar_one()
            with pytest.raises(Exception) as exc_info:
                await admission_service.finalize_profile(
                    db=session,
                    profile=profile,
                    admin=admin,
                    data={"version": version},  # stale
                )
            assert type(exc_info.value).__name__ == "ConflictError"
            await session.rollback()

        # Phase 3: finalize with fresh version succeeds; profile-row
        # lock has been released between phases.
        async with AsyncSessionLocal() as session:
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
                .with_for_update()
            )
            profile = (await session.execute(stmt)).scalar_one()
            await admission_service.finalize_profile(
                db=session,
                profile=profile,
                admin=admin,
                data={"version": confirmed_version},
            )
            await session.commit()

        final_status, _ = await _final_state(profile_id)
        assert final_status == "enrolled"


# ============================================================================
# Stale-instance defense — service refreshes column values under lock
# ============================================================================


class TestStaleInstanceRefresh:
    """``_lock_admission_profile_for_write`` returns a refreshed ORM
    instance (``populate_existing=True``). A non-router caller that
    loaded ``profile`` *before* waiting on the lock — and so has
    stale ``status``/``version`` in memory — must surface a
    deterministic error after the lock acquires, not silently mutate
    against pre-lock columns.

    The setup is contrived (router deps already lock + load), but
    proves the service body's contract holds for non-router callers
    too. If a future refactor drops ``populate_existing=True`` or
    drops the rebinding in override/finalize, these tests fire.
    """

    async def test_override_refreshes_stale_instance_under_lock(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Session A loads stale profile, commits (closes read txn but
        keeps the stale instance via ``expire_on_commit=False``).
        Session B overrides + commits. Session A then calls
        ``override_profile`` with the same stale instance — the
        helper's lock+refresh must surface state/version drift, not
        silently mutate against pre-lock columns.

        The intermediate commit on Session A matters: without it,
        Session A holds a read transaction open and Session B's
        ``FOR UPDATE`` would block. We only need the stale ORM
        snapshot in memory; the txn that loaded it can close."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        profile_id, _token, version = await _seed_approved_profile_with_token(
            unit_id
        )
        admin = await _fetch_user(admin_user_in_db["id"])

        async with AsyncSessionLocal() as session_a:
            # Session A — load profile WITHOUT FOR UPDATE; it sits in
            # this session's identity map with version=N / status=approved.
            stale_stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
            )
            stale_profile = (
                await session_a.execute(stale_stmt)
            ).scalar_one()
            assert stale_profile.version == version
            assert stale_profile.status == "approved"

            # Close the read txn so Session B's FOR UPDATE doesn't
            # block. expire_on_commit=False keeps stale_profile's
            # column values addressable.
            await session_a.commit()

            # Session B — perform a real override + commit. DB row is
            # now overridden / version+1.
            async with AsyncSessionLocal() as session_b:
                lock_stmt = (
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == profile_id)
                    .options(selectinload(models.AdmissionProfile.lead))
                    .with_for_update()
                )
                profile_b = (await session_b.execute(lock_stmt)).scalar_one()
                await admission_service.override_profile(
                    db=session_b,
                    profile=profile_b,
                    admin=admin,
                    data={
                        "version": version,
                        "reason": "ADM-013 stale-instance setup",
                        "bypass_rules": [],
                    },
                )
                await session_b.commit()

            # Session A — call service with the stale instance. The
            # helper acquires the lock + repopulates columns; service
            # then sees ``status="overridden"`` and raises BadRequest
            # (state-machine: approved→overridden is the only legal
            # transition; overridden→overridden is rejected).
            with pytest.raises(Exception) as exc_info:
                await admission_service.override_profile(
                    db=session_a,
                    profile=stale_profile,
                    admin=admin,
                    data={
                        "version": version,  # stale
                        "reason": "ADM-013 stale should be rejected",
                        "bypass_rules": [],
                    },
                )
            assert type(exc_info.value).__name__ in {
                "BadRequest",
                "ConflictError",
            }, (
                f"Service must reject stale-instance override after "
                f"lock+refresh; got {type(exc_info.value).__name__}"
            )
            await session_a.rollback()

        # Final DB state must be the session-B winner only — version
        # bumps exactly once across both attempted overrides.
        final_status, final_version = await _final_state(profile_id)
        assert final_status == "overridden"
        assert final_version == version + 1, (
            "Stale-instance attempt must NOT mutate the row a second time"
        )

    async def test_finalize_refreshes_stale_instance_under_lock(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Session A loads stale approved profile, commits to release
        the read txn (stale ORM snapshot survives via
        ``expire_on_commit=False``). Session B magic-link confirms +
        commits. Session A calls ``finalize_profile`` with the stale
        version — helper's lock+refresh must surface the version
        drift as ConflictError, not silently mutate."""
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        profile_id, token_value, version = await _seed_approved_profile_with_token(
            unit_id
        )
        admin = await _fetch_user(admin_user_in_db["id"])

        async with AsyncSessionLocal() as session_a:
            stale_stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
            )
            stale_profile = (
                await session_a.execute(stale_stmt)
            ).scalar_one()

            # Release the read txn so Session B's FOR UPDATE in the
            # confirm path doesn't block. The stale ORM instance keeps
            # its column values (expire_on_commit=False).
            await session_a.commit()

            # Session B — magic-link confirm completes. DB row is now
            # version+1 / status="confirmed"; stale_profile in
            # memory still reads version=N / status="approved".
            async with AsyncSessionLocal() as session_b:
                await admission_service.verify_and_confirm(
                    db=session_b,
                    token_value=token_value,
                    last_digits=LAST_DIGITS,
                )
                await session_b.commit()

            # Session A — finalize with stale version against an
            # already-confirmed profile. Helper repopulates → service
            # sees version+1 (stale claim of N fails) and raises
            # ConflictError.
            with pytest.raises(Exception) as exc_info:
                await admission_service.finalize_profile(
                    db=session_a,
                    profile=stale_profile,
                    admin=admin,
                    data={"version": version},  # stale
                )
            assert type(exc_info.value).__name__ == "ConflictError", (
                f"Stale finalize must surface ConflictError after "
                f"lock+refresh; got {type(exc_info.value).__name__}"
            )
            await session_a.rollback()

        final_status, final_version = await _final_state(profile_id)
        assert final_status == "confirmed", (
            "Stale finalize must NOT have advanced status to enrolled"
        )
        assert final_version == version + 1, (
            "Only the session-B confirm bumps version; stale finalize "
            "must not write"
        )
