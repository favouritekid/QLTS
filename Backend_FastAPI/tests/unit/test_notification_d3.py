"""
Phase D3: Automated Alerting — Unit Tests

Covers: failure rate alert, backlog alert, webhook lag alert, breaker alert, dedup.
"""

import pytest
from unittest.mock import AsyncMock, patch


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


# =============================================================================
# fix/notification-alert-flood — F-metric: exclude self-referential event
# =============================================================================


class TestHealthChecksExcludeOperationalEvent:
    """The failure-rate + backlog checks must exclude the operational
    ``notification_health_alert`` event so the health task never measures
    its own fan-out (self-feeding loop). See plan Finding 3."""

    @pytest.mark.asyncio
    async def test_failure_rate_passes_operational_exclude(self):
        from app.services.notification_alert_service import (
            check_failure_rate_alert,
            _OPERATIONAL_ALERT_EVENTS,
        )

        # The exclude set must contain ONLY the self-referential event —
        # NOT system_alert (a real admin broadcast post-Approach-Y).
        assert _OPERATIONAL_ALERT_EVENTS == ["notification_health_alert"]

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

            await check_failure_rate_alert(mock_db)
            repo.get_failure_rate.assert_awaited_once_with(
                minutes=30, exclude_events=_OPERATIONAL_ALERT_EVENTS
            )

    @pytest.mark.asyncio
    async def test_backlog_passes_operational_exclude(self):
        from app.services.notification_alert_service import (
            check_backlog_alert,
            _OPERATIONAL_ALERT_EVENTS,
        )

        mock_db = AsyncMock()
        with patch(
            "app.services.notification_alert_service.NotificationDeliveryRepository"
        ) as MockRepo, patch(
            "app.services.notification_alert_service.settings"
        ) as mock_settings:
            mock_settings.ALERT_BACKLOG_THRESHOLD = 500
            repo = AsyncMock()
            repo.get_queued_backlog_count = AsyncMock(return_value=10)
            MockRepo.return_value = repo

            await check_backlog_alert(mock_db)
            repo.get_queued_backlog_count.assert_awaited_once_with(
                exclude_events=_OPERATIONAL_ALERT_EVENTS
            )


# =============================================================================
# fix/notification-alert-flood — task dispatch: event routing + F-info
# =============================================================================


class _FakeSessionCM:
    """Minimal async-context-manager standing in for ``task_db_session()``."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class TestAlertTaskDispatch:
    """``check_notification_alerts`` task: dispatches via NOTIFICATION_HEALTH_ALERT
    (not SYSTEM_ALERT), skips info-severity, respects/skips preference by
    severity, and counts only what it actually dispatched.

    Invoked synchronously (``.apply().get()``) with the alert source and
    dispatcher mocked — same celery-eager idiom as the reminder-task tests.
    Sync test so ``run_async_task`` takes the ``run_until_complete`` branch.
    """

    def _run_task(self, alerts, dispatch_return=None):
        from app.tasks import delivery_tasks

        # Default: safe_dispatch created 1 notification (truthy). Pass [] to
        # simulate "no enabled rule / no recipient / swallowed failure".
        if dispatch_return is None:
            dispatch_return = [1]
        mock_session = AsyncMock()
        dispatch_mock = AsyncMock(return_value=dispatch_return)
        with patch.object(
            delivery_tasks, "task_db_session",
            return_value=_FakeSessionCM(mock_session),
        ), patch(
            "app.services.notification_alert_service.run_all_checks",
            new=AsyncMock(return_value=alerts),
        ), patch(
            "app.services.notification_dispatcher.safe_dispatch",
            new=dispatch_mock,
        ):
            result = delivery_tasks.check_notification_alerts.apply().get()
        return result, dispatch_mock

    def test_warning_and_error_dispatched_info_skipped(self):
        alerts = [
            {"alert_type": "failure_rate_high", "severity": "warning", "message": "warn"},
            {"alert_type": "webhook_lag", "severity": "info", "message": "lag"},
            {"alert_type": "breaker_open", "severity": "error", "message": "breaker"},
        ]
        result, dispatch_mock = self._run_task(alerts)

        assert dispatch_mock.await_count == 2, "info-severity alert must NOT dispatch"
        assert result["fired"] == 2, "metric counts real dispatches, not len(alerts)"
        assert result["skipped_info"] == 1
        assert set(result["types"]) == {"failure_rate_high", "breaker_open"}

    def test_dispatch_uses_health_alert_event_and_payload(self):
        from app.core.events import SystemEvents

        alerts = [
            {"alert_type": "failure_rate_high", "severity": "warning", "message": "warn"}
        ]
        _, dispatch_mock = self._run_task(alerts)

        kwargs = dispatch_mock.await_args.kwargs
        assert kwargs["event"] == SystemEvents.NOTIFICATION_HEALTH_ALERT, (
            "Health alert must dispatch via NOTIFICATION_HEALTH_ALERT, never "
            "SYSTEM_ALERT (which fans out to all_users)."
        )
        assert kwargs["payload"]["alert_type"] == "failure_rate_high"
        assert kwargs["payload"]["severity"] == "warning"
        assert kwargs["payload"]["message"] == "warn"
        assert kwargs["rooms"] == ["role_admin"]
        # warning → respects operator preference (they may opt out)
        assert kwargs["skip_preference_check"] is False

    def test_error_severity_skips_preference_check(self):
        alerts = [
            {"alert_type": "breaker_open", "severity": "error", "message": "breaker"}
        ]
        _, dispatch_mock = self._run_task(alerts)

        kwargs = dispatch_mock.await_args.kwargs
        assert kwargs["skip_preference_check"] is True, (
            "error severity (e.g. breaker_open) must reach operators even if "
            "they muted system-group email."
        )

    def test_all_info_alerts_dispatch_nothing(self):
        alerts = [
            {"alert_type": "webhook_lag", "severity": "info", "message": "lag"}
        ]
        result, dispatch_mock = self._run_task(alerts)

        assert dispatch_mock.await_count == 0
        assert result["fired"] == 0
        assert result["skipped_info"] == 1

    def test_no_alerts_returns_zero(self):
        result, dispatch_mock = self._run_task([])

        assert dispatch_mock.await_count == 0
        assert result["fired"] == 0

    def test_empty_dispatch_result_not_counted_as_fired(self):
        """safe_dispatch returning [] (no synced rule / no resolved recipient /
        swallowed failure) must NOT inflate ``fired`` — otherwise the metric
        masks exactly the fail-silent case the rollout gate watches for
        (notification_health_alert rule not yet in the DB)."""
        alerts = [
            {"alert_type": "failure_rate_high", "severity": "warning", "message": "warn"},
            {"alert_type": "breaker_open", "severity": "error", "message": "breaker"},
        ]
        result, dispatch_mock = self._run_task(alerts, dispatch_return=[])

        assert dispatch_mock.await_count == 2, "dispatch is still attempted"
        assert result["fired"] == 0, "empty dispatch result must not count as fired"
        assert result["types"] == []
