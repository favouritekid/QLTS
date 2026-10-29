# tests/security/test_password_reset_enforced.py
# -*- coding: utf-8 -*-
"""F128 / F131 / F133 / F134 — ``password_reset_required`` is ENFORCED.

Integration: every HTTP case goes through the real ASGI app and router
(``client`` fixture) — the (method, route) allowlist is matched on the route
FastAPI actually resolved, never on a mocked ``request.scope``. Socket cases
connect a real Socket.IO client to a real uvicorn (``test_server``).

What is locked here:
- HTTP gate at the ROOT (``get_current_user``): a flagged user gets 403
  ``PASSWORD_CHANGE_REQUIRED`` on business routes reached through
  ``get_current_active_user``, through IDOR dependencies that authenticate
  straight at the root, and on the root's own self-service routes;
- the allowlist is exactly two routes and both stay usable;
- ``confirm-login`` ("that was me") cannot lift the flag;
- full recovery: 403 → change password → the OLD token is refused → log in
  again → business API 200;
- F133: a flagged admin WITHOUT MFA (MFA enforced) still reads ``/users/me``,
  changes the password FIRST, then enrols MFA; ``/users/me`` keeps its MFA gate
  for unflagged users and its ``status`` gate always;
- Socket.IO: S1 connect refused · S2 secure-account notifies then cuts the
  live socket · S3 revalidate notifies then cuts · F134 the watchdog cuts what
  S2 left (cut not ACK-confirmed, client never revalidates), keeps sockets on a
  short DB outage and cuts them all past the bound.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app import models
from app import socket_manager as sm
from app.config import settings
from app.core import password_change as pc
from app.database import AsyncSessionLocal
from app.main import fastapi_app

try:
    import socketio

    SOCKETIO_AVAILABLE = True
except ImportError:  # pragma: no cover - python-socketio ships with the app
    SOCKETIO_AVAILABLE = False
    socketio = None

# asyncio_mode = auto (pytest.ini): async cases need no mark, sync ones must not carry it.
pytestmark = [pytest.mark.integration, pytest.mark.security]

LOGIN_URL = "/api/auth/login"
ME_URL = "/api/users/me"
CHANGE_PASSWORD_URL = "/api/auth/change-password"
LEADS_URL = "/api/leads"
MFA_SETUP_URL = "/api/auth/mfa/setup"
MFA_ENABLE_URL = "/api/auth/mfa/enable"
SECURE_ACCOUNT_URL = "/api/security/secure-account"
CONFIRM_LOGIN_URL = "/api/security/confirm-login"
NEW_PASSWORD = "MatKhauMoi@2026Xy"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture(autouse=True)
async def _redis_sach(clear_redis_keys):
    """Flush FakeRedis BEFORE the app lifespan registers its socket worker
    (autouse ⇒ set up first, torn down last): change-password writes
    ``user_blacklist:{id}`` with a 30-day ttl, and ids repeat across tests."""
    yield


async def _login(client, username: str, password: str) -> str:
    client.cookies.clear()
    try:
        res = await client.post(
            LOGIN_URL, data={"username": username, "password": password}
        )
    finally:
        client.cookies.clear()
    assert res.status_code == 200, res.text
    token = res.cookies.get("access_token")
    assert token, "login must set the access_token cookie"
    return token


async def _call(client, method: str, url: str, token: str, **kwargs):
    """Bearer only: no cookie of an earlier response may stand in for it."""
    client.cookies.clear()
    try:
        return await client.request(
            method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
    finally:
        client.cookies.clear()


async def _set_user(user_id: int, **values) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(
            update(models.User).where(models.User.id == user_id).values(**values)
        )
        await s.commit()


async def _flag_of(user_id: int):
    async with AsyncSessionLocal() as s:
        return (await s.get(models.User, user_id)).password_reset_required


async def _latest_login_id(user_id: int) -> int:
    async with AsyncSessionLocal() as s:
        login_id = (
            await s.execute(
                select(models.LoginHistory.id)
                .where(models.LoginHistory.user_id == user_id)
                .order_by(models.LoginHistory.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    assert login_id is not None, "precondition: the user has a login history row"
    return login_id


def _is_password_change_required(res) -> bool:
    if res.status_code != 403:
        return False
    detail = res.json().get("detail")
    return isinstance(detail, dict) and detail.get("code") == "PASSWORD_CHANGE_REQUIRED"


def _describe(res) -> str:
    return f"HTTP {res.status_code}: {res.text[:300]}"


# --------------------------------------------------------------------------- #
# HTTP gate — one blocked route per dependency branch
# --------------------------------------------------------------------------- #
BLOCKED_ROUTES = [
    # business API through get_current_active_user (Casbin check_permission)
    ("GET", LEADS_URL),
    # IDOR dependency straight at the root (get_lead_for_user): the gate runs
    # before the lookup — unflagged, the same id answers 404
    ("GET", f"{LEADS_URL}/999999"),
    # router dependency straight at the root (config_data)
    ("GET", "/api/config/subject-groups"),
    # self-service at the root that the allowlist leaves out
    ("POST", MFA_SETUP_URL),
    ("GET", "/api/sessions"),
    ("GET", "/api/auth/check-status"),
    ("GET", "/api/security/login-history"),
]


@pytest.mark.parametrize("method,url", BLOCKED_ROUTES)
async def test_flagged_user_is_refused_outside_the_allowlist(
    client, admin_user_in_db, method, url
):
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    await _set_user(user["id"], password_reset_required=True)

    res = await _call(client, method, url, token)

    assert _is_password_change_required(res), f"{method} {url} → {_describe(res)}"


@pytest.mark.parametrize("method,url", BLOCKED_ROUTES)
async def test_unflagged_user_is_not_refused_by_the_gate(
    client, admin_user_in_db, method, url
):
    """Control for the case above: the very same request, flag off, is not the
    gate's 403 — so that 403 is the gate's, not the route's own refusal."""
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])

    res = await _call(client, method, url, token)

    assert not _is_password_change_required(res), f"{method} {url} → {_describe(res)}"
    assert res.status_code < 500, _describe(res)


