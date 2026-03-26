# app/services/notification_circuit_breaker.py
"""
Phase D2: Per-channel circuit breaker for notification delivery.

Auto-disables a channel when sustained failures occur, preventing retry storms.
Uses aiobreaker (already in requirements.txt) with Redis state sync for dashboard.

Pattern follows database.py redis_breaker but per notification channel.
"""
import structlog
from datetime import datetime, timezone
from typing import Dict, List, Optional

from aiobreaker import CircuitBreaker, STATE_CLOSED, STATE_OPEN, STATE_HALF_OPEN

from app.config import settings

log = structlog.get_logger(__name__)

# Per-channel breaker registry (module-level, per worker process)
_breakers: Dict[str, CircuitBreaker] = {}

# Redis key pattern for dashboard visibility
_BREAKER_REDIS_KEY = "notif:breaker:{channel}"


def get_breaker(channel: str) -> CircuitBreaker:
    """Get or create circuit breaker for a channel."""
    if channel not in _breakers:
        _breakers[channel] = CircuitBreaker(
            fail_max=settings.CIRCUIT_BREAKER_FAIL_MAX,
            timeout_duration=settings.CIRCUIT_BREAKER_TIMEOUT,
            name=f"notif_{channel}",
        )
    return _breakers[channel]


async def check_channel_health(channel: str) -> bool:
    """
    Check if channel is healthy (breaker closed or half-open).
    Returns True if OK to send, False if breaker is open.
    """
    breaker = get_breaker(channel)
    return breaker.current_state != STATE_OPEN


async def record_success(channel: str) -> None:
    """Record a successful delivery for the channel breaker."""
    breaker = get_breaker(channel)
    # aiobreaker tracks success internally when calls succeed via call_async
    # For manual tracking, we reset fail counter on success
    if breaker.current_state == STATE_HALF_OPEN:
        # Success in half-open → close the breaker
        breaker._state_storage.reset_state()
        log.info("Circuit breaker closed after success", channel=channel)
    await _sync_breaker_to_redis(channel)


async def record_failure(channel: str) -> None:
    """Record a failed delivery for the channel breaker."""
    breaker = get_breaker(channel)
    breaker._state_storage.increment_counter()

    # Check if we should trip
    if breaker._state_storage.counter >= breaker._fail_max:
        if breaker.current_state != STATE_OPEN:
            breaker._state_storage.state = STATE_OPEN
            breaker._state_storage.opened_at = datetime.now(timezone.utc)
            log.warning(
                "Circuit breaker OPEN — channel disabled",
                channel=channel,
                fail_count=breaker._state_storage.counter,
                fail_max=breaker._fail_max,
            )
    await _sync_breaker_to_redis(channel)


async def reset_breaker(channel: str) -> None:
    """Manual reset — admin action."""
    breaker = get_breaker(channel)
    breaker._state_storage.reset_state()
    await _sync_breaker_to_redis(channel)
    log.info("Circuit breaker manually reset", channel=channel)


def get_breaker_state(channel: str) -> dict:
    """Get state for a single breaker."""
    breaker = get_breaker(channel)
    state = str(breaker.current_state)
    storage = breaker._state_storage
    return {
        "channel": channel,
        "state": state,
        "fail_count": getattr(storage, "counter", 0),
        "fail_max": breaker._fail_max,
        "timeout_duration": breaker._timeout_duration,
        "opened_at": getattr(storage, "opened_at", None),
    }


def get_all_breaker_states() -> List[dict]:
    """Get states for all known channel breakers."""
    # Ensure all canonical channels have breakers
    for ch in ("browser", "email", "zalo", "sms"):
        get_breaker(ch)
    return [get_breaker_state(ch) for ch in sorted(_breakers.keys())]


async def _sync_breaker_to_redis(channel: str) -> None:
    """Sync breaker state to Redis for cross-worker dashboard visibility."""
    try:
        import json
        from app import database

        redis = await database.get_redis()
        state = get_breaker_state(channel)
        # Serialize datetime
        if state.get("opened_at"):
            state["opened_at"] = state["opened_at"].isoformat()
        await redis.set(
            _BREAKER_REDIS_KEY.format(channel=channel),
            json.dumps(state),
            ex=600,  # 10 min TTL, refreshed on each state change
        )
    except Exception:
        pass  # Best effort — dashboard can still read from in-process state
