"""Option-B Commit 4 — TrustedDevice canonical columns + repo signature.

Locks the three behaviours added in this commit:

1. ``TrustedDevice`` model declares ``browser_family``, ``os_family``,
   ``device_type`` columns. They're nullable so legacy fixtures keep
   working, but ``trust_device`` populates them on every new row.

2. ``trust_device`` accepts ``browser_family`` / ``os_family`` /
   ``device_type`` kwargs and persists them. The fingerprint hash on
   the row stays the canonical SHA-256, but the row now also carries
   the family triple that went into the hash — useful for forensic
   queries and for the ``/settings/security`` UI to show stable family
   labels.

3. Self-heal: when the row already exists (UPSERT on the unique
   ``(user_id, device_fingerprint)`` constraint), ``trust_device``
   refreshes timestamps + display + IP as before AND backfills the
   canonical columns IF they were NULL. Existing canonical values are
   NOT overwritten, so a row whose ``device_type`` was set by the
   sl20260524 migration's Step 5b fallback heuristic keeps that value
   even if the next ``trust_device`` call would have chosen a different
   one.

All tests run against the real test DB via the existing
``AsyncSessionLocal`` fixture chain; no mocks for the model interactions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.repositories.trusted_device_repository import TrustedDeviceRepository


@pytest_asyncio.fixture
async def seed_user(setup_test_database):
    async with AsyncSessionLocal() as session:
        user = models.User(
            username="trust_repo_test",
            email="trust_repo@test.local",
            password_hash="x",
            role="user",
            status="active",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        yield user


# ===========================================================================
# 1. Model schema lock
# ===========================================================================


def test_model_has_canonical_columns():
    """``TrustedDevice`` MUST declare browser_family, os_family,
    device_type as columns. Commit 1 migration added them in the DB;
    this assertion locks the SQLAlchemy declaration so a refactor that
    drops them is caught at import time by any test of this file.
    """
    cols = {c.name for c in models.TrustedDevice.__table__.columns}
    for name in ("browser_family", "os_family", "device_type"):
        assert name in cols, (
            f"TrustedDevice.{name} column missing — Option-B Commit 4 "
            "model declaration regressed."
        )


# ===========================================================================
# 2. trust_device signature
# ===========================================================================


def test_trust_device_signature_accepts_canonical_kwargs():
    """Signature lock — repo.trust_device must accept the three canonical
    kwargs. Default ``None`` so legacy callers (e.g., third-party scripts
    or future fixtures) don't break.
    """
    import inspect as _inspect
    sig = _inspect.signature(TrustedDeviceRepository.trust_device)
    for kw in ("browser_family", "os_family", "device_type"):
        assert kw in sig.parameters, f"trust_device missing kwarg {kw!r}"
        assert sig.parameters[kw].default is None, (
            f"trust_device kwarg {kw!r} must default to None for back-compat"
        )


# ===========================================================================
# 3. Create new row populates canonical columns
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.security
async def test_trust_device_create_persists_canonical_columns(seed_user):
    """First-time trust on a fingerprint → new row with display +
    canonical fields both set.
    """
    FP = "d" * 64
    async with AsyncSessionLocal() as session:
        repo = TrustedDeviceRepository(session)
        td = await repo.trust_device(
            user_id=seed_user.id,
            device_fingerprint=FP,
            name="Mobile Safari on iOS",
            browser="Mobile Safari 26.4",
            os="iOS 18.7",
            ip_address="10.0.0.16",
            browser_family="Mobile Safari",
            os_family="iOS",
            device_type="mobile",
        )
        await session.commit()
        await session.refresh(td)

    assert td.browser == "Mobile Safari 26.4"
    assert td.os == "iOS 18.7"
    assert td.browser_family == "Mobile Safari"
    assert td.os_family == "iOS"
    assert td.device_type == "mobile"
    assert td.device_fingerprint == FP


# ===========================================================================
# 4. Self-heal: existing row with NULL canonical columns
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.security
async def test_trust_device_self_heals_null_canonical_columns(seed_user):
    """When the existing row has NULL canonical columns (e.g., created
    pre-Commit 4 or via a partial fixture), the next ``trust_device``
    call MUST populate them. Display ``browser`` / ``os`` are NOT
    overwritten — display history stays as the user first saw it.
    """
    FP = "e" * 64
    async with AsyncSessionLocal() as session:
        # Manually seed a row with display only — simulates pre-PR data
        # or a row whose Step 5b heuristic backfill failed.
        td_initial = models.TrustedDevice(
            user_id=seed_user.id,
            device_fingerprint=FP,
            name="Mobile Safari 16.3 on iOS 16.3",
            browser="Mobile Safari 16.3",
            os="iOS 16.3",
            first_seen_at=datetime.now(timezone.utc) - timedelta(days=30),
            trusted_at=datetime.now(timezone.utc) - timedelta(days=30),
            last_used_at=datetime.now(timezone.utc) - timedelta(days=5),
            trusted_from_ip="10.0.0.16",
            # All canonical columns NULL on purpose
        )
        session.add(td_initial)
        await session.commit()

        # User logs in again → confirm_login eventually calls trust_device
        # with the freshly-parsed canonical kwargs.
        repo = TrustedDeviceRepository(session)
        td_updated = await repo.trust_device(
            user_id=seed_user.id,
            device_fingerprint=FP,
            name="Mobile Safari on iOS",
            browser="Mobile Safari 16.3",  # display unchanged
            os="iOS 16.3",
            ip_address="10.0.0.99",
            browser_family="Mobile Safari",
            os_family="iOS",
            device_type="mobile",
        )
        await session.commit()
        await session.refresh(td_updated)

    assert td_updated.id == td_initial.id, "Should UPSERT, not create new row"
    # Canonical columns now populated (self-heal):
    assert td_updated.browser_family == "Mobile Safari"
    assert td_updated.os_family == "iOS"
    assert td_updated.device_type == "mobile"
    # Display unchanged (kept as user first saw):
    assert td_updated.browser == "Mobile Safari 16.3"
    assert td_updated.os == "iOS 16.3"
    # Refresh timestamp + IP / name updated:
    assert td_updated.trusted_from_ip == "10.0.0.99"
    assert td_updated.name == "Mobile Safari on iOS"


@pytest.mark.asyncio
@pytest.mark.security
async def test_trust_device_does_not_overwrite_existing_canonical(seed_user):
    """When the existing row already has canonical columns set (e.g.,
    by the sl20260524 migration's Step 5b heuristic), a subsequent
    ``trust_device`` call MUST NOT overwrite them. This protects against
    a stale UA parse silently flipping a row from "mobile" to "desktop".
    """
    FP = "f" * 64
    async with AsyncSessionLocal() as session:
        td_initial = models.TrustedDevice(
            user_id=seed_user.id,
            device_fingerprint=FP,
            name="Existing Trust",
            browser="Chrome 100",
            os="Windows 10",
            browser_family="Chrome",
            os_family="Windows",
            device_type="desktop",  # ← migration-set value to protect
            first_seen_at=datetime.now(timezone.utc),
            trusted_at=datetime.now(timezone.utc),
            last_used_at=datetime.now(timezone.utc),
            trusted_from_ip="10.0.0.1",
        )
        session.add(td_initial)
        await session.commit()

        repo = TrustedDeviceRepository(session)
        td_updated = await repo.trust_device(
            user_id=seed_user.id,
            device_fingerprint=FP,
            name="Should not affect canonical",
            browser="Chrome 100",
            os="Windows 10",
            ip_address="10.0.0.2",
            # Hypothetically wrong canonical — should be IGNORED because
            # existing row already has values.
            browser_family="WRONG",
            os_family="WRONG",
            device_type="mobile",
        )
        await session.commit()
        await session.refresh(td_updated)

    assert td_updated.browser_family == "Chrome"  # NOT "WRONG"
    assert td_updated.os_family == "Windows"
    assert td_updated.device_type == "desktop"  # NOT "mobile"


# ===========================================================================
# 5. Caller alignment — confirm_login forwards canonical kwargs
# ===========================================================================


def test_confirm_login_forwards_canonical_kwargs():
    """Static source contract: ``confirm_login`` must pass the canonical
    triple to ``trust_device``. Without this the service layer would
    create rows with NULL canonical columns even after Commit 4 lands,
    defeating the self-heal goal for fresh trusts.
    """
    import inspect
    import app.services.login_history_service as svc

    src = inspect.getsource(svc.confirm_login)
    assert "browser_family=browser_family" in src, (
        "confirm_login must forward browser_family to trust_device"
    )
    assert "os_family=os_family" in src
    assert "device_type=device_type" in src
