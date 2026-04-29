"""Per-process in-memory rate limit fallback for Redis-down windows.

Used by Zalo Bot webhook + link-code endpoints when ``safe_redis_incr``
returns ``None`` (Redis circuit breaker open). Without this, those
endpoints fail OPEN on Redis loss — letting an attacker DoS the bot's
send_message quota or generate unbounded link codes.

Properties:
- Per-process counters (no cross-worker coordination). With N gunicorn
  workers, an attacker effectively gets ``N × limit`` per window. Still
  bounded — much better than fail-open.
- ``time.monotonic()`` based windowing. Counter resets when the window
  expires; no background sweep, evictions happen on next access.
- Thread-safe via ``threading.Lock`` (gunicorn workers are processes,
  but uvicorn inside them may dispatch on a thread pool).
- Worker restart loses counters — acceptable, since the scope is
  "Redis briefly down". Restart pattern is also a natural reset.

NOT a replacement for Redis-backed limiting. Only kicks in when Redis
is unavailable — Redis-backed counters are still the primary defense.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict


@dataclass
class _Bucket:
    count: int
    window_start: float


# Soft cap on the bucket dict so an attacker rotating chat_ids during a
# Redis outage can't blow up RSS. When exceeded, we sweep expired
# buckets first; if still over after sweep, new keys fail-closed (return
# limit+1 to signal "block"). 10k chat_ids per process is well above
# normal usage but well below memory pressure.
_MAX_BUCKETS = 10_000


class InMemoryRateLimiter:
    """Fixed-window per-key counter. Window resets on first request after
    expiry, so behavior matches Redis ``INCR`` + ``EXPIRE`` semantics.
    """

    def __init__(self) -> None:
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _sweep_expired(self, now: float, window_seconds: int) -> None:
        """Drop buckets whose window has fully expired. Called only when
        the dict hits the soft cap — sweeping every call would be O(N)
        per request.
        """
        expired = [
            k
            for k, b in self._buckets.items()
            if now - b.window_start >= window_seconds
        ]
        for k in expired:
            self._buckets.pop(k, None)

    def incr(self, key: str, window_seconds: int) -> int:
        """Increment the counter for ``key`` and return the new value.

        Resets the window if ``window_seconds`` have passed since the
        bucket's window start. Caller compares the returned value to
        the limit and decides whether to allow or block.

        When the dict is at ``_MAX_BUCKETS``, expired buckets are swept;
        if the dict is still full after the sweep, new keys return
        ``window_seconds + 1`` (a sentinel guaranteed > any sane limit)
        so they fail closed without inserting a new bucket.
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= _MAX_BUCKETS:
                    self._sweep_expired(now, window_seconds)
                    if len(self._buckets) >= _MAX_BUCKETS:
                        # Memory pressure — fail closed for unknown keys.
                        # Return a large sentinel so callers' ``> limit``
                        # comparisons evaluate True regardless of limit.
                        return _MAX_BUCKETS
                bucket = _Bucket(count=1, window_start=now)
                self._buckets[key] = bucket
                return 1
            if now - bucket.window_start >= window_seconds:
                bucket.count = 1
                bucket.window_start = now
                return 1
            bucket.count += 1
            return bucket.count

    def reset(self) -> None:
        """Reset all buckets — test-only escape hatch."""
        with self._lock:
            self._buckets.clear()


# Module-level singleton — one shared limiter per process.
_limiter = InMemoryRateLimiter()


def fallback_incr(key: str, window_seconds: int) -> int:
    """Increment ``key`` in the per-process fallback limiter.

    Returns the new count for the current window. Use this only when
    Redis is unavailable (``safe_redis_incr`` returned None).
    """
    return _limiter.incr(key, window_seconds)


def reset_for_tests() -> None:
    """Reset the singleton — call from test setUp/teardown."""
    _limiter.reset()
