# tests/security/test_password_change_socket_unit.py
# -*- coding: utf-8 -*-
"""Unit tests (mocked Socket.IO / Redis / DB) for the F128 socket layers and
the F134 watchdog in ``app/socket_manager.py``, plus the pure predicate and
route key of ``app/core/password_change.py``.

The same behaviours are measured against a real server in
``test_password_reset_enforced.py``; these cases pin what a real server cannot
reach cheaply: ordering, ACK bookkeeping, the loop's bound, the log that marks
an unconfirmed cut.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import socket_manager as sm
from app.core import password_change as pc

pytestmark = [pytest.mark.unit, pytest.mark.security]


@pytest.fixture(autouse=True)
def _cam_ro_worker_id():
    """Same fence as ``test_socket_force_disconnect.py``: ``_worker_id`` is
    process-global; no case here may leave it changed."""
    truoc = sm._worker_id
    yield
    assert sm._worker_id == truoc


# --------------------------------------------------------------------------- #
# Predicate + route key
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,blocked",
    [(True, True), (False, False), (None, True), ("false", True), (0, True)],
)
def test_predicate_blocks_everything_but_an_exact_false(value, blocked):
    assert pc.password_change_required(SimpleNamespace(password_reset_required=value)) is blocked


def test_sql_predicate_keeps_null_on_the_blocking_side():
    from sqlalchemy.dialects import postgresql

    sql = str(pc.password_change_required_sql().compile(dialect=postgresql.dialect()))
    assert sql.endswith("password_reset_required IS NOT false"), sql


def _request(method, path):
    route = SimpleNamespace(path=path) if path is not None else None
    return SimpleNamespace(method=method, scope={"route": route} if route else {})


@pytest.mark.parametrize(
    "method,path,allowed",
    [
        ("GET", "/api/users/me", True),
        ("get", "/api/users/me", True),
        ("POST", "/api/auth/change-password", True),
        # same template, other method
        ("PUT", "/api/users/me", False),
        ("GET", "/api/auth/change-password", False),
        # neighbours / prefixes of an allowlisted template
        ("POST", "/api/auth/change-password/extra", False),
        ("POST", "/api/auth/mfa/setup", False),
        ("GET", "/api/users/me/", False),
        # no matched route ⇒ nothing is allowed
        ("GET", None, False),
    ],
)
def test_allowlist_matches_method_and_route_template_exactly(method, path, allowed):
    assert pc.is_allowed_while_forced(_request(method, path)) is allowed


# --------------------------------------------------------------------------- #
# S2 — local cut, handler routing, strict publish, post-commit enforcement
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cut_password_change_sockets_notifies_then_cuts_each_sid_of_the_user():
    order = []
    fake_sio = MagicMock()
    fake_sio.manager.get_participants.return_value = [("sidA", "e1"), ("sidB", "e2")]
    fake_sio.emit = AsyncMock(side_effect=lambda ev, data, room, **k: order.append((ev, room)))
    fake_sio.disconnect = AsyncMock(side_effect=lambda sid: order.append(("cut", sid)))
    with patch.object(sm, "sio", fake_sio):
        n = await sm.cut_password_change_sockets([7])

    assert n == 2
    assert order == [
        (sm.PASSWORD_CHANGE_REQUIRED_EVENT, "sidA"), ("cut", "sidA"),
        (sm.PASSWORD_CHANGE_REQUIRED_EVENT, "sidB"), ("cut", "sidB"),
    ]
    fake_sio.manager.get_participants.assert_called_once_with("/", "user_room_7")


@pytest.mark.asyncio
async def test_notice_failure_never_blocks_the_cut():
    fake_sio = MagicMock()
    fake_sio.emit = AsyncMock(side_effect=RuntimeError("emit failed"))
    fake_sio.disconnect = AsyncMock()
    with patch.object(sm, "sio", fake_sio):
        await sm._notify_and_cut_password_change("sidA")
    fake_sio.disconnect.assert_awaited_once_with("sidA")


@pytest.mark.asyncio
async def test_handler_routes_password_change_command_and_acks_once():
    rc = AsyncMock()
    cut_pwd = AsyncMock(return_value=1)
    cut_users = AsyncMock(return_value=0)
    cut_sessions = AsyncMock(return_value=0)
    raw = json.dumps({"command_id": "c1", "password_change_user_ids": [7]})
    with patch.object(sm, "_worker_id", "w-self"), \
            patch.object(sm, "redis_client", rc), \
            patch.object(sm, "cut_password_change_sockets", cut_pwd), \
            patch.object(sm, "force_disconnect_user", cut_users), \
            patch.object(sm, "force_disconnect_sessions", cut_sessions):
        await sm._handle_force_disconnect(raw)

    cut_pwd.assert_awaited_once_with([7])
    cut_users.assert_not_awaited()
    cut_sessions.assert_not_awaited()
    rc.sadd.assert_awaited_once_with(sm._ACK_PREFIX + "c1", "w-self")


@pytest.mark.asyncio
async def test_handler_password_change_cut_failure_does_not_ack():
    rc = AsyncMock()
    raw = json.dumps({"command_id": "c2", "password_change_user_ids": [7]})
    with patch.object(sm, "_worker_id", "w-self"), \
            patch.object(sm, "redis_client", rc), \
            patch.object(sm, "cut_password_change_sockets",
                         AsyncMock(side_effect=RuntimeError("cut failed"))):
        with pytest.raises(RuntimeError):
            await sm._handle_force_disconnect(raw)
    rc.sadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_strict_publishes_one_password_change_command():
    publish = AsyncMock(return_value="cmd")
    with patch.object(sm, "_publish_force_disconnect_strict", publish):
        out = await sm.force_password_change_cut_strict([7, 8])
    assert out == "cmd"
    publish.assert_awaited_once()
    targets = publish.await_args.args[0]
    assert targets == {"password_change_user_ids": [7, 8]}


@pytest.mark.asyncio
async def test_unconfirmed_cut_is_logged_as_unconfirmed_and_never_raises():
    fake_log = MagicMock()
    with patch.object(sm, "force_password_change_cut_strict",
                      AsyncMock(side_effect=TimeoutError("no ACK"))), \
            patch.object(sm, "log", fake_log):
        ok = await sm.enforce_password_change_cut(7)

    assert ok is False
    actions = [c.kwargs.get("action") for c in fake_log.error.call_args_list]
    assert actions == ["socket.password_change_cut_unconfirmed"]
    fake_log.info.assert_not_called()


@pytest.mark.asyncio
async def test_confirmed_cut_is_reported_done():
    fake_log = MagicMock()
    with patch.object(sm, "force_password_change_cut_strict", AsyncMock(return_value="c")), \
            patch.object(sm, "log", fake_log):
        ok = await sm.enforce_password_change_cut(7)
    assert ok is True
    actions = [c.kwargs.get("action") for c in fake_log.info.call_args_list]
    assert actions == ["socket.password_change_cut_confirmed"]


# --------------------------------------------------------------------------- #
# S3 — revalidate_auth
# --------------------------------------------------------------------------- #
def _fake_sio_with_session(session):
    order = []
    fake_sio = MagicMock()
    fake_sio.get_session = AsyncMock(return_value=session)
    fake_sio.emit = AsyncMock(side_effect=lambda ev, data, room, **k: order.append(ev))
    fake_sio.disconnect = AsyncMock(side_effect=lambda sid: order.append("cut"))
    return fake_sio, order


@pytest.mark.asyncio
async def test_revalidate_password_change_notifies_then_cuts():
    fake_sio, order = _fake_sio_with_session({"user_id": 5, "session_id": 7})
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "_session_refusal_reason",
                         AsyncMock(return_value=sm.PASSWORD_CHANGE_REFUSAL)):
        out = await sm.revalidate_auth("sid1")
    assert out == {"valid": False, "reason": sm.PASSWORD_CHANGE_REFUSAL}
    assert order == [sm.PASSWORD_CHANGE_REQUIRED_EVENT, "cut"]


@pytest.mark.asyncio
async def test_revalidate_other_refusal_cuts_without_the_notice():
    fake_sio, order = _fake_sio_with_session({"user_id": 5, "session_id": 7})
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "_session_refusal_reason",
                         AsyncMock(return_value="Session revoked")):
        out = await sm.revalidate_auth("sid1")
    assert out == {"valid": False, "reason": "Session revoked"}
    assert order == ["cut"]


# --------------------------------------------------------------------------- #
# F134 — one pass
# --------------------------------------------------------------------------- #
def _sweep_sio(sessions: dict):
    """``sessions``: sid → socket session (``{}`` = mid-connect)."""
    order = []
    fake_sio = MagicMock()
    fake_sio.manager.get_participants.return_value = [(sid, "e") for sid in sessions]
    fake_sio.get_session = AsyncMock(side_effect=lambda sid: sessions[sid])
    fake_sio.emit = AsyncMock(side_effect=lambda ev, data, room, **k: order.append((ev, room)))
    fake_sio.disconnect = AsyncMock(side_effect=lambda sid: order.append(("cut", sid)))
    return fake_sio, order


@pytest.mark.asyncio
async def test_sweep_cuts_only_sockets_of_flagged_users():
    fake_sio, order = _sweep_sio(
        {"sidF": {"user_id": 1}, "sidOk": {"user_id": 2}, "sidNew": {}}
    )
    pending = AsyncMock(return_value={1})
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "_users_pending_password_change", pending):
        n = await sm._password_change_sweep()

    assert n == 1
    assert order == [(sm.PASSWORD_CHANGE_REQUIRED_EVENT, "sidF"), ("cut", "sidF")]
    assert sorted(pending.await_args.args[0]) == [1, 2], "mid-connect sid not judged"


@pytest.mark.asyncio
async def test_sweep_unreadable_flags_raise_and_cut_nothing():
    """The pass itself never decides fail-open/fail-closed: it raises."""
    fake_sio, order = _sweep_sio({"sidA": {"user_id": 1}})
    with patch.object(sm, "sio", fake_sio), \
            patch.object(sm, "_users_pending_password_change",
                         AsyncMock(side_effect=OSError("db down"))):
        with pytest.raises(OSError):
            await sm._password_change_sweep()
    assert order == []


# --------------------------------------------------------------------------- #
# F134/F135 — the loop and its bound, on the REAL event-loop clock
# --------------------------------------------------------------------------- #
# Short constants; the margins below are what the cases measure.
INTERVAL, MAX_STALE, CUT_BUDGET = 0.12, 0.5, 0.15
EPS = 0.04  # scheduling slack allowed after a deadline
TWO = {"sidA": {"user_id": 1}, "sidB": {"user_id": 2}}  # "every socket" ⇒ ≥ 2


@pytest.fixture
def _nhanh(monkeypatch):
    monkeypatch.setattr(sm, "_PWD_WATCHDOG_INTERVAL", INTERVAL)
    monkeypatch.setattr(sm, "_PWD_WATCHDOG_MAX_STALE", MAX_STALE)
    monkeypatch.setattr(sm, "_PWD_WATCHDOG_CUT_BUDGET", CUT_BUDGET)


@pytest.fixture
async def _tha_ket():
    """An Event that stuck fakes wait on; set at teardown so nothing the test
    abandoned (a pass or a cut that swallowed its cancel) outlives it."""
    ev = asyncio.Event()
    yield ev
    ev.set()
    await asyncio.sleep(0)


class _Socks:
    """Local sockets of a fake worker. A cut removes the sid and records WHEN
    (loop time) and whether a notice preceded it."""

    def __init__(self, sessions: dict):
        self.sessions = dict(sessions)
        self.cuts: list = []      # (time, sid, noticed)
        self._noticed: set = set()
        self.sio = MagicMock()
        self.sio.manager.get_participants.side_effect = (
            lambda ns, room: [(sid, "e") for sid in list(self.sessions)]
        )
        self.sio.get_session = AsyncMock(side_effect=self._get_session)
        self.sio.emit = AsyncMock(side_effect=self._emit)
        self.sio.disconnect = AsyncMock(side_effect=self._disconnect)

    async def _get_session(self, sid):
        if sid not in self.sessions:
            raise KeyError("Session not found")
        return self.sessions[sid]

    async def _emit(self, ev, data, room, **k):
        self._noticed.add(room)

    async def _disconnect(self, sid):
        self.sessions.pop(sid, None)
        self.cuts.append((asyncio.get_running_loop().time(), sid, sid in self._noticed))

    def cut_all(self):
        """(first, last) time of the notice-less cuts, and which sids."""
        rows = [(t, sid) for t, sid, noticed in self.cuts if not noticed]
        if not rows:
            return None, None, set()
        return min(t for t, _ in rows), max(t for t, _ in rows), {sid for _, sid in rows}


async def _run_watchdog(socks: _Socks, read, seconds: float, *, expect_end: bool = False,
                        ended: list | None = None):
    """Run the REAL loop for ``seconds``; return (t0, task).

    ``t0`` is taken just before the loop starts, so its first deadline is
    ≥ ``t0 + MAX_STALE``. Only the cancellation THIS helper sends is
    swallowed: a loop that stopped by itself is a failure (unless the case
    expects it), and so is one that does not end on cancel."""
    loop = asyncio.get_running_loop()
    with patch.object(sm, "sio", socks.sio), \
            patch.object(sm, "_users_pending_password_change", read):
        t0 = loop.time()
        task = asyncio.create_task(sm.password_change_watchdog())
        if ended is not None:
            task.add_done_callback(lambda t: ended.append(loop.time()))
        await asyncio.sleep(seconds)
        if task.done():
            if not expect_end:
                exc = task.exception() if not task.cancelled() else None
                pytest.fail(f"the watchdog stopped by itself: {exc!r}")
            return t0, task
        if expect_end:
            task.cancel()
            pytest.fail("the watchdog was expected to end and is still running")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert task.cancelled(), "the watchdog swallowed its own cancellation"
    return t0, task


@pytest.mark.asyncio
async def test_healthy_cuts_a_flagged_socket_within_an_interval(_nhanh):
    socks = _Socks({"sidF": {"user_id": 1}, "sidOk": {"user_id": 2}, "sidNew": {}})
    t0, _ = await _run_watchdog(socks, AsyncMock(return_value={1}), MAX_STALE + 0.3)

    assert [(sid, noticed) for _, sid, noticed in socks.cuts] == [("sidF", True)]
    assert socks.cuts[0][0] <= t0 + INTERVAL + EPS
    assert set(socks.sessions) == {"sidOk", "sidNew"}, "a healthy loop never cuts all"


@pytest.mark.asyncio
async def test_slow_failing_reads_cannot_push_the_cut_past_the_deadline(_nhanh):
    """Each read takes 0.1 s, then fails: the checks must not drift (35→70→
    105→140 at full scale)."""
    async def read(_ids):
        await asyncio.sleep(0.1)
        raise OSError("db slow then down")

    socks = _Socks(TWO)
    t0, _ = await _run_watchdog(socks, read, MAX_STALE + 0.3)

    first, last, sids = socks.cut_all()
    assert sids == {"sidA", "sidB"}, "every socket must be cut at the bound"
    assert t0 + MAX_STALE <= first and last <= t0 + MAX_STALE + EPS, (first - t0, last - t0)


@pytest.mark.asyncio
async def test_a_read_that_never_returns_cannot_hold_the_cut(_nhanh, _tha_ket):
    async def read(_ids):
        await _tha_ket.wait()

    socks = _Socks(TWO)
    t0, _ = await _run_watchdog(socks, read, MAX_STALE + 0.3)

    first, last, sids = socks.cut_all()
    assert sids == {"sidA", "sidB"}, "a hung read held the sockets past the bound"
    assert t0 + MAX_STALE <= first and last <= t0 + MAX_STALE + EPS, (first - t0, last - t0)


@pytest.mark.asyncio
async def test_a_read_that_delays_its_cancellation_cannot_hold_the_cut(_nhanh, _tha_ket):
    """Cancellation reaches the read, whose cleanup then takes 1 s: the loop
    must not wait for that cleanup (``asyncio.timeout`` would)."""
    async def read(_ids):
        try:
            await _tha_ket.wait()
        finally:
            await asyncio.sleep(1.0)

    socks = _Socks(TWO)
    t0, _ = await _run_watchdog(socks, read, MAX_STALE + 0.3)

    first, last, sids = socks.cut_all()
    assert sids == {"sidA", "sidB"}
    assert last <= t0 + MAX_STALE + EPS, last - t0


@pytest.mark.asyncio
async def test_a_read_that_swallows_its_cancellation_cannot_hold_the_cut(_nhanh, _tha_ket):
    async def read(_ids):
        while not _tha_ket.is_set():
            try:
                await _tha_ket.wait()
            except asyncio.CancelledError:
                continue  # swallowed

    socks = _Socks(TWO)
    t0, _ = await _run_watchdog(socks, read, MAX_STALE + 0.3)

    first, last, sids = socks.cut_all()
    assert sids == {"sidA", "sidB"}
    assert last <= t0 + MAX_STALE + EPS, last - t0


@pytest.mark.asyncio
async def test_lasting_errors_cut_at_the_bound_and_do_not_spin(_nhanh):
    reads = AsyncMock(side_effect=OSError("db down"))
    socks = _Socks(TWO)
    run = MAX_STALE + 4 * INTERVAL
    t0, _ = await _run_watchdog(socks, reads, run)

    first, last, sids = socks.cut_all()
    assert sids == {"sidA", "sidB"}
    assert t0 + MAX_STALE <= first and last <= t0 + MAX_STALE + EPS, (first - t0, last - t0)
    assert reads.await_count <= int(run / INTERVAL) + 2, (
        f"{reads.await_count} reads in {run}s — the stale loop is spinning")


@pytest.mark.asyncio
async def test_a_cut_that_hangs_ends_the_loop_within_its_budget(_nhanh, _tha_ket):
    """Fail-closed cut stuck (even swallowing its cancel) ⇒ the loop raises
    TimeoutError by deadline + cut budget — it does not hang with it. That is
    the loop ENDING; the worker exit is the lifespan's (separate case)."""
    socks = _Socks(TWO)

    async def stuck(sid):
        while not _tha_ket.is_set():
            try:
                await _tha_ket.wait()
            except asyncio.CancelledError:
                continue

    socks.sio.disconnect = AsyncMock(side_effect=stuck)
    ended: list = []
    t0, task = await _run_watchdog(
        socks, AsyncMock(side_effect=OSError("db down")),
        MAX_STALE + CUT_BUDGET + 3 * EPS, expect_end=True, ended=ended,
    )

    assert isinstance(task.exception(), TimeoutError), task.exception()
    assert ended and ended[0] <= t0 + MAX_STALE + CUT_BUDGET + EPS, [e - t0 for e in ended]