async def test_flagged_user_reads_users_me_with_the_flag(client, admin_user_in_db):
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    await _set_user(user["id"], password_reset_required=True)

    res = await _call(client, "GET", ME_URL, token)

    assert res.status_code == 200, _describe(res)
    assert res.json()["password_reset_required"] is True


async def test_confirm_login_cannot_lift_the_flag(client, admin_user_in_db):
    """"That was me" clears the flag in the service; a flagged session must not
    reach it — only a password change (or an admin reset) lifts the flag."""
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    login_id = await _latest_login_id(user["id"])
    await _set_user(user["id"], password_reset_required=True)

    res = await _call(
        client,
        "POST",
        CONFIRM_LOGIN_URL,
        token,
        json={"login_id": login_id, "trust_device": False},
    )

    assert await _flag_of(user["id"]) is True, (
        f"confirm-login lifted the flag without a password change: {_describe(res)}"
    )


async def test_recovery_flow_change_password_old_token_refused_relogin_works(
    client, admin_user_in_db
):
    """403 → change password (allowed) → the old token is refused → log in again
    with the new password → business API 200, flag gone."""
    user = admin_user_in_db
    old_token = await _login(client, user["username"], user["password"])
    await _set_user(user["id"], password_reset_required=True)

    blocked = await _call(client, "GET", LEADS_URL, old_token)
    assert _is_password_change_required(blocked), _describe(blocked)

    changed = await _call(
        client,
        "POST",
        CHANGE_PASSWORD_URL,
        old_token,
        json={"old_password": user["password"], "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204, _describe(changed)
    assert await _flag_of(user["id"]) is False

    old_again = await _call(client, "GET", ME_URL, old_token)
    assert old_again.status_code == 401, (
        f"the token of the flagged session survived the change: {_describe(old_again)}"
    )

    new_token = await _login(client, user["username"], NEW_PASSWORD)
    leads = await _call(client, "GET", LEADS_URL, new_token)
    assert leads.status_code == 200, _describe(leads)
    me = await _call(client, "GET", ME_URL, new_token)
    assert me.status_code == 200 and me.json()["password_reset_required"] is False


# --------------------------------------------------------------------------- #
# F133 — /users/me for a flagged admin WITHOUT MFA while MFA is enforced
# --------------------------------------------------------------------------- #
@pytest.fixture
def _mfa_enforced(monkeypatch):
    monkeypatch.setattr(settings, "MFA_ENFORCE_ROLES", ["admin", "manager"])


async def test_f133_password_first_then_mfa(client, admin_user_in_db, _mfa_enforced):
    """The real order: a flagged admin without MFA reads /users/me, cannot
    enrol MFA yet, changes the password, logs in again, meets the MFA gate,
    enrols MFA, and only then reaches the business API."""
    import pyotp

    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    await _set_user(user["id"], password_reset_required=True)

    me = await _call(client, "GET", ME_URL, token)
    assert me.status_code == 200, _describe(me)
    assert me.json()["password_reset_required"] is True
    assert me.json()["mfa_enabled"] is False

    leads = await _call(client, "GET", LEADS_URL, token)
    assert _is_password_change_required(leads), _describe(leads)
    setup_first = await _call(client, "POST", MFA_SETUP_URL, token)
    assert _is_password_change_required(setup_first), _describe(setup_first)

    changed = await _call(
        client,
        "POST",
        CHANGE_PASSWORD_URL,
        token,
        json={"old_password": user["password"], "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204, _describe(changed)

    token2 = await _login(client, user["username"], NEW_PASSWORD)
    me2 = await _call(client, "GET", ME_URL, token2)
    assert me2.status_code == 403 and "MFA is required" in me2.text, _describe(me2)
    leads2 = await _call(client, "GET", LEADS_URL, token2)
    assert leads2.status_code == 403 and "MFA is required" in leads2.text, _describe(leads2)

    setup = await _call(client, "POST", MFA_SETUP_URL, token2)
    assert setup.status_code == 200, _describe(setup)
    enable = await _call(
        client,
        "POST",
        MFA_ENABLE_URL,
        token2,
        json={"code": pyotp.TOTP(setup.json()["secret"]).now()},
    )
    assert enable.status_code == 200, _describe(enable)

    leads3 = await _call(client, "GET", LEADS_URL, token2)
    assert leads3.status_code == 200, _describe(leads3)


async def test_f133_unflagged_admin_without_mfa_still_meets_the_mfa_gate_on_me(
    client, admin_user_in_db, _mfa_enforced
):
    """The MFA deferral on /users/me lasts only while the flag is set."""
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])

    res = await _call(client, "GET", ME_URL, token)

    assert res.status_code == 403 and "MFA is required" in res.text, _describe(res)


async def test_f133_users_me_still_gates_status_while_flagged(client, admin_user_in_db):
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    await _set_user(user["id"], password_reset_required=True, status="inactive")

    res = await _call(client, "GET", ME_URL, token)

    assert res.status_code == 400 and "Inactive user" in res.text, _describe(res)


# --------------------------------------------------------------------------- #
# One source: the allowlist, the Python predicate, the SQL predicate
# --------------------------------------------------------------------------- #
def test_allowlist_is_exactly_the_two_approved_routes():
    """Owner decision 28-10: two routes. Widening it must be a visible edit."""
    assert pc.ALLOWED_ROUTES == frozenset(
        {("POST", "/api/auth/change-password"), ("GET", "/api/users/me")}
    )


def test_every_allowlisted_route_exists_in_the_app():
    """A renamed route would leave a dead entry — and lock flagged users out of
    the only way to recover."""
    from fastapi.routing import APIRoute

    served = {
        (method, route.path)
        for route in fastapi_app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert pc.ALLOWED_ROUTES <= served, sorted(pc.ALLOWED_ROUTES - served)


async def test_sql_predicate_selects_exactly_the_python_predicate(client, admin_user_in_db):
    """``password_change_required`` (Python) and ``password_change_required_sql``
    (watchdog / revalidate) must name the same users."""
    flagged = admin_user_in_db["id"]
    async with AsyncSessionLocal() as s:
        other = models.User(
            username="pc_not_flagged",
            email="pc_not_flagged@test.local",
            password_hash="x",
            role="user",
            status="active",
            password_reset_required=False,
        )
        s.add(other)
        await s.commit()
        await s.refresh(other)
        other_id = other.id
    await _set_user(flagged, password_reset_required=True)

    got = await sm._users_pending_password_change([flagged, other_id])

    async with AsyncSessionLocal() as s:
        users = (
            await s.execute(select(models.User).where(models.User.id.in_([flagged, other_id])))
        ).scalars().all()
    assert got == {u.id for u in users if pc.password_change_required(u)} == {flagged}


async def test_lifespan_runs_the_password_change_watchdog(client):
    """Wiring (CLAUDE.md §10): the loop exists only if the lifespan starts it."""
    task = getattr(fastapi_app.state, "_pwd_watchdog_task", None)
    assert task is not None, "lifespan did not start the password-change watchdog"
    assert not task.done(), "the password-change watchdog is not running"
    assert task.get_coro().__name__ == "password_change_watchdog"


async def test_secure_account_cuts_the_users_sockets_after_commit(
    client, admin_user_in_db
):
    """Wiring of S2: secure-account calls the cut for THIS user, after the flag
    is committed (a session of its own sees it)."""
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    login_id = await _latest_login_id(user["id"])
    flag_at_cut = []

    async def _spy(user_id):
        flag_at_cut.append((user_id, await _flag_of(user_id)))
        return True

    with patch.object(sm, "enforce_password_change_cut", AsyncMock(side_effect=_spy)):
        res = await _call(client, "POST", f"{SECURE_ACCOUNT_URL}?login_id={login_id}", token)

    assert res.status_code == 200, _describe(res)
    assert flag_at_cut == [(user["id"], True)]


# --------------------------------------------------------------------------- #
# Socket.IO against a real server
# --------------------------------------------------------------------------- #
needs_socketio = pytest.mark.skipif(not SOCKETIO_AVAILABLE, reason="python-socketio missing")


class _Recorder:
    """A real Socket.IO client that records, in order, the password-change
    notice and the disconnect."""

    def __init__(self):
        import aiohttp

        self._session = aiohttp.ClientSession()
        self.sio = socketio.AsyncClient(http_session=self._session, reconnection=False)
        self.events: list = []
        self.gone = asyncio.Event()
        self.gone_at = None

        @self.sio.on(sm.PASSWORD_CHANGE_REQUIRED_EVENT)
        async def _notice(*_):
            self.events.append("notice")

        @self.sio.on("disconnect")
        async def _gone(*_):
            self.events.append("disconnect")
            self.gone_at = asyncio.get_running_loop().time()
            self.gone.set()

    async def connect(self, base_url: str, token: str):
        await self.sio.connect(base_url, auth={"token": token}, transports=["websocket"])
        assert self.sio.connected

    async def close(self):
        if self.sio.connected:
            await self.sio.disconnect()
        if not self._session.closed:
            await self._session.close()


@pytest_asyncio.fixture
async def recorder():
    rec = _Recorder()
    try:
        yield rec
    finally:
        await rec.close()


@pytest.fixture
def _no_background_watchdog(client):
    """Stop the lifespan's watchdog so ONLY the sweep a test runs can cut a
    socket (its 30 s timer would make a 'still connected' check racy)."""
    task = fastapi_app.state._pwd_watchdog_task
    task.cancel()
    yield


async def _still_connected_after(rec: _Recorder, seconds: float = 1.0) -> bool:
    try:
        await asyncio.wait_for(rec.gone.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return rec.sio.connected
    return False


@needs_socketio
async def test_s1_connect_refused_while_flagged(test_server, client, admin_user_in_db):
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    # Liveness with the very same token: the refusal below is the guard's.
    alive = _Recorder()
    try:
        await alive.connect(test_server, token)
    finally:
        await alive.close()

    await _set_user(user["id"], password_reset_required=True)
    refused = _Recorder()
    try:
        with pytest.raises(socketio.exceptions.ConnectionError):
            await refused.connect(test_server, token)
    finally:
        await refused.close()


@needs_socketio
async def test_s2_secure_account_notifies_then_cuts_the_live_socket(
    test_server, client, admin_user_in_db, recorder
):
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    login_id = await _latest_login_id(user["id"])
    await recorder.connect(test_server, token)

    res = await _call(client, "POST", f"{SECURE_ACCOUNT_URL}?login_id={login_id}", token)
    assert res.status_code == 200 and res.json().get("relogin_required") is False, _describe(res)

    await asyncio.wait_for(recorder.gone.wait(), timeout=10)
    assert recorder.events == ["notice", "disconnect"]


@needs_socketio
async def test_s3_revalidate_notifies_then_cuts_a_flagged_socket(
    test_server, client, admin_user_in_db, recorder, _no_background_watchdog
):
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    await recorder.connect(test_server, token)
    await _set_user(user["id"], password_reset_required=True)

    await recorder.sio.emit("revalidate_auth")

    await asyncio.wait_for(recorder.gone.wait(), timeout=10)
    assert recorder.events == ["notice", "disconnect"]


WD_INTERVAL, WD_MAX_STALE, WD_CUT_BUDGET = 0.1, 1.0, 0.5
WD_SLACK = 0.3  # websocket + scheduling slack on a real server


@pytest.fixture
def _fast_watchdog(monkeypatch):
    """Short constants for a watchdog the test runs itself (the real loop)."""
    monkeypatch.setattr(sm, "_PWD_WATCHDOG_INTERVAL", WD_INTERVAL)
    monkeypatch.setattr(sm, "_PWD_WATCHDOG_MAX_STALE", WD_MAX_STALE)
    monkeypatch.setattr(sm, "_PWD_WATCHDOG_CUT_BUDGET", WD_CUT_BUDGET)


@pytest_asyncio.fixture
async def _release():
    """Event that stuck fakes wait on; set at teardown so nothing abandoned
    by the watchdog outlives the test."""
    ev = asyncio.Event()
    yield ev
    ev.set()
    await asyncio.sleep(0)


class _Watchdog:
    """The REAL ``password_change_watchdog`` loop, run by the test. Exit
    swallows only the cancellation it sends; a loop that already stopped by
    itself fails the test."""

    async def __aenter__(self):
        self.loop = asyncio.get_running_loop()
        self.t0 = self.loop.time()
        self.task = asyncio.create_task(sm.password_change_watchdog())
        return self

    async def __aexit__(self, *exc):
        if self.task.done():
            if exc[0] is None:
                pytest.fail(f"the watchdog stopped by itself: {self.task.exception()!r}")
            return False
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        return False


@needs_socketio
async def test_f134_watchdog_cuts_what_an_unconfirmed_s2_left_without_revalidate(
    test_server, client, admin_user_in_db, recorder, _no_background_watchdog, _fast_watchdog
):
    """S2's cut is not ACK-confirmed and the client never revalidates: the HTTP
    answer still reflects the commit, the socket survives S2, and the
    server's own loop cuts it within one interval of starting."""
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    login_id = await _latest_login_id(user["id"])
    await recorder.connect(test_server, token)

    with patch.object(
        sm, "force_password_change_cut_strict", AsyncMock(side_effect=TimeoutError("no ACK"))
    ):
        res = await _call(client, "POST", f"{SECURE_ACCOUNT_URL}?login_id={login_id}", token)
    assert res.status_code == 200, _describe(res)
    assert await _flag_of(user["id"]) is True
    assert await _still_connected_after(recorder), "precondition: S2 must not have cut"

    async with _Watchdog() as wd:
        await asyncio.wait_for(recorder.gone.wait(), timeout=WD_INTERVAL + 2.0)
        cut_after = recorder.gone_at - wd.t0
    assert cut_after <= WD_INTERVAL + WD_SLACK, cut_after
    assert recorder.events == ["notice", "disconnect"]


@needs_socketio
async def test_f134_watchdog_keeps_sockets_while_flags_unreadable_within_the_bound(
    test_server, client, admin_user_in_db, recorder, _no_background_watchdog, _fast_watchdog
):
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    await recorder.connect(test_server, token)

    with patch.object(
        sm, "_users_pending_password_change", AsyncMock(side_effect=OSError("db down"))
    ):
        async with _Watchdog() as wd:
            await asyncio.sleep(max(0.0, wd.t0 + WD_MAX_STALE - WD_SLACK - wd.loop.time()))
            assert recorder.sio.connected and recorder.events == [], (
                "a short DB outage cut a socket before the bound")


@needs_socketio
async def test_f134_watchdog_cuts_every_socket_by_the_bound_even_if_reads_hang(
    test_server, client, admin_user_in_db, _no_background_watchdog, _fast_watchdog, _release
):
    """A read that never returns cannot hold the cut: by the bound EVERY local
    socket (two here) is cut, with no notice (no reason is known)."""
    user = admin_user_in_db
    token = await _login(client, user["username"], user["password"])
    socks = [_Recorder(), _Recorder()]
    try:
        for rec in socks:
            await rec.connect(test_server, token)

        async def hang(_ids):
            await _release.wait()

        with patch.object(sm, "_users_pending_password_change", hang):
            async with _Watchdog() as wd:
                await asyncio.wait_for(
                    asyncio.gather(*(rec.gone.wait() for rec in socks)),
                    timeout=WD_MAX_STALE + WD_CUT_BUDGET + 1.0,
                )
                cut_after = [rec.gone_at - wd.t0 for rec in socks]
    finally:
        for rec in socks:
            await rec.close()

    assert all(WD_MAX_STALE <= c <= WD_MAX_STALE + WD_SLACK for c in cut_after), cut_after
    # ONE fail-closed turn cuts them all. A socket left to a later turn (≥ one
    # interval on) still fits WD_SLACK here, but at production's ratio
    # (INTERVAL 30 > CUT_BUDGET 10) it would be past the bound.
    assert max(cut_after) - min(cut_after) < WD_INTERVAL, cut_after
    assert [rec.events for rec in socks] == [["disconnect"], ["disconnect"]], "no notice"


async def test_f134_a_watchdog_that_ends_exits_the_worker(
    setup_test_database, monkeypatch, _fast_watchdog, _release
):
    """Separate from 'deadline reached' and 'socket cut': when the loop ENDS
    (here: the fail-closed cut overran its budget), the lifespan's
    supervisor calls ``os._exit(1)``. Faked so the test process survives."""
    import os

    from app.main import lifespan

    exits: list = []
    monkeypatch.setattr(os, "_exit", lambda code: exits.append(code))
    cut_calls: list = []

    async def stuck_cut():
        cut_calls.append(asyncio.get_running_loop().time())
        await _release.wait()
        return 0

    with patch.object(sm, "_users_pending_password_change",
                      AsyncMock(side_effect=OSError("db down"))), \
            patch.object(sm, "_cut_every_local_socket", stuck_cut):
        async with lifespan(fastapi_app):
            task = fastapi_app.state._pwd_watchdog_task
            loop = asyncio.get_running_loop()
            limit = loop.time() + WD_MAX_STALE + WD_CUT_BUDGET + 1.0
            while not task.done() and loop.time() < limit:
                await asyncio.sleep(0.02)
            await asyncio.sleep(0)  # let the done-callback run
            ended = task.done()
            exc = task.exception() if ended and not task.cancelled() else None

    assert cut_calls, "the deadline never triggered the fail-closed cut"
    assert ended and isinstance(exc, TimeoutError), exc
    assert exits == [1], f"the supervisor did not exit the worker: {exits}"
