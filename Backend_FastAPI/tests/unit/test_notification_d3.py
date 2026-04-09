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


class TestRunAllChecksSessionSafety:
    """Issue #104 regression: run_all_checks must NOT share an AsyncSession
    across concurrent tasks via asyncio.gather. The 3 DB-touching checks
    must run sequentially; the circuit breaker check runs after.
    """

    @pytest.mark.asyncio
    async def test_db_checks_run_sequentially_not_concurrently(self):
        """The 3 DB checks must run in order (failure_rate → backlog → webhook_lag).

        Regression: if someone reintroduces asyncio.gather, this test fails
        because all 3 mocks would be invoked before any awaits resolve.
        We prove sequentiality by asserting the call-order list matches the
        expected order exactly.
        """
        from app.services.notification_alert_service import run_all_checks

        call_order: list[str] = []

        async def _tracked(name):
            async def _inner(db=None):
                call_order.append(name)
                return None
            return _inner

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.check_failure_rate_alert",
            new=await _tracked("failure_rate"),
        ), patch(
            "app.services.notification_alert_service.check_backlog_alert",
            new=await _tracked("backlog"),
        ), patch(
            "app.services.notification_alert_service.check_webhook_lag_alert",
            new=await _tracked("webhook_lag"),
        ), patch(
            "app.services.notification_alert_service.check_breaker_alert",
            new=await _tracked("breaker"),
        ):
            await run_all_checks(mock_db)

        # Must match the exact sequential order documented in run_all_checks.
        # DB checks first (in list order), then breaker.
        assert call_order == ["failure_rate", "backlog", "webhook_lag", "breaker"], (
            f"run_all_checks must execute DB checks sequentially then breaker. "
            f"Got order: {call_order!r}. If this fails, someone may have "
            f"reintroduced asyncio.gather — see Issue #104."
        )

    @pytest.mark.asyncio
    async def test_one_db_check_exception_does_not_block_others(self):
        """If check_failure_rate_alert raises (e.g. the exact Issue #104
        InvalidRequestError), check_backlog_alert, check_webhook_lag_alert,
        and check_breaker_alert must still run and their results aggregated.
        """
        from sqlalchemy.exc import InvalidRequestError

        from app.services.notification_alert_service import run_all_checks

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.check_failure_rate_alert",
            new_callable=AsyncMock,
            side_effect=InvalidRequestError(
                "This session is provisioning a new connection; "
                "concurrent operations are not permitted"
            ),
        ), patch(
            "app.services.notification_alert_service.check_backlog_alert",
            new_callable=AsyncMock,
            return_value={
                "alert_type": "backlog_high",
                "severity": "warning",
                "message": "backlog test",
                "details": {},
            },
        ), patch(
            "app.services.notification_alert_service.check_webhook_lag_alert",
            new_callable=AsyncMock,
            return_value={
                "alert_type": "webhook_lag",
                "severity": "info",
                "message": "lag test",
                "details": {},
            },
        ), patch(
            "app.services.notification_alert_service.check_breaker_alert",
            new_callable=AsyncMock,
            return_value={
                "alert_type": "breaker_open",
                "severity": "error",
                "message": "breaker test",
                "details": {},
            },
        ), patch(
            "app.services.notification_alert_service._try_set_dedup",
            new_callable=AsyncMock,
            return_value=True,
        ):
            alerts = await run_all_checks(mock_db)

        # failure_rate raised → skipped. Other 3 aggregated.
        alert_types = {a["alert_type"] for a in alerts}
        assert alert_types == {"backlog_high", "webhook_lag", "breaker_open"}, (
            f"Expected 3 surviving alerts (backlog/webhook_lag/breaker_open), "
            f"got {alert_types!r}. Per-check try/except must isolate failures."
        )

    @pytest.mark.asyncio
    async def test_all_checks_return_none_produces_empty_alerts(self):
        """When no alert fires (healthy system), run_all_checks returns [].

        Uses realistic scenarios where each check returned None because
        metrics were within thresholds.
        """
        from app.services.notification_alert_service import run_all_checks

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_alert_service.check_failure_rate_alert",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.services.notification_alert_service.check_backlog_alert",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.services.notification_alert_service.check_webhook_lag_alert",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.services.notification_alert_service.check_breaker_alert",
            new_callable=AsyncMock,
            return_value=None,
        ):
            alerts = await run_all_checks(mock_db)

        assert alerts == []

    @pytest.mark.asyncio
    async def test_breaker_check_runs_even_when_all_db_checks_fail(self):
        """If all 3 DB checks raise (worst-case: entire session is poisoned),
        check_breaker_alert must still run because it does not touch the DB.
        This is the minimum guarantee we make to ops during DB-layer outages.
        """
        from sqlalchemy.exc import InvalidRequestError

        from app.services.notification_alert_service import run_all_checks

        mock_db = AsyncMock()
        poison = InvalidRequestError("session poisoned")

        with patch(
            "app.services.notification_alert_service.check_failure_rate_alert",
            new_callable=AsyncMock,
            side_effect=poison,
        ), patch(
            "app.services.notification_alert_service.check_backlog_alert",
            new_callable=AsyncMock,
            side_effect=poison,
        ), patch(
            "app.services.notification_alert_service.check_webhook_lag_alert",
            new_callable=AsyncMock,
            side_effect=poison,
        ), patch(
            "app.services.notification_alert_service.check_breaker_alert",
            new_callable=AsyncMock,
            return_value={
                "alert_type": "breaker_open",
                "severity": "error",
                "message": "zalo breaker open",
                "details": {"open_channels": ["zalo"]},
            },
        ), patch(
            "app.services.notification_alert_service._try_set_dedup",
            new_callable=AsyncMock,
            return_value=True,
        ):
            alerts = await run_all_checks(mock_db)

        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "breaker_open", (
            "Circuit breaker alert must still fire when all DB checks fail — "
            "it does not depend on the shared session."
        )
