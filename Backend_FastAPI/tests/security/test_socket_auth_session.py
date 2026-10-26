"""Unit tests for Socket.IO session validation hardening
(``app/socket_manager.py:revalidate_auth`` + ``_get_user_from_token``).

Reviewed invariants:
- revalidate fails CLOSED when the socket session is missing user_id/session_id
  (including a socket session shaped before F103, carrying only ``jti``),
- revalidate cross-checks the DB for the EXACT refresh_jti (not "any active
  session of the user"), so an old/revoked socket cannot ride on a new login,
- F103: that refresh_jti is RESOLVED from the socket's session row by its
  stable id (``UserSession.id``) on every run — never the jti of the handshake
  token, which /auth/refresh rotates,
- F103: connect binds the socket to the room of that stable id, and a
  targeted force_logout is emitted to exactly that room,
- a connecting token whose DB session is revoked/phantom is rejected.

Mock-based (no live Socket.IO server).
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app import socket_manager as sm

pytestmark = [pytest.mark.unit, pytest.mark.security]


def _fake_session_local(db):
    @asynccontextmanager
    async def _cm():
        yield db
    return MagicMock(side_effect=lambda: _cm())


def _fake_sio(socket_session):
    fake_sio = MagicMock()
    fake_sio.get_session = AsyncMock(return_value=socket_session)
    fake_sio.disconnect = AsyncMock()
    return fake_sio


@pytest.mark.asyncio
async def test_revalidate_missing_session_id_disconnects():
    fake_sio = _fake_sio({"user_id": 1, "session_id": None})
    with patch.object(sm, "sio", fake_sio):
        out = await sm.revalidate_auth("sid1")
    assert out == {"valid": False, "reason": "Invalid session"}
    fake_sio.disconnect.assert_awaited_once_with("sid1")


@pytest.mark.asyncio
async def test_revalidate_pre_f103_socket_session_with_jti_only_is_refused():
    """A socket session shaped before F103 (``jti``, no ``session_id``) is refused.

    Never validated through that jti: it may have rotated since the handshake.
    The DB is not even opened — there is no session row to resolve.
    """
    fake_sio = _fake_sio({"user_id": 1, "jti": "handshake-jti"})
    session_local = _fake_session_local(MagicMock())
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "AsyncSessionLocal", session_local):
        out = await sm.revalidate_auth("sid1")
    assert out == {"valid": False, "reason": "Invalid session"}
    fake_sio.disconnect.assert_awaited_once_with("sid1")
    session_local.assert_not_called()


@pytest.mark.asyncio
async def test_revalidate_missing_user_id_disconnects():
    fake_sio = _fake_sio({"user_id": None, "session_id": 7})
    with patch.object(sm, "sio", fake_sio):
        out = await sm.revalidate_auth("sid1")
    assert out == {"valid": False, "reason": "Invalid session"}
    fake_sio.disconnect.assert_awaited_once_with("sid1")


@pytest.mark.asyncio
async def test_revalidate_exact_jti_revoked_disconnects():
    """Redis says the session is valid AND the user has SOME active session, but
    the EXACT jti of THIS session has no non-revoked DB row → must disconnect."""
    fake_sio = _fake_sio({"user_id": 5, "session_id": 7})

    repo = MagicMock()
    repo.get_refresh_jti_for_share = AsyncMock(return_value="cur-jti")
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=None)  # exact jti gone

    # Redis ANSWERED "session present" (the strict read: revalidate no longer
    # reads ``session:`` through the lenient GET) → reach the blacklist read,
    # then the DB cross-check.
    session_read = AsyncMock(return_value="5")
    # Redis ANSWERED "not blacklisted" (the strict read; the lenient GET no
    # longer decides this).
    blacklist_read = AsyncMock(return_value=False)

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "redis_get_or_raise", session_read), \
            patch.object(sm, "redis_exists_or_raise", blacklist_read), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm.revalidate_auth("sid1")

    assert out == {"valid": False, "reason": "Session revoked"}
    fake_sio.disconnect.assert_awaited_once_with("sid1")
    repo.get_refresh_jti_for_share.assert_awaited_once_with(7, 5)
    session_read.assert_awaited_once_with("session:cur-jti", "auth.session")
    blacklist_read.assert_awaited_once_with("user_blacklist:5", "auth.user_blacklist")
    repo.get_by_refresh_jti_and_user.assert_awaited_once_with("cur-jti", 5)


@pytest.mark.asyncio
async def test_revalidate_exact_jti_valid_passes():
    fake_sio = _fake_sio({"user_id": 5, "session_id": 7})

    repo = MagicMock()
    repo.get_refresh_jti_for_share = AsyncMock(return_value="good-jti")
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=MagicMock())  # live row

    # Redis ANSWERED "session present" (strict read).
    session_read = AsyncMock(return_value="5")
    # Redis ANSWERED "not blacklisted".
    blacklist_read = AsyncMock(return_value=False)

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "redis_get_or_raise", session_read), \
            patch.object(sm, "redis_exists_or_raise", blacklist_read), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm.revalidate_auth("sid1")

    assert out == {"valid": True}
    fake_sio.disconnect.assert_not_awaited()
    session_read.assert_awaited_once_with("session:good-jti", "auth.session")
    blacklist_read.assert_awaited_once_with("user_blacklist:5", "auth.user_blacklist")


@pytest.mark.asyncio
async def test_revalidate_checks_current_jti_of_session_not_handshake_one():
    """F103: the jti checked is the one the session ROW carries now.

    The socket session holds a decoy ``jti`` (what connect stored before F103,
    i.e. the jti of the handshake token). Every per-jti check must run on the
    jti resolved from session row 7 — the one /auth/refresh rotated to.
    """
    fake_sio = _fake_sio({"user_id": 5, "session_id": 7, "jti": "handshake-jti"})

    repo = MagicMock()
    repo.get_refresh_jti_for_share = AsyncMock(return_value="rotated-jti")
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=MagicMock())

    session_read = AsyncMock(return_value="5")
    blacklist_read = AsyncMock(return_value=False)

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "redis_get_or_raise", session_read), \
            patch.object(sm, "redis_exists_or_raise", blacklist_read), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm.revalidate_auth("sid1")

    assert out == {"valid": True}
    fake_sio.disconnect.assert_not_awaited()
    repo.get_refresh_jti_for_share.assert_awaited_once_with(7, 5)
    session_read.assert_awaited_once_with("session:rotated-jti", "auth.session")
    repo.get_by_refresh_jti_and_user.assert_awaited_once_with("rotated-jti", 5)


@pytest.mark.asyncio
async def test_revalidate_unknown_session_row_is_refused_before_redis():
    """No row of this id for this user ⇒ ``Session revoked``, disconnected; Redis is
    never asked (there is no jti to ask about)."""
    fake_sio = _fake_sio({"user_id": 5, "session_id": 7})

    repo = MagicMock()
    repo.get_refresh_jti_for_share = AsyncMock(return_value=None)
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=MagicMock())
    session_read = AsyncMock(return_value="5")
    blacklist_read = AsyncMock(return_value=False)

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "redis_get_or_raise", session_read), \
            patch.object(sm, "redis_exists_or_raise", blacklist_read), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm.revalidate_auth("sid1")

    assert out == {"valid": False, "reason": "Session revoked"}
    fake_sio.disconnect.assert_awaited_once_with("sid1")
    session_read.assert_not_awaited()
    blacklist_read.assert_not_awaited()
    repo.get_by_refresh_jti_and_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_revalidate_session_row_unreadable_is_validation_error():
    """The DB does not answer the jti lookup ⇒ ``Validation error``, disconnected
    (fail-closed, the contract of every DB error in revalidate). Nothing passes on
    a lookup that did not happen."""
    fake_sio = _fake_sio({"user_id": 5, "session_id": 7})

    repo = MagicMock()
    repo.get_refresh_jti_for_share = AsyncMock(
        side_effect=OperationalError("SELECT", {}, Exception("injected: DB did not answer"))
    )
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=MagicMock())
    session_read = AsyncMock(return_value="5")
    blacklist_read = AsyncMock(return_value=False)

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "redis_get_or_raise", session_read), \
            patch.object(sm, "redis_exists_or_raise", blacklist_read), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm.revalidate_auth("sid1")

    assert out == {"valid": False, "reason": "Validation error"}
    fake_sio.disconnect.assert_awaited_once_with("sid1")
    session_read.assert_not_awaited()
    repo.get_by_refresh_jti_and_user.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_get_user_from_token_returns_id_of_the_live_session_row():
    """F103: connect learns the STABLE id of the live row the token's r_jti names."""
    payload = {"sub": "u", "r_jti": "jx"}
    user = MagicMock()
    user.id = 9
    row = MagicMock()
    row.id = 42
    repo = MagicMock()
    repo.get_by_refresh_jti_and_user = AsyncMock(return_value=row)

    with patch.object(sm.security, "decode_token", return_value=payload), \
            patch.object(sm, "safe_redis_get", AsyncMock(return_value="9")), \
            patch.object(sm, "redis_exists_or_raise", AsyncMock(return_value=False)), \
            patch.object(sm, "AsyncSessionLocal", _fake_session_local(MagicMock())), \
            patch("app.services.user_service.get_user_by_username",
                  AsyncMock(return_value=user)), \
            patch("app.repositories.SessionRepository", MagicMock(return_value=repo)):
        out = await sm._get_user_from_token("tok")

    assert out == sm.SocketAuth(user=user, session_id=42)