@pytest.mark.asyncio
async def test_the_bound_counts_from_the_start_of_the_last_good_read(_nhanh, _tha_ket):
    """One good read taking 0.1 s, then reads hang: the deadline is the START
    of that read + MAX_STALE, not its end."""
    starts = []

    async def read(_ids):
        starts.append(asyncio.get_running_loop().time())
        if len(starts) == 1:
            await asyncio.sleep(0.1)
            return set()
        await _tha_ket.wait()

    socks = _Socks(TWO)
    await _run_watchdog(socks, read, INTERVAL + 0.1 + MAX_STALE + 0.2)

    first, last, sids = socks.cut_all()
    assert sids == {"sidA", "sidB"}
    assert last <= starts[0] + MAX_STALE + EPS, last - starts[0]


@pytest.mark.asyncio
async def test_recovers_once_flags_are_readable_again(_nhanh):
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    up_at = t0 + MAX_STALE + INTERVAL

    async def read(_ids):
        if loop.time() < up_at:
            raise OSError("db down")
        return set()

    socks = _Socks(TWO)

    async def late_sockets():
        await asyncio.sleep(up_at - loop.time() + 3 * INTERVAL)
        socks.sessions["sidC"] = {"user_id": 3}
        socks.sessions["sidD"] = {"user_id": 4}

    adder = asyncio.create_task(late_sockets())
    await _run_watchdog(socks, read, up_at - t0 + 6 * INTERVAL)
    await adder

    assert {"sidA", "sidB"} <= socks.cut_all()[2], "the outage must have cut every old socket"
    assert {"sidC", "sidD"} <= set(socks.sessions), "after recovery the loop kept cutting"


