"""End-to-end tests for the inactive-account lockdown (security hotfix).

Verifies the two layers:
- (A) token-issuance gate: login / verify-mfa / refresh refuse a non-active
  account (generic 401, no lockout side effects), with the authoritative
  re-check in _complete_login_flow closing the deactivate↔mint race;
- (B) deactivation revokes live sessions: an admin status change to a non-active
  value kills existing access tokens immediately (DB-authoritative session
  check), is fail-closed, and does NOT reactivate via change-password.

Also covers the Redis/DB session desync (stale + phantom) that previously let an
old token resurrect.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app import models, security
from app.database import AsyncSessionLocal, safe_redis_get
from app.main import fastapi_app
from app.security import get_password_hash
from app.services import user_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration, pytest.mark.security]

NON_ACTIVE = ["inactive", "pending", "banned"]
PWD = "TestPassword123!"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _seed_user(username, *, status="active", role="user"):
    async with AsyncSessionLocal() as s:
        u = models.User(
            username=username,
            email=f"{username}@test.local",
            password_hash=get_password_hash(PWD),
            role=role,
            status=status,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


async def _set_status(user_id, status):
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(models.User).where(models.User.id == user_id).values(status=status)
        )
        await s.commit()


async def _get_status(user_id):
    async with AsyncSessionLocal() as s:
        u = await s.get(models.User, user_id)
        return u.status


def _bare_client():
    return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test")


async def _login(pc, username, password=PWD):
    """Login on the given client; returns the response (cookies land on pc)."""
    return await pc.post(
        "/api/auth/login", data={"username": username, "password": password}
    )


# --------------------------------------------------------------------------- #
# (A) Token-issuance gate
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", NON_ACTIVE)
async def test_login_non_active_rejected_generic_401(client: AsyncClient, status):
    uid = await _seed_user(f"login_gate_{status}", status=status)
    assert uid
    res = await _login(client, f"login_gate_{status}")
    assert res.status_code == 401
    body = res.text.lower()
    # Generic message — must not leak account state ("inactive"/"banned").
    assert "inactive" not in body and "banned" not in body
    assert "access_token" not in res.cookies


async def test_login_inactive_no_mfa_token(client: AsyncClient):
    await _seed_user("login_gate_nomfa", status="inactive")
    res = await _login(client, "login_gate_nomfa")
    assert res.status_code == 401
    assert "mfa_token" not in res.text and "mfa_required" not in res.text


async def test_refresh_non_active_401_not_500_and_no_counter(client: AsyncClient):
    uid = await _seed_user("refresh_gate", status="active")
    async with _bare_client() as pc:
        r = await _login(pc, "refresh_gate")
        assert r.status_code == 200
        await _set_status(uid, "inactive")
        rr = await pc.post("/api/auth/refresh")
    assert rr.status_code == 401  # NOT 500
    # legitimate deny must not trip the refresh-abuse counter
    assert await safe_redis_get("refresh_fail:refresh_gate") in (None, "0")


async def test_tang_a_race_deactivate_after_authenticate(
    client: AsyncClient, monkeypatch
):
    """Account is active when authenticate_user returns (Tầng B early gate sees a
    stale active object), but flipped to inactive before the token is minted.
    _complete_login_flow's authoritative db.refresh must catch it → 401."""
    await _seed_user("race_gate", status="active")
    orig = user_service.authenticate_user

    async def fake_auth(db, username, password):
        user = await orig(db, username=username, password=password)
        await _set_status(user.id, "inactive")  # flip DB after returning stale obj
        return user

    monkeypatch.setattr(user_service, "authenticate_user", fake_auth)
    res = await _login(client, "race_gate")
    assert res.status_code == 401
    assert "access_token" not in res.cookies


