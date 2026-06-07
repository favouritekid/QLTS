"""Integration test: server-side force-disconnect end-to-end over REAL Redis
pub/sub with a single in-process worker.

Verifies the full path: publish → subscribe → local disconnect → ACK → publisher
returns. The multi-worker ACK aggregation / required-set logic is unit-tested in
``test_socket_force_disconnect.py``; a true 2-OS-process fan-out run is left to
manual/CI (pytest is single-process and the worker id is process-global).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import socket_manager as sm

pytestmark = [pytest.mark.asyncio, pytest.mark.integration, pytest.mark.security]


async def test_force_disconnect_end_to_end_real_redis(setup_test_database):
    # Fake the local socket layer: 2 SIDs in the target user's room.
    fake_sio = MagicMock()
    fake_sio.manager.get_participants.return_value = [("sidA", "e1"), ("sidB", "e2")]
    fake_sio.disconnect = AsyncMock()

    pubsub = await sm.subscribe_force_disconnect()
    await sm.register_socket_worker()
    task = asyncio.create_task(sm.consume_force_disconnect(pubsub))
    await asyncio.sleep(0.15)  # let the consumer actually start listening
    try:
        with patch.object(sm, "sio", fake_sio):
            cmd = await sm.force_disconnect_user_strict([4242], timeout=3.0)
        assert cmd, "strict disconnect should be ACKed by the in-process worker"
        # The worker disconnected both local SIDs of the user.
        assert fake_sio.disconnect.await_count == 2
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await sm.deregister_socket_worker()


async def test_force_disconnect_strict_raises_without_workers(setup_test_database):
    """With no registered worker, enforcement cannot be guaranteed → fail-closed.
    (Clean any leftover registry entries first so the set is genuinely empty.)"""
    from app.database import redis_client

    members = await redis_client.smembers(sm._WORKERS_SET)
    if members:
        await redis_client.srem(sm._WORKERS_SET, *members)

    with pytest.raises(RuntimeError):
        await sm.force_disconnect_user_strict([1], timeout=0.5)


async def test_worker_register_deregister_roundtrip(setup_test_database):
    """Lifecycle: register adds the worker + heartbeat; deregister removes both."""
    from app.database import redis_client

    await sm.register_socket_worker()
    wid = sm._worker_id
    assert await redis_client.sismember(sm._WORKERS_SET, wid)
    assert await redis_client.exists(sm._WORKER_HB_PREFIX + wid)

    await sm.deregister_socket_worker()
    assert not await redis_client.sismember(sm._WORKERS_SET, wid)
    assert not await redis_client.exists(sm._WORKER_HB_PREFIX + wid)


async def test_subscribe_handshake_returns_listening_pubsub(setup_test_database):
    """Readiness handshake: subscribe_force_disconnect returns a pubsub that is
    already subscribed to the channel BEFORE the worker is registered as live."""
    pubsub = await sm.subscribe_force_disconnect()
    try:
        channels = pubsub.channels  # decode_responses → str keys
        ch = sm.FORCE_DISCONNECT_CHANNEL
        assert any((c == ch or c == ch.encode()) for c in channels)
    finally:
        await pubsub.unsubscribe(sm.FORCE_DISCONNECT_CHANNEL)
        await pubsub.aclose()
