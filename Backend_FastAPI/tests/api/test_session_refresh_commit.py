"""PR1 Commit 2 anchor tests — session refresh now COMMITS the rotation
(A07/A10), plus fail-closed/no-lockout on Redis or commit failure.

Root cause fixed: /auth/refresh staged the refresh_jti rotation inside a
``begin_nested()`` savepoint but never called ``db.commit()`` → ``get_db``
closed the session and the OUTER transaction rolled back, FREEZING
``user_session.refresh_jti`` at the original value. Symptoms: is_current
never resolved ("Không thể xác định phiên hiện tại") and revoke blacklisted
the wrong (frozen) jti.

Anchors:
  1. refresh persists the rotation to the DB (refresh_jti changes,
     last_activity_at advances) — the core fix.
  2. is_current resolves after refreshes (request.state.refresh_jti /
     committed session.refresh_jti).
  3. desync (old jti valid in Redis but no DB row) → 401 force re-login,
     NOT a phantom rotation (None-FATAL self-heal).
  4. commit failure → compensate Redis to OLD → 503, no new cookie, and the
     client's still-held OLD refresh token keeps working (NO LOCKOUT).
  5. Redis-rotate failure → 503, no new cookie, old token still works.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal

LOGIN = "/api/auth/login"
REFRESH = "/api/auth/refresh"
SESSIONS = "/api/sessions"


async def _login(client: AsyncClient, user: dict):
    r = await client.post(LOGIN, data={"username": user["username"], "password": user["password"]})
    assert r.status_code == 200, r.text
    return r


async def _latest_session(user_id: int) -> models.UserSession:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(models.UserSession)
                .where(
                    models.UserSession.user_id == user_id,
                    models.UserSession.revoked_at.is_(None),
                )
                .order_by(models.UserSession.id.desc())
            )
        ).scalars().all()
    assert rows, "expected an active UserSession row after login"
    return rows[0]


@pytest.mark.asyncio
async def test_refresh_commits_rotation_to_db(client: AsyncClient, regular_user_in_db: dict):
    """The core fix: a successful refresh must PERSIST the rotated refresh_jti
    and an advanced last_activity_at — not roll them back."""
    uid = regular_user_in_db["id"]
    await _login(client, regular_user_in_db)

    before = await _latest_session(uid)
    jti_before = before.refresh_jti
    last_before = before.last_activity_at

    r = await client.post(REFRESH)
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as s:
        after = (
            await s.execute(
                select(models.UserSession).where(models.UserSession.id == before.id)
            )
        ).scalar_one()

    assert after.refresh_jti != jti_before, (
        "refresh_jti must rotate AND commit — frozen jti means the no-commit "
        "bug regressed"
    )
    assert after.last_activity_at > last_before, (
        "last_activity_at must advance on refresh (was equal to created_at "
        "while the rotation rolled back)"
    )


@pytest.mark.asyncio
async def test_is_current_resolves_after_refresh(client: AsyncClient, regular_user_in_db: dict):
    """After refreshes, GET /api/sessions must mark exactly one session
    is_current (committed refresh_jti == access-token r_jti)."""
    await _login(client, regular_user_in_db)
    assert (await client.post(REFRESH)).status_code == 200
    assert (await client.post(REFRESH)).status_code == 200

    res = await client.get(SESSIONS)
    assert res.status_code == 200, res.text
    body = res.json()
    current = [s for s in body["sessions"] if s["is_current"]]
    assert len(current) == 1, f"exactly one current session expected, got {current}"
    assert body["current_session_id"] is not None


@pytest.mark.asyncio
async def test_revoke_session_then_access_token_401(client: AsyncClient, regular_user_in_db: dict):
    """End-to-end HTTP fail-fast + revocation correctness: after a refresh,
    revoking the current session must 401 the very access token that session
    minted. Before the commit fix, session.refresh_jti was frozen at the login
    jti while the live access r_jti was the rotated jti, so revoke deleted the
    WRONG session key and the access token stayed valid. Now they match →
    deps.py session:{r_jti} check rejects the next request immediately."""
    await _login(client, regular_user_in_db)
    assert (await client.post(REFRESH)).status_code == 200

    res = await client.get(SESSIONS)
    assert res.status_code == 200, res.text
    sid = res.json()["current_session_id"]
    assert sid is not None, "current session must resolve to be revocable"

    rev = await client.delete(f"{SESSIONS}/{sid}")
    assert rev.status_code == 204, rev.text

    # The access-token cookie (r_jti = the now-revoked session) must be rejected
    # on the very next authed request — no waiting for the access TTL to lapse.
    after = await client.get(SESSIONS)
    assert after.status_code == 401, (
        f"revoked session's access token must 401 immediately; got {after.status_code}"
    )


@pytest.mark.asyncio
async def test_refresh_desync_forces_relogin_401(client: AsyncClient, regular_user_in_db: dict):
    """Old jti still valid in Redis but DB has no matching row (desync) →
    update_session_activity returns None → plain 401 (force re-login), NOT a
    rotated phantom session."""
    uid = regular_user_in_db["id"]
    await _login(client, regular_user_in_db)

    # Break the DB↔cookie link: change the row's refresh_jti so the lookup by
    # the cookie's (still-Redis-valid) jti misses → None.
    sess = await _latest_session(uid)
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(models.UserSession).where(models.UserSession.id == sess.id)
            )
        ).scalar_one()
        row.refresh_jti = "BOGUS_DESYNC_JTI"
        await s.commit()

    r = await client.post(REFRESH)
    assert r.status_code == 401, r.text
    # No new cookies were issued on the desync path.
    assert "access_token" not in r.cookies


@pytest.mark.asyncio
async def test_commit_failure_no_lockout(
    client: AsyncClient, regular_user_in_db: dict, monkeypatch
):
    """If the DB commit fails after the Redis rotate, the endpoint must
    compensate Redis back to OLD, issue NO new cookie, and 503 — so the
    client's still-held OLD refresh token keeps working (no lockout)."""
    await _login(client, regular_user_in_db)

    async def _failing_commit(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(AsyncSession, "commit", _failing_commit, raising=True)
    r = await client.post(REFRESH)
    assert r.status_code == 503, r.text
    assert "access_token" not in r.cookies, "no new cookie may be set on failure"
    assert "refresh_token" not in r.cookies

    # Undo the patch and prove the OLD refresh token still authenticates.
    monkeypatch.undo()
    r2 = await client.post(REFRESH)
    assert r2.status_code == 200, (
        "old refresh token must still work after a compensated commit failure "
        f"(no lockout); got {r2.status_code}: {r2.text}"
    )


@pytest.mark.asyncio
async def test_redis_rotate_failure_no_lockout(
    client: AsyncClient, regular_user_in_db: dict, monkeypatch
):
    """If the Redis rotate fails, the endpoint must roll back the staged DB
    change and 503 with no new cookie; the old token still works."""
    await _login(client, regular_user_in_db)

    class _BrokenPipe:
        async def __aenter__(self):
            raise RuntimeError("redis down")

        async def __aexit__(self, *exc):
            return False

    def _broken_pipeline(*args, **kwargs):
        return _BrokenPipe()

    monkeypatch.setattr("app.routers.auth.safe_redis_pipeline", _broken_pipeline)
    r = await client.post(REFRESH)
    assert r.status_code == 503, r.text
    assert "access_token" not in r.cookies

    monkeypatch.undo()
    r2 = await client.post(REFRESH)
    assert r2.status_code == 200, (
        f"old token must still work after a failed Redis rotate; got {r2.status_code}"
    )
