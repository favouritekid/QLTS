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


def patch_redis():
    """Apply FakeRedis patches. Call BEFORE importing app modules."""
    redis.asyncio.from_url = _fake_redis_from_url_async
    redis.from_url = _fake_redis_from_url_sync
    log.info("Redis patched with FakeRedis (shared FakeServer for LUA support)")


def get_fake_server():
    """Get the shared FakeServer instance."""
    return _fake_server