@pytest.mark.asyncio
async def test_connect_binds_socket_to_room_of_stable_session_id():
    """F103: connect saves ``session_id`` (no ``jti``) and joins that id's room."""
    user = MagicMock()
    user.id = 5
    user.username = "u"
    user.role = "officer"
    user.unit_id = None
    fake_sio = MagicMock()
    fake_sio.save_session = AsyncMock()
    fake_sio.enter_room = AsyncMock()

    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "check_rate_limit", AsyncMock(return_value=True)), \
            patch.object(
                sm, "_get_user_from_token",
                AsyncMock(return_value=sm.SocketAuth(user=user, session_id=42)),
            ):
        await sm.connect("sid1", {"REMOTE_ADDR": "unit-test-client"}, {"token": "tok"})

    fake_sio.save_session.assert_awaited_once()
    saved = fake_sio.save_session.await_args.args[1]
    assert saved["session_id"] == 42, saved
    assert "jti" not in saved, f"connect still stores a refresh jti: {saved}"
    rooms = [c.args[1] for c in fake_sio.enter_room.await_args_list]
    assert sm.session_room(42) in rooms, rooms


def test_session_room_is_keyed_by_session_id_only():
    """Two sessions never share a room; the name carries the id and nothing else."""
    assert sm.session_room(42) != sm.session_room(43)
    assert sm.session_room(42) == sm.session_room(42)
    assert "42" in sm.session_room(42)


