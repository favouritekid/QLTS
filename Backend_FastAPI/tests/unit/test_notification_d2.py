"""
Phase D2: Circuit Breaker — Unit Tests

Covers: breaker trip, half-open recovery, manual reset, delivery task integration.
Updated for dict-based implementation (no aiobreaker internals).
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestCircuitBreakerTrip:
    """Test breaker trips after fail_max failures."""

    @pytest.mark.asyncio
    async def test_breaker_trips_after_fail_max(self):
        """After fail_max failures, channel should be unhealthy."""
        from app.services.notification_circuit_breaker import (
            check_channel_health, record_failure,
            _fail_counters, _breaker_states, _opened_at,
        )

        channel = "_test_trip"
        # Clean state
        _fail_counters.pop(channel, None)
        _breaker_states.pop(channel, None)
        _opened_at.pop(channel, None)

        with patch("app.services.notification_circuit_breaker.settings") as mock_settings, \
             patch("app.services.notification_circuit_breaker._sync_to_redis", new_callable=AsyncMock):
            mock_settings.CIRCUIT_BREAKER_FAIL_MAX = 3
            mock_settings.CIRCUIT_BREAKER_TIMEOUT = 300

            # Initially healthy
            assert await check_channel_health(channel) is True

            # Record 3 failures
            for _ in range(3):
                await record_failure(channel)

            # Now should be open (unhealthy)
            assert await check_channel_health(channel) is False

        # Cleanup
        _fail_counters.pop(channel, None)
        _breaker_states.pop(channel, None)
        _opened_at.pop(channel, None)

    @pytest.mark.asyncio
    async def test_manual_reset_closes_breaker(self):
        """Admin reset should close an open breaker."""
        from app.services.notification_circuit_breaker import (
            check_channel_health, record_failure, reset_breaker,
            _fail_counters, _breaker_states, _opened_at,
        )

        channel = "_test_reset"
        _fail_counters.pop(channel, None)
        _breaker_states.pop(channel, None)
        _opened_at.pop(channel, None)

        with patch("app.services.notification_circuit_breaker.settings") as mock_settings, \
             patch("app.services.notification_circuit_breaker._sync_to_redis", new_callable=AsyncMock):
            mock_settings.CIRCUIT_BREAKER_FAIL_MAX = 2
            mock_settings.CIRCUIT_BREAKER_TIMEOUT = 300

            # Trip the breaker
            for _ in range(2):
                await record_failure(channel)
            assert await check_channel_health(channel) is False

            # Manual reset
            await reset_breaker(channel)
            assert await check_channel_health(channel) is True

        _fail_counters.pop(channel, None)
        _breaker_states.pop(channel, None)
        _opened_at.pop(channel, None)

    @pytest.mark.asyncio
    async def test_counter_resets_on_trip(self):
        """M4: fail counter should reset to 0 when breaker trips to open."""
        from app.services.notification_circuit_breaker import (
            record_failure, _fail_counters, _breaker_states, _opened_at,
        )

        channel = "_test_m4"
        _fail_counters.pop(channel, None)
        _breaker_states.pop(channel, None)
        _opened_at.pop(channel, None)

        with patch("app.services.notification_circuit_breaker.settings") as mock_settings, \
             patch("app.services.notification_circuit_breaker._sync_to_redis", new_callable=AsyncMock):
            mock_settings.CIRCUIT_BREAKER_FAIL_MAX = 3
            mock_settings.CIRCUIT_BREAKER_TIMEOUT = 300

            for _ in range(3):
                await record_failure(channel)

            assert _breaker_states[channel] == "open"
            assert _fail_counters[channel] == 0  # Reset after trip

        _fail_counters.pop(channel, None)
        _breaker_states.pop(channel, None)
        _opened_at.pop(channel, None)


class TestCircuitBreakerState:
    """Test state reporting functions."""

    def test_get_all_breaker_states_returns_canonical_channels(self):
        """get_all_breaker_states includes browser, email, zalo, sms."""
        from app.services.notification_circuit_breaker import get_all_breaker_states

        states = get_all_breaker_states()
        channels = {s["channel"] for s in states}
        assert {"browser", "email", "zalo", "sms"}.issubset(channels)

    def test_get_breaker_state_has_expected_fields(self):
        """State dict has required fields."""
        from app.services.notification_circuit_breaker import get_breaker_state

        state = get_breaker_state("email")
        assert "channel" in state
        assert "state" in state
        assert "fail_count" in state
        assert "fail_max" in state
        assert "timeout_duration" in state


class TestBreakerDeliveryIntegration:
    """Test that circuit_breaker_open is transient (allows retry)."""

    def test_circuit_breaker_open_is_transient(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("circuit_breaker_open") is False
