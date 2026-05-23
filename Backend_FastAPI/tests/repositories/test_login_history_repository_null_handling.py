"""Option-B Commit 3 — repository NULL-safe filters + canonical lookup.

Locks three behaviours that Commit 3 changed in
``app/repositories/login_history_repository.py``:

1. ``check_*_seen_before`` now uses ``is_distinct_from("secured")`` so
   pending rows (``user_response IS NULL``) count as "seen" history.
   Pre-fix the predicate was ``user_response != "secured"`` which
   evaluates NULL → NULL in Postgres three-valued logic, silently
   excluding the most common case and causing every pending login to
   re-flag as "new device / IP / location" forever.

2. ``check_device_seen_before`` queries by the canonical SHA-256
   ``device_fingerprint`` column (exact hash match) instead of the
   display-string columns (browser / os / device_type). This was the
   user-visible bug from the audit: pre-PR the equality check broke on
   every browser version bump, so clicking "Là tôi" never stuck.

3. New ``count_pending_suspicious(user_id)`` method exists with the
   right filter (OR of 3 anomaly flags + ``user_response IS NULL``).
   Used by ``/auth/login`` response to populate the FE banner count
   with the real number instead of a hardcoded ``1`` (Commit 5).

All tests build LoginHistory rows directly on a real (test-DB) session.
The Commit 1 migration is already part of the test-DB schema via
``Base.metadata.create_all()`` since Commit 2 added the canonical
columns to the model.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.repositories.login_history_repository import LoginHistoryRepository


# ===========================================================================
# Helper — seed a LoginHistory row with explicit anomaly flags.
# ===========================================================================


async def _seed_login(
    session,
    *,
    user_id: int,
    ip_address: str | None = "10.0.0.1",
    country: str | None = "Vietnam",
    browser: str | None = "Mobile Safari 26.4",
    os_: str | None = "iOS 18.7",
    device_type: str | None = "mobile",
    browser_family: str | None = "Mobile Safari",
    os_family: str | None = "iOS",
    device_fingerprint: str | None = None,
    user_response: str | None = None,
    is_new_ip: bool = False,
    is_new_device: bool = False,
    is_new_location: bool = False,
) -> models.LoginHistory:
    login = models.LoginHistory(
        user_id=user_id,
        login_at=datetime.now(timezone.utc),
        ip_address=ip_address,
        country=country,
        city="HCMC",
        device_type=device_type,
        browser=browser,
        os=os_,
        browser_family=browser_family,
        os_family=os_family,
        device_fingerprint=device_fingerprint,
        is_new_ip=is_new_ip,
        is_new_device=is_new_device,
        is_new_location=is_new_location,
        risk_score=0,
        user_response=user_response,
    )
    session.add(login)
    await session.flush()
    return login


@pytest_asyncio.fixture
async def seed_user(setup_test_database):
    """Create one synthetic user inside a fresh test-DB session."""
    async with AsyncSessionLocal() as session:
        user = models.User(
            username="repo_null_test",
            email="null@test.local",
            password_hash="x",
            role="user",
            status="active",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        yield user


# ===========================================================================
# 1. NULL-safe predicate — pending rows count as "seen"
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_ip_seen_before_includes_pending_row(seed_user):
    """Pending row (``user_response IS NULL``) MUST count as seen.

    Pre-fix the predicate was ``user_response != "secured"`` which is
    NULL ↔ NULL → NULL → falsy in WHERE — so the very common case (user
    hasn't reviewed the suspicious login yet) was silently excluded,
    causing the next login from the same IP to be re-flagged.
    """
    async with AsyncSessionLocal() as session:
        await _seed_login(session, user_id=seed_user.id, ip_address="1.1.1.1",
                          is_new_ip=True, user_response=None)
        await session.commit()
        repo = LoginHistoryRepository(session)
        seen = await repo.check_ip_seen_before(seed_user.id, "1.1.1.1")
    assert seen is True, "Pending row must count as IP seen — NULL-safe fix"


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_country_seen_before_includes_pending_row(seed_user):
    """Same NULL-safe semantics for country."""
    async with AsyncSessionLocal() as session:
        await _seed_login(session, user_id=seed_user.id, country="Vietnam",
                          is_new_location=True, user_response=None)
        await session.commit()
        repo = LoginHistoryRepository(session)
        seen = await repo.check_country_seen_before(seed_user.id, "Vietnam")
    assert seen is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_device_seen_before_includes_pending_row(seed_user):
    """Device check is now an exact-hash match; pending rows still count."""
    FP = "a" * 64
    async with AsyncSessionLocal() as session:
        await _seed_login(session, user_id=seed_user.id, device_fingerprint=FP,
                          is_new_device=True, user_response=None)
        await session.commit()
        repo = LoginHistoryRepository(session)
        seen = await repo.check_device_seen_before(seed_user.id, FP)
    assert seen is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_ip_excludes_secured_rows_only(seed_user):
    """Only rows where the user explicitly said "Không phải tôi"
    (user_response='secured') are excluded. Pending + confirmed both
    count as legitimate history.
    """
    async with AsyncSessionLocal() as session:
        # Only seed a 'secured' row — should NOT count as seen.
        await _seed_login(session, user_id=seed_user.id, ip_address="2.2.2.2",
                          is_new_ip=True, user_response="secured")
        await session.commit()
        repo = LoginHistoryRepository(session)
        seen = await repo.check_ip_seen_before(seed_user.id, "2.2.2.2")
    assert seen is False, "'secured' row must NOT count as IP seen"


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_ip_pending_plus_secured_still_seen(seed_user):
    """When a user has BOTH pending AND secured rows for the same IP,
    the pending row alone is enough to mark the IP as seen.
    """
    async with AsyncSessionLocal() as session:
        await _seed_login(session, user_id=seed_user.id, ip_address="3.3.3.3",
                          is_new_ip=True, user_response="secured")
        await _seed_login(session, user_id=seed_user.id, ip_address="3.3.3.3",
                          is_new_ip=True, user_response=None)
        await session.commit()
        repo = LoginHistoryRepository(session)
        seen = await repo.check_ip_seen_before(seed_user.id, "3.3.3.3")
    assert seen is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_ip_confirmed_row_counts_as_seen(seed_user):
    """'confirmed' rows (user clicked "Là tôi") absolutely count as seen."""
    async with AsyncSessionLocal() as session:
        await _seed_login(session, user_id=seed_user.id, ip_address="4.4.4.4",
                          is_new_ip=True, user_response="confirmed")
        await session.commit()
        repo = LoginHistoryRepository(session)
        seen = await repo.check_ip_seen_before(seed_user.id, "4.4.4.4")
    assert seen is True


# ===========================================================================
# 2. check_device_seen_before — canonical hash lookup
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_device_seen_before_signature_is_str(seed_user):
    """Lock the new contract: the repo accepts a canonical fingerprint
    string, not a dict of display attributes.
    """
    import inspect as _inspect
    sig = _inspect.signature(LoginHistoryRepository.check_device_seen_before)
    assert sig.parameters["device_fingerprint"].annotation is str


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_device_seen_before_misses_on_different_hash(seed_user):
    """Exact-hash match: a different fingerprint MUST NOT match an
    existing row. This is the inverse of the user-visible bug — pre-PR
    the display-string equality check matched too LOOSELY (same family
    but different version still seen as "new device" because the hash
    was version-sensitive); Commit 3's canonical hash is exact-match.
    """
    FP_A = "a" * 64
    FP_B = "b" * 64
    async with AsyncSessionLocal() as session:
        await _seed_login(session, user_id=seed_user.id, device_fingerprint=FP_A,
                          is_new_device=True, user_response=None)
        await session.commit()
        repo = LoginHistoryRepository(session)
        seen_a = await repo.check_device_seen_before(seed_user.id, FP_A)
        seen_b = await repo.check_device_seen_before(seed_user.id, FP_B)
    assert seen_a is True
    assert seen_b is False


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_device_seen_before_empty_string_treated_as_seen(seed_user):
    """Defensive: an empty / missing fingerprint short-circuits to True
    so the anomaly path doesn't false-positive when the UA parse failed.
    """
    async with AsyncSessionLocal() as session:
        repo = LoginHistoryRepository(session)
        seen = await repo.check_device_seen_before(seed_user.id, "")
    assert seen is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_check_device_seen_before_user_scoped(seed_user):
    """Fingerprint match is scoped to the user. Another user's identical
    fingerprint hash MUST NOT leak as "seen" for this user (and in
    practice ``generate_device_fingerprint`` mixes user_id into the hash
    so collisions across users are already unlikely, but the repo's
    user_id filter is the canonical guarantee).
    """
    FP = "c" * 64
    async with AsyncSessionLocal() as session:
        # Seed another user with same fingerprint
        other = models.User(
            username="other_repo_null_test",
            email="other@test.local",
            password_hash="x",
            role="user",
            status="active",
        )
        session.add(other)
        await session.flush()
        await _seed_login(session, user_id=other.id, device_fingerprint=FP,
                          is_new_device=True, user_response=None)
        await session.commit()

        repo = LoginHistoryRepository(session)
        seen_for_seed = await repo.check_device_seen_before(seed_user.id, FP)
        seen_for_other = await repo.check_device_seen_before(other.id, FP)

    assert seen_for_seed is False, "Cross-user fingerprint leak — user_id filter broken"
    assert seen_for_other is True


# ===========================================================================
# 3. count_pending_suspicious — banner count source
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.security
async def test_count_pending_suspicious_zero_when_no_logins(seed_user):
    async with AsyncSessionLocal() as session:
        repo = LoginHistoryRepository(session)
        count = await repo.count_pending_suspicious(seed_user.id)
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.security
async def test_count_pending_suspicious_counts_each_anomaly_flag(seed_user):
    """``is_suspicious`` is the OR of (is_new_ip, is_new_device,
    is_new_location). The count must match that OR + pending filter.
    """
    async with AsyncSessionLocal() as session:
        # Row 1: only new_ip — pending → counts
        await _seed_login(session, user_id=seed_user.id, is_new_ip=True, user_response=None)
        # Row 2: only new_device — pending → counts
        await _seed_login(session, user_id=seed_user.id, is_new_device=True, user_response=None)
        # Row 3: only new_location — pending → counts
        await _seed_login(session, user_id=seed_user.id, is_new_location=True, user_response=None)
        # Row 4: all flags False — NOT suspicious → does NOT count
        await _seed_login(session, user_id=seed_user.id, user_response=None)
        await session.commit()
        repo = LoginHistoryRepository(session)
        count = await repo.count_pending_suspicious(seed_user.id)
    assert count == 3, f"Expected 3 suspicious-pending, got {count}"


@pytest.mark.asyncio
@pytest.mark.security
async def test_count_pending_suspicious_excludes_confirmed_and_secured(seed_user):
    """Once the user has responded (confirmed OR secured) the row stops
    counting toward the banner — the banner only shows OPEN reviews.
    """
    async with AsyncSessionLocal() as session:
        # Pending: counts
        await _seed_login(session, user_id=seed_user.id, is_new_ip=True, user_response=None)
        # Confirmed: does NOT count
        await _seed_login(session, user_id=seed_user.id, is_new_ip=True, user_response="confirmed")
        # Secured: does NOT count
        await _seed_login(session, user_id=seed_user.id, is_new_ip=True, user_response="secured")
        await session.commit()
        repo = LoginHistoryRepository(session)
        count = await repo.count_pending_suspicious(seed_user.id)
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.security
async def test_count_pending_suspicious_user_scoped(seed_user):
    """Count is per-user; another user's suspicious-pending rows MUST
    NOT bleed into this user's banner.
    """
    async with AsyncSessionLocal() as session:
        other = models.User(
            username="other_count_test",
            email="other_count@test.local",
            password_hash="x",
            role="user",
            status="active",
        )
        session.add(other)
        await session.flush()

        await _seed_login(session, user_id=seed_user.id, is_new_ip=True, user_response=None)
        await _seed_login(session, user_id=other.id, is_new_ip=True, user_response=None)
        await _seed_login(session, user_id=other.id, is_new_device=True, user_response=None)
        await session.commit()

        repo = LoginHistoryRepository(session)
        seed_count = await repo.count_pending_suspicious(seed_user.id)
        other_count = await repo.count_pending_suspicious(other.id)

    assert seed_count == 1
    assert other_count == 2