def _one_worker_channel():
    """``force_disconnect_sessions_strict`` as ONE in-process worker runs it: the
    command reaches the real local handler (``force_disconnect_sessions``)."""
    async def _strict(sessions, **kwargs):
        await sm.force_disconnect_sessions(sessions)
        return "cmd-1"
    return AsyncMock(side_effect=_strict)


@pytest.mark.asyncio
async def test_emit_force_logout_targets_room_of_stable_session_id():
    """F103/F108: a targeted revoke reaches the room of the revoked session's id;
    the payload keeps naming the jti (unchanged client contract). The notice is
    a LOCAL emit on each worker (same websocket as the cut that follows)."""
    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock()
    fake_sio.disconnect = AsyncMock()
    fake_sio.manager.get_participants.return_value = [("sidA", "e1")]
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "force_disconnect_sessions_strict", _one_worker_channel()):
        await sm.emit_force_logout(
            user_id=5, revoked_jtis=["cur-jti"], revoked_session_ids=[42]
        )

    fake_sio.emit.assert_awaited_once_with(
        "force_logout_batch",
        {"revoked_jtis": ["cur-jti"]},
        room=sm.session_room(42),
        ignore_queue=True,
    )
    fake_sio.manager.get_participants.assert_called_once_with("/", sm.session_room(42))


