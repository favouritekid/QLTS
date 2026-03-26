"""
Phase D2: Circuit Breaker — Unit Tests

Covers: breaker trip, half-open recovery, manual reset, delivery task integration.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestCircuitBreakerTrip:
    """Test breaker trips after fail_max failures."""

    @pytest.mark.asyncio
    async def test_breaker_trips_after_fail_max(self):
        """After fail_max failures, channel should be unhealthy."""
        from app.services.notification_circuit_breaker import (
            check_channel_health, record_failure, get_breaker, _breakers,
        )

        # Use a test channel to avoid polluting real breakers
        channel = "_test_trip"
        _breakers.pop(channel, None)

        with patch("app.services.notification_circuit_breaker.settings") as mock_settings:
            mock_settings.CIRCUIT_BREAKER_FAIL_MAX = 3
            mock_settings.CIRCUIT_BREAKER_TIMEOUT = 300

        # Force create fresh breaker with low threshold
        from aiobreaker import CircuitBreaker
        _breakers[channel] = CircuitBreaker(fail_max=3, timeout_duration=300, name=f"test_{channel}")

        with patch("app.services.notification_circuit_breaker._sync_breaker_to_redis", new_callable=AsyncMock):
            # Initially healthy
            assert await check_channel_health(channel) is True

            # Record 3 failures
            for _ in range(3):
                await record_failure(channel)

            # Now should be open (unhealthy)
            assert await check_channel_health(channel) is False

        # Cleanup
        _breakers.pop(channel, None)

    @pytest.mark.asyncio
    async def test_manual_reset_closes_breaker(self):
        """Admin reset should close an open breaker."""
        from app.services.notification_circuit_breaker import (
            check_channel_health, record_failure, reset_breaker, _breakers,
        )
        from aiobreaker import CircuitBreaker

        channel = "_test_reset"
        _breakers[channel] = CircuitBreaker(fail_max=2, timeout_duration=300, name=f"test_{channel}")

        with patch("app.services.notification_circuit_breaker._sync_breaker_to_redis", new_callable=AsyncMock):
            # Trip the breaker
            for _ in range(2):
                await record_failure(channel)
            assert await check_channel_health(channel) is False

            # Manual reset
            await reset_breaker(channel)
            assert await check_channel_health(channel) is True

        _breakers.pop(channel, None)


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
