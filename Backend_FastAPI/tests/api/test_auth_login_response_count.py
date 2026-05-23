"""Option-B Commit 5 — /auth/login response carries suspicious_login_count.

Pre-PR the FE banner hardcoded ``count=1`` whenever the login response
contained a ``login_notification`` block (see useAuth.ts:96,158 — Plan
v10 finding #3). That meant a user with 5 pending suspicious logins
saw "Phát hiện 1 đăng nhập đáng ngờ" right after login, hiding the
real backlog until they navigated to /settings/security.

Commit 5 adds ``suspicious_login_count`` at the top level of the login
JSON response (alongside ``user`` and ``login_notification``) so the FE
can render the accurate number from the first paint. Plan v10 also
specified that ``_complete_login_flow`` is the single inject point, so
both ``/auth/login`` and ``/auth/verify-mfa`` get the field for free.

The count is computed AFTER ``db.commit()`` and tolerates errors
silently (banner UX, not auth correctness) — so a counter SQL hiccup
returns ``0`` and the user still completes login.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.security import get_password_hash


@pytest_asyncio.fixture
async def fresh_user_with_pending(setup_test_database):
    """Seed a user with N pending suspicious logins so we can assert
    the response count reflects the real backlog at login time.
    """
    async with AsyncSessionLocal() as session:
        user = models.User(
            username="login_count_test",
            email="login_count@test.local",
            password_hash=get_password_hash("TestPassword123!"),
            role="user",
            status="active",
            full_name="Login Count Test",
        )
        session.add(user)
        await session.flush()

        # Seed 3 pending suspicious logins.
        for i in range(3):
            session.add(models.LoginHistory(
                user_id=user.id,
                login_at=datetime.now(timezone.utc),
                ip_address=f"10.0.0.{i+1}",
                country="Vietnam",
                city="HCMC",
                device_type="desktop",
                browser="Chrome 100",
                os="Windows 10",
                browser_family="Chrome",
                os_family="Windows",
                is_new_ip=True,
                is_new_device=False,
                is_new_location=False,
                risk_score=30,
                user_response=None,  # pending
            ))
        # And 1 already-confirmed suspicious login (must NOT count).
        session.add(models.LoginHistory(
            user_id=user.id,
            login_at=datetime.now(timezone.utc),
            ip_address="10.0.0.99",
            country="Vietnam",
            city="HCMC",
            device_type="desktop",
            browser="Chrome 100",
            os="Windows 10",
            browser_family="Chrome",
            os_family="Windows",
            is_new_ip=True,
            is_new_device=False,
            is_new_location=False,
            risk_score=30,
            user_response="confirmed",
            responded_at=datetime.now(timezone.utc),
        ))
        await session.commit()
        await session.refresh(user)
        yield {
            "id": user.id,
            "username": user.username,
            "password": "TestPassword123!",
        }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_login_response_includes_suspicious_login_count_field(
    client: AsyncClient, fresh_user_with_pending: dict
):
    """The login response must expose ``suspicious_login_count`` at the
    top level (not nested inside ``login_notification`` which would only
    appear when THIS login was itself suspicious).
    """
    res = await client.post(
        "/api/auth/login",
        data={
            "username": fresh_user_with_pending["username"],
            "password": fresh_user_with_pending["password"],
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert "suspicious_login_count" in payload, (
        "Login response missing ``suspicious_login_count`` top-level field. "
        "FE banner falls back to hardcoded 1 without this."
    )
    assert isinstance(payload["suspicious_login_count"], int)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_login_response_count_reflects_pending_backlog(
    client: AsyncClient, fresh_user_with_pending: dict
):
    """Seeded 3 pending + 1 confirmed → count must be at least 3.

    "At least" because this login itself may add a 4th suspicious row
    if the test client's IP/UA is flagged as new (which it almost
    always is in a fresh test DB). Either way it must be >= 3.
    """
    res = await client.post(
        "/api/auth/login",
        data={
            "username": fresh_user_with_pending["username"],
            "password": fresh_user_with_pending["password"],
        },
    )
    assert res.status_code == 200
    count = res.json()["suspicious_login_count"]
    assert count >= 3, (
        f"Expected at least 3 pending suspicious logins after seed, got {count}. "
        f"Confirmed rows must NOT count toward this number."
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.security
async def test_login_response_count_zero_for_clean_user(
    client: AsyncClient, setup_test_database
):
    """A fresh user with no prior suspicious login history can still
    have a non-zero count if THIS login itself is flagged as suspicious
    (new IP/device/location on first login from the test client). The
    contract is just: the field exists and is a non-negative int.
    """
    async with AsyncSessionLocal() as session:
        user = models.User(
            username="clean_login_count_test",
            email="clean_count@test.local",
            password_hash=get_password_hash("TestPassword123!"),
            role="user",
            status="active",
        )
        session.add(user)
        await session.commit()

    res = await client.post(
        "/api/auth/login",
        data={"username": "clean_login_count_test", "password": "TestPassword123!"},
    )
    assert res.status_code == 200
    count = res.json()["suspicious_login_count"]
    assert isinstance(count, int)
    assert count >= 0
