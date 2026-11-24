# tests/fixtures/redis.py
"""
Track T: Extracted Redis patching from conftest.py.

Patches redis.asyncio.from_url and redis.from_url with FakeRedis
BEFORE app import. Uses a shared FakeServer for LUA script support.

Must be called at module level in conftest.py before any app imports.
"""
import logging

import redis
import redis.asyncio
import fakeredis
import fakeredis.aioredis

log = logging.getLogger(__name__)

# Shared FakeServer for LUA script support across all test connections
_fake_server = fakeredis.FakeServer()

# Save originals for potential restore
_original_from_url_async = redis.asyncio.from_url
_original_from_url_sync = redis.from_url
# The CLASSMETHOD object itself (not the bound method), so subclasses keep their own ``cls``.
_original_redis_cls_from_url = redis.Redis.__dict__["from_url"]


def _fake_redis_from_url_async(*args, **kwargs):
    """Intercept async redis.from_url → return FakeRedis."""
    decode_responses = kwargs.get("decode_responses", True)
    return fakeredis.aioredis.FakeRedis(
        server=_fake_server, decode_responses=decode_responses
    )


def _fake_redis_from_url_sync(*args, **kwargs):
    """Intercept sync redis.from_url → return FakeStrictRedis."""
    decode_responses = kwargs.get("decode_responses", True)
    return fakeredis.FakeStrictRedis(
        server=_fake_server, decode_responses=decode_responses
    )


def _fake_redis_cls_from_url(cls, url, **kwargs):
    """Intercept the sync CLASSMETHOD ``redis.Redis.from_url`` → FakeStrictRedis on the SAME shared server.

    ``redis.from_url`` above only covers the MODULE function. ``app.socket_manager._heartbeat_thread_run`` builds
    its client with the classmethod, so without this the heartbeat thread refreshed a REAL Redis while
    ``register_socket_worker`` / ``_required_workers`` used FakeRedis: the worker's FakeRedis heartbeat (TTL
    ``_WORKER_HB_TTL``) was never refreshed, and every strict force-disconnect issued more than that TTL after the
    lifespan started raised "No live socket workers" (nightly 23-11, test_q4 khoá hàng loạt). Only ``redis.Redis``
    itself is intercepted; subclasses (fakeredis' own ``from_url``) keep the original behaviour.
    """
    if cls is redis.Redis:
        return fakeredis.FakeStrictRedis(
            server=_fake_server, decode_responses=kwargs.get("decode_responses", False)
        )
    return _original_redis_cls_from_url.__func__(cls, url, **kwargs)


def patch_redis():
    """Apply FakeRedis patches. Call BEFORE importing app modules."""
    redis.asyncio.from_url = _fake_redis_from_url_async
    redis.from_url = _fake_redis_from_url_sync
    redis.Redis.from_url = classmethod(_fake_redis_cls_from_url)
    log.info("Redis patched with FakeRedis (shared FakeServer for LUA support)")


def get_fake_server():
    """Get the shared FakeServer instance."""
    return _fake_server