@pytest.mark.asyncio
async def test_emit_force_logout_unpaired_jti_is_not_widened_to_user():
    """A targeted revoke without its session id is a caller bug: nothing is
    emitted — above all not to ``user_room_{id}``, which would log out the
    user's OTHER, live sessions — and nothing is disconnected."""
    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock()
    strict_sessions = AsyncMock(return_value="cmd")
    strict_user = AsyncMock(return_value="cmd")
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "force_disconnect_sessions_strict", strict_sessions), \
            patch.object(sm, "force_disconnect_user_strict", strict_user):
        await sm.emit_force_logout(user_id=5, revoked_jtis=["cur-jti"])

    fake_sio.emit.assert_not_awaited()
    strict_sessions.assert_not_awaited()
    strict_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_force_logout_enforces_server_cut_of_revoked_sessions():
    """F108: a targeted revoke is ENFORCED through the ACK-confirmed session
    command — exactly the revoked (session id, jti) pairs; never the user-wide
    command, never only a queued event the client may ignore."""
    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock()
    strict_sessions = AsyncMock(return_value="cmd")
    strict_user = AsyncMock(return_value="cmd")
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "force_disconnect_sessions_strict", strict_sessions), \
            patch.object(sm, "force_disconnect_user_strict", strict_user):
        await sm.emit_force_logout(
            user_id=5, revoked_jtis=["j1", "j2"], revoked_session_ids=[41, 42]
        )

    strict_sessions.assert_awaited_once_with([(41, "j1"), (42, "j2")])
    strict_user.assert_not_awaited()
    fake_sio.emit.assert_not_awaited()  # confirmed ⇒ no queued fallback notice


@pytest.mark.asyncio
async def test_emit_force_logout_unconfirmed_cut_is_never_reported_done():
    """F108: the session command not ACKed (here: TimeoutError) ⇒ logged as NOT
    confirmed, never as confirmed; the handler does not raise (the revoke is
    already committed and stays the source of truth)."""
    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock()
    fake_log = MagicMock()
    strict_sessions = AsyncMock(side_effect=TimeoutError("w2 did not ACK"))
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "log", fake_log), \
            patch.object(sm, "force_disconnect_sessions_strict", strict_sessions):
        await sm.emit_force_logout(
            user_id=5, revoked_jtis=["cur-jti"], revoked_session_ids=[42]
        )

    actions = [c.kwargs.get("action") for c in fake_log.error.call_args_list]
    assert "socket.session_disconnect_unconfirmed" in actions, fake_log.error.call_args_list
    claimed = [
        c for c in fake_log.info.call_args_list
        if c.kwargs.get("action") == "socket.session_disconnect_confirmed"
    ]
    assert claimed == [], f"an unconfirmed cut was reported as done: {claimed}"


@pytest.mark.asyncio
async def test_emit_force_logout_all_sessions_cuts_whole_user_with_notice():
    """``revoked_jtis=[]`` (invalidate_all_sessions, post-commit) keeps meaning ALL
    sessions — and is ENFORCED: one ACK-confirmed USER command with ``notify``
    (each worker tells the user's sockets, then cuts them); never the session
    command; no queued notice once confirmed."""
    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock()
    strict_user = AsyncMock(return_value="cmd")
    strict_sessions = AsyncMock(return_value="cmd")
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "force_disconnect_user_strict", strict_user), \
            patch.object(sm, "force_disconnect_sessions_strict", strict_sessions):
        await sm.emit_force_logout(user_id=5, revoked_jtis=[], reason="Password changed")

    strict_user.assert_awaited_once_with(5, notify=True)
    strict_sessions.assert_not_awaited()
    fake_sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_force_logout_all_unconfirmed_is_never_reported_done():
    """Revoke-ALL whose user command is not ACKed ⇒ logged NOT confirmed, never
    confirmed; still ANNOUNCED through the queue (advisory); no raise."""
    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock()
    fake_log = MagicMock()
    strict_user = AsyncMock(side_effect=TimeoutError("w2 did not ACK"))
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "log", fake_log), \
            patch.object(sm, "force_disconnect_user_strict", strict_user):
        await sm.emit_force_logout(user_id=5, revoked_jtis=[], reason="Password changed")

    actions = [c.kwargs.get("action") for c in fake_log.error.call_args_list]
    assert "socket.user_disconnect_unconfirmed" in actions, fake_log.error.call_args_list
    claimed = [
        c for c in fake_log.info.call_args_list
        if c.kwargs.get("action") == "socket.user_disconnect_confirmed"
    ]
    assert claimed == [], f"an unconfirmed cut was reported as done: {claimed}"
    fake_sio.emit.assert_awaited_once_with(
        "force_logout_batch", {"revoked_jtis": []}, room="user_room_5"
    )