# --------------------------------------------------------------------------- #
# (B) Deactivation revokes live sessions
# --------------------------------------------------------------------------- #
async def test_single_deactivate_kills_existing_token(
    client: AsyncClient, admin_token_headers: dict
):
    uid = await _seed_user("revoke_single", status="active")
    async with _bare_client() as pc:
        r = await _login(pc, "revoke_single")
        assert r.status_code == 200
        token = pc.cookies.get("access_token")
        # token works before deactivation
        ok = await pc.get("/api/auth/check-status")
        assert ok.status_code == 200

        res = await client.put(
            f"/api/admin/users/{uid}",
            data={"status": "inactive"},
            headers=admin_token_headers,
        )
        assert res.status_code == 200, res.text

        # old token must now be rejected immediately
        async with _bare_client() as probe:
            probe.cookies.set("access_token", token)
            gone = await probe.get("/api/auth/check-status")
        assert gone.status_code == 401


async def test_single_deactivate_fail_closed_on_revoke_error(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    uid = await _seed_user("revoke_failclosed", status="active")

    async def boom(*a, **k):
        raise RuntimeError("revoke exploded")

    monkeypatch.setattr(user_service, "invalidate_all_sessions", boom)
    res = await client.put(
        f"/api/admin/users/{uid}",
        data={"status": "inactive"},
        headers=admin_token_headers,
    )
    assert res.status_code == 500
    # fail-closed: status must NOT have changed
    assert await _get_status(uid) == "active"


async def test_single_deactivate_fail_closed_on_disconnect_timeout(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    """An ACK timeout from the force-disconnect must roll back the whole change."""
    import app.socket_manager as sm

    uid = await _seed_user("revoke_dc_timeout", status="active")

    async def boom(*a, **k):
        raise TimeoutError("ack timeout")

    monkeypatch.setattr(sm, "force_disconnect_user_strict", boom)
    res = await client.put(
        f"/api/admin/users/{uid}",
        data={"status": "inactive"},
        headers=admin_token_headers,
    )
    assert res.status_code == 500
    assert await _get_status(uid) == "active"


async def test_bulk_deactivate_kills_existing_token(
    client: AsyncClient, admin_token_headers: dict
):
    uid = await _seed_user("revoke_bulk", status="active")
    async with _bare_client() as pc:
        await _login(pc, "revoke_bulk")
        token = pc.cookies.get("access_token")
        res = await client.post(
            "/api/admin/users/bulk",
            json={"action": "change_status", "user_ids": [uid], "status": "banned"},
            headers=admin_token_headers,
        )
        assert res.status_code == 200, res.text
        async with _bare_client() as probe:
            probe.cookies.set("access_token", token)
            gone = await probe.get("/api/auth/check-status")
        assert gone.status_code == 401
    assert await _get_status(uid) == "banned"


async def test_bulk_deactivate_fail_closed_on_disconnect_error(
    client: AsyncClient, admin_token_headers: dict, monkeypatch
):
    """If the batched force-disconnect fails, the bulk status change rolls back."""
    import app.socket_manager as sm

    uid = await _seed_user("revoke_bulk_failclosed", status="active")

    async def boom(*a, **k):
        raise RuntimeError("disconnect exploded")

    monkeypatch.setattr(sm, "force_disconnect_user_strict", boom)
    res = await client.post(
        "/api/admin/users/bulk",
        json={"action": "change_status", "user_ids": [uid], "status": "banned"},
        headers=admin_token_headers,
    )
    assert res.status_code == 500
    assert await _get_status(uid) == "active"  # fail-closed


async def test_verify_mfa_tang_a_race(client: AsyncClient, monkeypatch):
    """Account is active at the verify-mfa early gate and through OTP, but flipped
    to inactive before the token mints. _complete_login_flow (Tầng A) must 401."""
    from app.services import mfa_service

    uid = await _seed_user("mfa_race", status="active")
    mfa_token = mfa_service.create_mfa_token(username="mfa_race", user_id=uid)

    async def fake_verify(db, user, code):
        await _set_status(user.id, "inactive")  # flip right after a "good" OTP
        return True

    monkeypatch.setattr(mfa_service, "verify_mfa_code", fake_verify)
    async with _bare_client() as pc:
        res = await pc.post(
            "/api/auth/verify-mfa",
            json={"mfa_token": mfa_token, "code": "123456"},
        )
    assert res.status_code == 401
    assert "access_token" not in res.cookies


# --------------------------------------------------------------------------- #
# (B) Redis/DB session desync — no token resurrection
# --------------------------------------------------------------------------- #
async def _jti_of(token):
    return security.decode_token(token).get("r_jti")


async def test_desync_db_revoked_redis_present_rejected(client: AsyncClient):
    await _seed_user("desync_revoked", status="active")
    async with _bare_client() as pc:
        await _login(pc, "desync_revoked")
        token = pc.cookies.get("access_token")
        jti = await _jti_of(token)
        # Revoke the DB session row but LEAVE the Redis session key in place.
        async with AsyncSessionLocal() as s:
            await s.execute(
                update(models.UserSession)
                .where(models.UserSession.refresh_jti == jti)
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await s.commit()
        gone = await pc.get("/api/auth/check-status")
    assert gone.status_code == 401  # DB cross-check rejects the stale Redis hit


async def test_phantom_redis_only_rejected(client: AsyncClient):
    await _seed_user("desync_phantom", status="active")
    async with _bare_client() as pc:
        await _login(pc, "desync_phantom")
        token = pc.cookies.get("access_token")
        jti = await _jti_of(token)
        # Delete the DB session row entirely (phantom: Redis key, no DB row).
        async with AsyncSessionLocal() as s:
            await s.execute(
                models.UserSession.__table__.delete().where(
                    models.UserSession.refresh_jti == jti
                )
            )
            await s.commit()
        gone = await pc.get("/api/auth/check-status")
    assert gone.status_code == 401


# --------------------------------------------------------------------------- #
# Recovery / contract — SYNTHETIC valid session (status flipped directly, not
# via the admin endpoint, so the session is NOT revoked and the token is valid)
# --------------------------------------------------------------------------- #
async def test_change_password_does_not_reactivate(client: AsyncClient):
    uid = await _seed_user("recover_chpwd", status="active")
    async with _bare_client() as pc:
        await _login(pc, "recover_chpwd")
        await _set_status(uid, "inactive")  # synthetic inactive, session still valid
        res = await pc.post(
            "/api/auth/change-password",
            json={"old_password": PWD, "new_password": "NewPassword456!"},
        )
    assert res.status_code == 204
    # change-password must NOT reactivate the account
    assert await _get_status(uid) == "inactive"


async def test_check_status_returns_real_status(client: AsyncClient):
    uid = await _seed_user("recover_status", status="active")
    async with _bare_client() as pc:
        await _login(pc, "recover_status")
        await _set_status(uid, "inactive")
        res = await pc.get("/api/auth/check-status")
    assert res.status_code == 200
    assert res.json()["status"] == "inactive"  # real status, not hardcoded "active"


# --------------------------------------------------------------------------- #
# No lockout side effect for a legitimate inactive deny
# --------------------------------------------------------------------------- #
async def test_inactive_login_does_not_lock_account(client: AsyncClient):
    await _seed_user("nolock_gate", status="inactive")
    for _ in range(6):
        res = await _login(client, "nolock_gate")
        assert res.status_code == 401
    from app.security.account_lockout import AccountLockoutService

    is_locked, _ttl = await AccountLockoutService.check_lockout("nolock_gate")
    assert is_locked is False


# --------------------------------------------------------------------------- #
# Login-session contract: a DB session-creation failure must fail-closed
# (STEP 4 is DB-authoritative, so a token without a DB session row is 401 on
# arrival — we must NOT mint it).
# --------------------------------------------------------------------------- #
async def test_login_fail_closed_when_db_session_creation_fails(
    client: AsyncClient, monkeypatch
):
    from app.services import session_service

    await _seed_user("login_session_fail", status="active")

    async def boom(*a, **k):
        raise RuntimeError("db session create failed")

    monkeypatch.setattr(session_service, "create_session", boom)
    async with _bare_client() as pc:
        res = await _login(pc, "login_session_fail")
    assert res.status_code == 500
    assert "access_token" not in res.cookies
