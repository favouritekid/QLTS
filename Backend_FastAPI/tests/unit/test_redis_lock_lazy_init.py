"""Regression: redis_lock client must lazy-init for Celery worker context.

Celery worker boots via `celery -A app.celery_app worker ...` and never
runs FastAPI lifespan main.py:449 init_redis_client(). Before the lazy-
init fix, any task calling acquire_redis_lock() raised RuntimeError.
"""
from unittest.mock import patch

import app.utils.redis_lock as redis_lock_module


def test_get_redis_client_lazy_inits_when_uninitialized():
    """First call from worker context must self-heal, not raise."""
    original = redis_lock_module._redis_client
    redis_lock_module._redis_client = None
    try:
        client = redis_lock_module.get_redis_client()
        assert client is not None
        assert redis_lock_module._redis_client is client
        # Second call returns same cached instance (no double init)
        assert redis_lock_module.get_redis_client() is client
    finally:
        redis_lock_module._redis_client = original


def test_get_redis_client_skips_init_call_when_already_set():
    """FastAPI eager init path is preserved: init_redis_client() is NOT called
    again on subsequent get_redis_client() calls.

    Spy on init_redis_client to catch a regression where someone removes the
    `if _redis_client is None` guard in get_redis_client. A pure
    `assert result is sentinel` would not catch that, because
    init_redis_client() is itself idempotent (redis_lock.py:39) — calling it
    extra times would still return the same client and the assert would pass.
    """
    original = redis_lock_module._redis_client
    sentinel = object()
    redis_lock_module._redis_client = sentinel  # type: ignore[assignment]
    try:
        with patch.object(redis_lock_module, "init_redis_client") as init_spy:
            result = redis_lock_module.get_redis_client()
            assert result is sentinel
            init_spy.assert_not_called()
    finally:
        redis_lock_module._redis_client = original
