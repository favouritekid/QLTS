"""F-2: in-memory fallback rate limiter unit tests.

Validates the per-process counter used by Zalo Bot endpoints when Redis
is unavailable. The fallback prevents fail-OPEN on Redis loss.
"""
from __future__ import annotations

import pytest

from app.utils.inmemory_rate_limit import (
    InMemoryRateLimiter,
    fallback_incr,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_for_tests()
    yield
    reset_for_tests()


class TestInMemoryRateLimiter:
    def test_first_increment_returns_one(self):
        rl = InMemoryRateLimiter()
        assert rl.incr("k1", 60) == 1

    def test_increments_within_window(self):
        rl = InMemoryRateLimiter()
        for expected in range(1, 6):
            assert rl.incr("k1", 60) == expected

    def test_separate_keys_have_independent_counters(self):
        rl = InMemoryRateLimiter()
        assert rl.incr("a", 60) == 1
        assert rl.incr("b", 60) == 1
        assert rl.incr("a", 60) == 2

    def test_window_expiry_resets_counter(self, monkeypatch):
        # Patch time.monotonic so we can simulate a window roll-over without
        # sleeping. Use a list to allow mutation from the patch closure.
        clock = [1000.0]
        monkeypatch.setattr(
            "app.utils.inmemory_rate_limit.time.monotonic", lambda: clock[0]
        )
        rl = InMemoryRateLimiter()
        assert rl.incr("k", 60) == 1
        assert rl.incr("k", 60) == 2
        clock[0] += 60.1  # Window has rolled over.
        assert rl.incr("k", 60) == 1, "should reset to 1 after window expiry"

    def test_reset_clears_all_buckets(self):
        rl = InMemoryRateLimiter()
        rl.incr("a", 60)
        rl.incr("b", 60)
        rl.reset()
        assert rl.incr("a", 60) == 1
        assert rl.incr("b", 60) == 1

    def test_soft_cap_sweeps_expired_then_fails_closed(self, monkeypatch):
        """Attacker rotating chat_ids during Redis outage cannot blow
        memory: dict caps at _MAX_BUCKETS, expired entries sweep first,
        then new keys fail closed.
        """
        from app.utils import inmemory_rate_limit as ir

        # Shrink the cap for the test so we don't have to insert 10k keys.
        monkeypatch.setattr(ir, "_MAX_BUCKETS", 5)
        clock = [1000.0]
        monkeypatch.setattr(
            "app.utils.inmemory_rate_limit.time.monotonic", lambda: clock[0]
        )

        rl = ir.InMemoryRateLimiter()
        # Fill cap with non-expired entries.
        for i in range(5):
            assert rl.incr(f"k{i}", 60) == 1

        # 6th unique key with all entries still fresh → fail closed
        # (returns sentinel >= cap so callers' "> limit" evaluates True).
        result = rl.incr("k_new", 60)
        assert result >= 5, "new key beyond cap must fail closed"

        # Roll the clock so half the original keys expire, then a new
        # key should succeed (sweep clears expired entries first).
        clock[0] += 60.1
        # k0..k4 windows are now expired. New key triggers sweep.
        assert rl.incr("k_after_sweep", 60) == 1


class TestFallbackIncrSingleton:
    def test_singleton_increments_across_calls(self):
        assert fallback_incr("test:k", 60) == 1
        assert fallback_incr("test:k", 60) == 2
        assert fallback_incr("test:k", 60) == 3

    def test_reset_for_tests_clears_singleton(self):
        fallback_incr("test:k", 60)
        fallback_incr("test:k", 60)
        reset_for_tests()
        assert fallback_incr("test:k", 60) == 1
