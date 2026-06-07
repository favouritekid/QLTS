"""Unit tests for Socket.IO session validation hardening
(``app/socket_manager.py:revalidate_auth`` + ``_get_user_from_token``).

Reviewed invariants:
- revalidate fails CLOSED when the socket session is missing user_id/jti,
- revalidate cross-checks the DB for the EXACT refresh_jti (not "any active
  session of the user"), so an old/revoked socket cannot ride on a new login,
- a connecting token whose DB session is revoked/phantom is rejected.

Mock-based (no live Socket.IO server).
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import socket_manager as sm

pytestmark = [pytest.mark.unit, pytest.mark.security]


def _fake_session_local(db):
    @asynccontextmanager
    async def _cm():
        yield db
    return MagicMock(side_effect=lambda: _cm())


@pytest.mark.asyncio
async def test_revalidate_missing_jti_disconnects():
    fake_sio = MagicMock()
    fake_sio.get_session = AsyncMock(return_value={"user_id": 1, "jti": None})
    fake_sio.disconnect = AsyncMock()
    with patch.object(sm, "sio", fake_sio):
        out = await sm.revalidate_auth("sid1")
    assert out["valid"] is False
    fake_sio.disconnect.assert_awaited_once_with("sid1")


@pytest.mark.asyncio
async def test_revalidate_missing_user_id_disconnects():
    fake_sio = MagicMock()
    fake_sio.get_session = AsyncMock(return_value={"user_id": None, "jti": "j1"})
    fake_sio.disconnect = AsyncMock()
    with patch.object(sm, "sio", fake_sio):
        out = await sm.revalidate_auth("sid1")
    assert out["valid"] is False
    fake_sio.disconnect.assert_awaited_once_with("sid1")


@pytest.mark.asyncio
async def test_revalidate_exact_jti_revoked_disconnects():
    """Redis says the session is valid AND the user has SOME active session, but
    the EXACT jti has no non-revoked DB row → must disconnect."""
    fake_sio = MagicMock()
    fake_sio.get_session = AsyncMock(return_value={"user_id": 5, "jti": "old-jti"})
    fake_sio.disconnect = AsyncMock()

    repo = MagicMock()
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=None)  # exact jti gone

    async def _redis_get(key):
        # Redis session valid + user NOT blacklisted → reach the DB cross-check.
        return "5" if key.startswith("session:") else None

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "safe_redis_get", AsyncMock(side_effect=_redis_get)), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm.revalidate_auth("sid1")

    assert out["valid"] is False
    fake_sio.disconnect.assert_awaited_once_with("sid1")
    repo.get_by_refresh_jti_and_user.assert_awaited_once_with("old-jti", 5)


@pytest.mark.asyncio
async def test_revalidate_exact_jti_valid_passes():
    fake_sio = MagicMock()
    fake_sio.get_session = AsyncMock(return_value={"user_id": 5, "jti": "good-jti"})
    fake_sio.disconnect = AsyncMock()

    repo = MagicMock()
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=MagicMock())  # live row

    async def _redis_get(key):
        # session valid, user not blacklisted
        return "5" if key.startswith("session:") else None

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "safe_redis_get", AsyncMock(side_effect=_redis_get)), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm.revalidate_auth("sid1")

    assert out["valid"] is True
    fake_sio.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_user_from_token_db_revoked_phantom_rejected():
    """Socket CONNECT: a Redis session hit whose exact jti has no non-revoked DB
    row (stale cleanup miss / phantom) must be refused. _get_user_from_token
    converts any auth failure into ConnectionRefusedError (connect refusal)."""
    payload = {"sub": "u", "r_jti": "jx"}
    user = MagicMock()
    user.id = 9
    repo = MagicMock()
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=None)  # no live DB row

    with patch.object(sm.security, "decode_token", return_value=payload), \
            patch.object(sm, "safe_redis_get", AsyncMock(return_value="9")), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.services.user_service.get_user_by_username",
                  AsyncMock(return_value=user)), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        with pytest.raises(ConnectionRefusedError):
            await sm._get_user_from_token("tok")

    # The DB cross-check ran for the exact jti before the refusal.
    repo.get_by_refresh_jti_and_user.assert_awaited_once_with("jx", 9)