@pytest.mark.asyncio
async def test_recovery_rearms_the_bound(_nhanh):
    """After an outage past the bound, a good read RE-ARMS the bound: one
    transient failure later is just a failure, not another cut of everything."""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    up_at = t0 + MAX_STALE + INTERVAL
    blip_at = up_at + 4 * INTERVAL
    blipped: list = []

    async def read(_ids):
        now = loop.time()
        if now < up_at:
            raise OSError("db down")
        if now >= blip_at and not blipped:
            blipped.append(now)
            raise OSError("one transient failure")
        return set()

    socks = _Socks(TWO)

    async def late_sockets():
        await asyncio.sleep(up_at - loop.time() + 2 * INTERVAL)
        socks.sessions["sidC"] = {"user_id": 3}
        socks.sessions["sidD"] = {"user_id": 4}

    adder = asyncio.create_task(late_sockets())
    await _run_watchdog(socks, read, up_at - t0 + 6 * INTERVAL)
    await adder

    assert blipped, "the transient failure never happened"
    assert {"sidA", "sidB"} <= socks.cut_all()[2], "the outage must have cut every old socket"
    assert {"sidC", "sidD"} <= set(socks.sessions), "one failure after recovery cut everything"


def test_bound_constants_are_coherent():
    """Advertised bound 120 s; a stale turn (sleep + recovery pass + cut) fits
    inside it."""
    assert sm._PWD_WATCHDOG_BOUND == sm._PWD_WATCHDOG_MAX_STALE + sm._PWD_WATCHDOG_CUT_BUDGET == 120.0
    assert 2 * sm._PWD_WATCHDOG_INTERVAL + sm._PWD_WATCHDOG_CUT_BUDGET <= sm._PWD_WATCHDOG_BOUND
    assert sm._PWD_WATCHDOG_INTERVAL < sm._PWD_WATCHDOG_MAX_STALE
