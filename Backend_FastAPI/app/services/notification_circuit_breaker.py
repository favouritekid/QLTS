# app/services/notification_circuit_breaker.py
"""
Phase D2: Per-channel circuit breaker for notification delivery.

Redis-backed state for cross-worker consistency.
In-memory aiobreaker as local fast path, Redis as source of truth.
"""
import json
import structlog
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.config import settings

log = structlog.get_logger(__name__)

# Redis key pattern
_BREAKER_REDIS_KEY = "notif:breaker:{channel}"
_BREAKER_REDIS_TTL = 600  # 10 min TTL

# Canonical channels
_CANONICAL_CHANNELS = ("browser", "email", "zalo", "sms")

# In-memory fail counters (per worker process, fast path)
_fail_counters: Dict[str, int] = {}
_breaker_states: Dict[str, str] = {}  # "closed", "open", "half_open"
_opened_at: Dict[str, Optional[datetime]] = {}


async def check_channel_health(channel: str) -> bool:
    """
    Check if channel is healthy. Returns True if OK to send.

    Fast path: in-memory state. Fallback: Redis state.
    """
    # Fast path: check local state
    state = _breaker_states.get(channel, "closed")
    if state == "open":
        # Check if timeout has elapsed → transition to half_open
        opened = _opened_at.get(channel)
        if opened:
            elapsed = (datetime.now(timezone.utc) - opened).total_seconds()
            if elapsed >= settings.CIRCUIT_BREAKER_TIMEOUT:
                _breaker_states[channel] = "half_open"
                await _sync_to_redis(channel)
                return True  # Allow one test request
        return False

    return True  # closed or half_open


async def record_success(channel: str) -> None:
    """Record successful delivery. Resets fail counter, closes breaker if half-open."""
    state = _breaker_states.get(channel, "closed")

    if state == "half_open":
        _breaker_states[channel] = "closed"
        _fail_counters[channel] = 0
        _opened_at[channel] = None
        log.info("Circuit breaker closed after success", channel=channel)

    elif state == "closed":
        # Decay fail counter on success
        if channel in _fail_counters and _fail_counters[channel] > 0:
            _fail_counters[channel] = max(0, _fail_counters[channel] - 1)

    await _sync_to_redis(channel)


async def record_failure(channel: str) -> None:
    """Record failed delivery. Trips breaker if fail_max exceeded."""
    count = _fail_counters.get(channel, 0) + 1
    _fail_counters[channel] = count

    fail_max = settings.CIRCUIT_BREAKER_FAIL_MAX
    state = _breaker_states.get(channel, "closed")

    if count >= fail_max and state != "open":
        _breaker_states[channel] = "open"
        _opened_at[channel] = datetime.now(timezone.utc)
        log.warning(
            "Circuit breaker OPEN — channel disabled",
            channel=channel,
            fail_count=count,
            fail_max=fail_max,
        )

    await _sync_to_redis(channel)


async def reset_breaker(channel: str) -> None:
    """Manual admin reset."""
    _breaker_states[channel] = "closed"
    _fail_counters[channel] = 0
    _opened_at[channel] = None
    await _sync_to_redis(channel)
    log.info("Circuit breaker manually reset", channel=channel)


def get_breaker_state(channel: str) -> dict:
    """Get state for a single breaker."""
    state = _breaker_states.get(channel, "closed")

    # Auto-transition open→half_open if timeout elapsed
    if state == "open":
        opened = _opened_at.get(channel)
        if opened:
            elapsed = (datetime.now(timezone.utc) - opened).total_seconds()
            if elapsed >= settings.CIRCUIT_BREAKER_TIMEOUT:
                state = "half_open"

    return {
        "channel": channel,
        "state": state,
        "fail_count": _fail_counters.get(channel, 0),
        "fail_max": settings.CIRCUIT_BREAKER_FAIL_MAX,
        "timeout_duration": settings.CIRCUIT_BREAKER_TIMEOUT,
        "opened_at": _opened_at.get(channel),
    }


def get_all_breaker_states() -> List[dict]:
    """Get states for all canonical channels."""
    return [get_breaker_state(ch) for ch in _CANONICAL_CHANNELS]


async def _sync_to_redis(channel: str) -> None:
    """Sync breaker state to Redis for cross-worker visibility."""
    try:
        from app import database
        redis = await database.get_redis()
        state = get_breaker_state(channel)
        if state.get("opened_at"):
            state["opened_at"] = state["opened_at"].isoformat()
        await redis.set(
            _BREAKER_REDIS_KEY.format(channel=channel),
            json.dumps(state),
            ex=_BREAKER_REDIS_TTL,
        )
    except Exception as e:
        log.warning("Failed to sync breaker state to Redis", channel=channel, error=str(e))
