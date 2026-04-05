"""
Phase D3: Automated Alerting — Unit Tests

Covers: failure rate alert, backlog alert, webhook lag alert, breaker alert, dedup.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFailureRateAlert:
    """Test failure rate threshold check."""

    @pytest.mark.asyncio
    async def test_fires_when_rate_exceeds_threshold(self):
        from app.services.notification_alert_service import check_failure_rate_alert

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.NotificationDeliveryRepository"
        ) as MockRepo, patch(
            "app.services.notification_alert_service.settings"
        ) as mock_settings:
            mock_settings.ALERT_FAILURE_RATE_THRESHOLD = 0.20
            repo = AsyncMock()
            repo.get_failure_rate = AsyncMock(return_value=0.35)
            MockRepo.return_value = repo

            result = await check_failure_rate_alert(mock_db)
            assert result is not None
            assert result["alert_type"] == "failure_rate_high"

    @pytest.mark.asyncio
    async def test_none_when_under_threshold(self):
        from app.services.notification_alert_service import check_failure_rate_alert

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.NotificationDeliveryRepository"
        ) as MockRepo, patch(
            "app.services.notification_alert_service.settings"
        ) as mock_settings:
            mock_settings.ALERT_FAILURE_RATE_THRESHOLD = 0.20
            repo = AsyncMock()
            repo.get_failure_rate = AsyncMock(return_value=0.05)
            MockRepo.return_value = repo

            result = await check_failure_rate_alert(mock_db)
            assert result is None


class TestBacklogAlert:
    """Test queued backlog threshold."""

    @pytest.mark.asyncio
    async def test_fires_when_backlog_exceeds_threshold(self):
        from app.services.notification_alert_service import check_backlog_alert

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.NotificationDeliveryRepository"
        ) as MockRepo, patch(
            "app.services.notification_alert_service.settings"
        ) as mock_settings:
            mock_settings.ALERT_BACKLOG_THRESHOLD = 500
            repo = AsyncMock()
            repo.get_queued_backlog_count = AsyncMock(return_value=750)
            MockRepo.return_value = repo

            result = await check_backlog_alert(mock_db)
            assert result is not None
            assert result["alert_type"] == "backlog_high"

    @pytest.mark.asyncio
    async def test_none_when_under_threshold(self):
        from app.services.notification_alert_service import check_backlog_alert

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.NotificationDeliveryRepository"
        ) as MockRepo, patch(
            "app.services.notification_alert_service.settings"
        ) as mock_settings:
            mock_settings.ALERT_BACKLOG_THRESHOLD = 500
            repo = AsyncMock()
            repo.get_queued_backlog_count = AsyncMock(return_value=100)
            MockRepo.return_value = repo

            result = await check_backlog_alert(mock_db)
            assert result is None


class TestBreakerAlert:
    """Test circuit breaker open alert."""

    @pytest.mark.asyncio
    async def test_fires_when_breaker_open(self):
        from app.services.notification_alert_service import check_breaker_alert

        with patch(
            "app.services.notification_alert_service.get_all_breaker_states"
        ) as mock_states:
            mock_states.return_value = [
                {"channel": "email", "state": "closed"},
                {"channel": "zalo", "state": "open"},
            ]

            result = await check_breaker_alert()
            assert result is not None
            assert result["alert_type"] == "breaker_open"
            assert "zalo" in result["details"]["open_channels"]

    @pytest.mark.asyncio
    async def test_none_when_all_closed(self):
        from app.services.notification_alert_service import check_breaker_alert

        with patch(
            "app.services.notification_alert_service.get_all_breaker_states"
        ) as mock_states:
            mock_states.return_value = [
                {"channel": "email", "state": "closed"},
                {"channel": "zalo", "state": "closed"},
            ]

            result = await check_breaker_alert()
            assert result is None


class TestAlertDedup:
    """Test that same alert type within 1h is deduped (SET NX pattern)."""

    @pytest.mark.asyncio
    async def test_dedup_prevents_duplicate_alert(self):
        from app.services.notification_alert_service import run_all_checks

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.check_failure_rate_alert",
            new_callable=AsyncMock,
        ) as mock_check, patch(
            "app.services.notification_alert_service._try_set_dedup",
            new_callable=AsyncMock,
        ) as mock_dedup, patch(
            "app.services.notification_alert_service.check_backlog_alert",
            new_callable=AsyncMock, return_value=None,
        ), patch(
            "app.services.notification_alert_service.check_webhook_lag_alert",
            new_callable=AsyncMock, return_value=None,
        ), patch(
            "app.services.notification_alert_service.check_breaker_alert",
            new_callable=AsyncMock, return_value=None,
        ):
            mock_check.return_value = {
                "alert_type": "failure_rate_high",
                "severity": "warning",
                "message": "test",
                "details": {},
            }
            # First call: SET NX succeeds (not deduped) → fires
            mock_dedup.return_value = True
            alerts = await run_all_checks(mock_db)
            assert len(alerts) == 1

            # Second call: SET NX fails (already exists) → suppressed
            mock_dedup.return_value = False
            alerts = await run_all_checks(mock_db)
            assert len(alerts) == 0
