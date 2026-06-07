"""Unit tests for the server-side force-disconnect ACK subsystem
(``app/socket_manager.py``).

Covers the invariants hardened during review:
- heartbeat watchdog uses FINITE socket timeouts (no infinite hang),
- 3 consecutive heartbeat failures call ``os._exit(1)`` BEFORE the TTL grace,
- ``_required_workers`` prunes ONLY workers whose heartbeat key is gone
  (process exited), never a live-heartbeat worker,
- ``force_disconnect_user_strict`` fails closed: no live workers → raise,
  missing ACK → TimeoutError, and emits ONE batched command for all user ids,
- a handler failure does NOT ACK (publisher fail-closes),
- ``force_disconnect_user`` disconnects every local SID of the user.

These are pure unit tests with mocked Redis / Socket.IO — no live app needed.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import socket_manager as sm

pytestmark = [pytest.mark.unit, pytest.mark.security]


# --------------------------------------------------------------------------- #
# Heartbeat watchdog thread (sync function, runs off the event loop)
# --------------------------------------------------------------------------- #
def test_heartbeat_thread_uses_finite_socket_timeouts():
    """A network blackhole must not be able to hang the heartbeat past the TTL,
    so the sync Redis client MUST be created with finite socket timeouts."""
    captured = {}

    def fake_from_url(url, **kwargs):
        captured.update(kwargs)
        client = MagicMock()
        client.set.return_value = True
        return client

    stop = MagicMock()
    stop.is_set.side_effect = [False, True]  # one iteration then exit
    stop.wait.return_value = None

    with patch.object(sm._redis_sync.Redis, "from_url", side_effect=fake_from_url):
        sm._heartbeat_thread_run("w1", stop)

    assert captured.get("socket_timeout") == 2
    assert captured.get("socket_connect_timeout") == 2
    assert captured.get("retry_on_timeout") is False
    assert captured.get("decode_responses") is True


def test_heartbeat_three_failures_exits_worker():
    """3 consecutive refresh failures must call ``os._exit(1)`` (so the process
    dies and its sockets close BEFORE the 30s TTL lets it be pruned)."""
    client = MagicMock()
    client.set.side_effect = Exception("blackhole")
    stop = MagicMock()
    stop.is_set.return_value = False
    stop.wait.return_value = None

    with patch.object(sm._redis_sync.Redis, "from_url", return_value=client), \
            patch.object(sm.os, "_exit", side_effect=SystemExit) as mexit:
        with pytest.raises(SystemExit):
            sm._heartbeat_thread_run("w1", stop)

    mexit.assert_called_once_with(1)
    assert client.set.call_count == sm._HB_MAX_FAILS  # exits exactly at the 3rd


def test_heartbeat_transient_failure_does_not_exit():
    """A single transient failure (then success) must NOT kill the worker."""
    client = MagicMock()
    client.set.side_effect = [Exception("blip"), True]
    stop = MagicMock()
    stop.is_set.side_effect = [False, False, True]
    stop.wait.return_value = None

    with patch.object(sm._redis_sync.Redis, "from_url", return_value=client), \
            patch.object(sm.os, "_exit", side_effect=SystemExit) as mexit:
        sm._heartbeat_thread_run("w1", stop)

    mexit.assert_not_called()


# --------------------------------------------------------------------------- #
# _required_workers — prune only the provably-dead
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_required_workers_prunes_only_heartbeat_gone():
    rc = AsyncMock()
    rc.smembers.return_value = {"w_live", "w_dead"}

    async def _exists(key):
        return 1 if key.endswith("w_live") else 0

    rc.exists.side_effect = _exists
    with patch.object(sm, "redis_client", rc):
        required = await sm._required_workers()

    assert required == {"w_live"}
    # The dead worker (heartbeat gone) is pruned; the live one is kept.
    rc.srem.assert_awaited_once()
    assert "w_dead" in rc.srem.await_args.args


# --------------------------------------------------------------------------- #
# force_disconnect_user_strict — fail-closed + batched
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_strict_no_live_workers_raises():
    with patch.object(sm, "_required_workers", AsyncMock(return_value=set())):
        with pytest.raises(RuntimeError):
            await sm.force_disconnect_user_strict([1])


@pytest.mark.asyncio
async def test_strict_ack_timeout_raises():
    rc = AsyncMock()
    rc.smembers.return_value = set()  # nobody ever ACKs
    with patch.object(sm, "redis_client", rc), \
            patch.object(sm, "_required_workers", AsyncMock(return_value={"w1"})), \
            patch.object(sm.asyncio, "sleep", AsyncMock()):
        with pytest.raises(TimeoutError):
            await sm.force_disconnect_user_strict([1], timeout=0.3)
    rc.publish.assert_awaited_once()
    rc.delete.assert_awaited()  # ack key cleaned up in finally


@pytest.mark.asyncio
async def test_strict_success_one_batched_command():
    rc = AsyncMock()
    rc.smembers.return_value = {"w1"}  # immediate ACK
    with patch.object(sm, "redis_client", rc), \
            patch.object(sm, "_required_workers", AsyncMock(return_value={"w1"})):
        cmd = await sm.force_disconnect_user_strict([1, 2, 3])

    assert isinstance(cmd, str) and cmd
    rc.publish.assert_awaited_once()
    channel, raw = rc.publish.await_args.args
    assert channel == sm.FORCE_DISCONNECT_CHANNEL
    payload = json.loads(raw)
    assert payload["user_ids"] == [1, 2, 3]  # ONE command for the whole batch


@pytest.mark.asyncio
async def test_strict_waits_for_all_workers_multi():
    """Multi-worker: succeeds only when EVERY required worker ACKs."""
    rc = AsyncMock()
    rc.smembers.return_value = {"w1", "w2"}  # both ACK
    with patch.object(sm, "redis_client", rc), \
            patch.object(sm, "_required_workers", AsyncMock(return_value={"w1", "w2"})):
        cmd = await sm.force_disconnect_user_strict([1])
    assert cmd


@pytest.mark.asyncio
async def test_strict_one_worker_missing_ack_fails_multi():
    """Multi-worker: a single non-ACKing worker → TimeoutError (fail-closed)."""
    rc = AsyncMock()
    rc.smembers.return_value = {"w1"}  # w2 never ACKs
    two = AsyncMock(return_value={"w1", "w2"})
    with patch.object(sm, "redis_client", rc), \
            patch.object(sm, "_required_workers", two), \
            patch.object(sm.asyncio, "sleep", AsyncMock()):
        with pytest.raises(TimeoutError):
            await sm.force_disconnect_user_strict([1], timeout=0.3)


@pytest.mark.asyncio
async def test_strict_empty_list_is_noop():
    with patch.object(sm, "_required_workers", AsyncMock()) as req:
        out = await sm.force_disconnect_user_strict([])
    assert out == ""
    req.assert_not_awaited()  # never even looks up workers


# --------------------------------------------------------------------------- #
# Handler — no ACK on failure
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_handler_failure_does_not_ack():
    rc = AsyncMock()
    with patch.object(sm, "redis_client", rc), \
            patch.object(sm, "force_disconnect_user",
                         AsyncMock(side_effect=Exception("boom"))):
        with pytest.raises(Exception):
            await sm._handle_force_disconnect(
                json.dumps({"command_id": "c1", "user_ids": [1]})
            )
    rc.sadd.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_success_acks_once():
    rc = AsyncMock()
    sm._worker_id = "w-self"
    with patch.object(sm, "redis_client", rc), \
            patch.object(sm, "force_disconnect_user", AsyncMock(return_value=0)):
        await sm._handle_force_disconnect(
            json.dumps({"command_id": "c2", "user_ids": [1, 2]})
        )
    rc.sadd.assert_awaited_once()
    ack_key, wid = rc.sadd.await_args.args
    assert ack_key == sm._ACK_PREFIX + "c2"
    assert wid == "w-self"


# --------------------------------------------------------------------------- #
# force_disconnect_user — local disconnect of every SID
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_force_disconnect_user_disconnects_all_local_sids():
    fake_sio = MagicMock()
    fake_sio.manager.get_participants.return_value = [("sidA", "e1"), ("sidB", "e2")]
    fake_sio.disconnect = AsyncMock()
    with patch.object(sm, "sio", fake_sio):
        n = await sm.force_disconnect_user([7])
    assert n == 2
    assert fake_sio.disconnect.await_count == 2
    fake_sio.manager.get_participants.assert_called_with("/", "user_room_7")
