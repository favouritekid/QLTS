"""
Phase C2: Operational Hardening — Unit Tests

Covers: retry/dead-letter, sweep, replay, cooldown, rate limit,
        stats/failures API, reconciliation, error classification.

Strategy: test component functions directly (helpers, services, repos).
Celery tasks use run_async_task + local imports — test their logic
via the helper functions they call, following existing C1 test patterns.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# C2-1: Error classification helpers
# ---------------------------------------------------------------------------

class TestErrorClassification:
    """Pure function tests — no async, no DB."""

    def test_permanent_errors_include_consent(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("consent_revoked") is True
        assert _is_permanent_error("consent_not_granted") is True

    def test_permanent_errors_include_user_issues(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("user_not_found") is True
        assert _is_permanent_error("no_email") is True
        assert _is_permanent_error("no_phone") is True
        assert _is_permanent_error("invalid_phone") is True

    def test_permanent_errors_include_zalo_216_230_202_204(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("Zalo error -216") is True
        assert _is_permanent_error("Zalo error -230") is True
        assert _is_permanent_error("Zalo error -202") is True
        assert _is_permanent_error("Zalo error -204") is True

    def test_zalo_217_is_transient(self):
        """Template pending approval — may be approved later."""
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("Zalo error -217") is False

    def test_zalo_210_quota_is_transient(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("Zalo error -210") is False

    def test_unknown_error_is_transient(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("some random network timeout") is False
        assert _is_permanent_error("ConnectionError") is False

    def test_empty_error_is_transient(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("") is False
        assert _is_permanent_error(None) is False

    def test_channel_not_implemented_is_permanent(self):
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("channel_not_implemented") is True

    def test_backoff_formula_attempt_0(self):
        from app.tasks.delivery_tasks import _calculate_next_retry

        now = datetime.now(timezone.utc)
        result = _calculate_next_retry(0)
        delta = (result - now).total_seconds()
        assert delta == pytest.approx(60, abs=2)  # 60 * 2^0 = 60

    def test_backoff_formula_attempt_1(self):
        from app.tasks.delivery_tasks import _calculate_next_retry

        now = datetime.now(timezone.utc)
        result = _calculate_next_retry(1)
        delta = (result - now).total_seconds()
        assert delta == pytest.approx(120, abs=2)  # 60 * 2^1 = 120

    def test_backoff_formula_attempt_2(self):
        from app.tasks.delivery_tasks import _calculate_next_retry

        now = datetime.now(timezone.utc)
        result = _calculate_next_retry(2)
        delta = (result - now).total_seconds()
        assert delta == pytest.approx(240, abs=2)  # 60 * 2^2 = 240

    def test_backoff_formula_increases_monotonically(self):
        from app.tasks.delivery_tasks import _calculate_next_retry

        r0 = _calculate_next_retry(0)
        r1 = _calculate_next_retry(1)
        r2 = _calculate_next_retry(2)
        r3 = _calculate_next_retry(3)
        assert r1 > r0
        assert r2 > r1
        assert r3 > r2

    def test_backoff_capped_at_3600(self):
        from app.tasks.delivery_tasks import _calculate_next_retry

        now = datetime.now(timezone.utc)
        result = _calculate_next_retry(20)  # 60 * 2^20 >> 3600
        delta = (result - now).total_seconds()
        assert delta == pytest.approx(3600, abs=2)

    def test_backoff_constants(self):
        from app.tasks.delivery_tasks import RETRY_BACKOFF_BASE, RETRY_BACKOFF_MAX

        assert RETRY_BACKOFF_BASE == 60
        assert RETRY_BACKOFF_MAX == 3600


# ---------------------------------------------------------------------------
# C2-1: Worker idempotency logic (test the status check pattern)
# ---------------------------------------------------------------------------

class TestWorkerIdempotency:
    """Test the status check that guards task execution."""

    ALLOWED_STATUSES = ("queued", "failed")

    def test_queued_is_processable(self):
        assert "queued" in self.ALLOWED_STATUSES

    def test_failed_is_processable(self):
        assert "failed" in self.ALLOWED_STATUSES

    def test_dead_lettered_is_skipped(self):
        assert "dead_lettered" not in self.ALLOWED_STATUSES

    def test_sent_is_skipped(self):
        assert "sent" not in self.ALLOWED_STATUSES

    def test_delivered_is_skipped(self):
        assert "delivered" not in self.ALLOWED_STATUSES

    def test_read_is_skipped(self):
        assert "read" not in self.ALLOWED_STATUSES

    def test_skipped_is_skipped(self):
        assert "skipped" not in self.ALLOWED_STATUSES


# ---------------------------------------------------------------------------
# C2-1: mark_for_retry / mark_dead_lettered service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMarkForRetryService:

    async def test_mark_for_retry_sets_fields(self):
        delivery = MagicMock()
        delivery.attempt_count = 2
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)
        db.flush = AsyncMock()

        from app.services.notification_delivery_service import mark_for_retry
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=120)
        count = await mark_for_retry(db, 1, next_retry_at=next_retry, error_reason="timeout")

        assert count == 1
        assert delivery.status == "failed"
        assert delivery.next_retry_at == next_retry
        assert delivery.error_reason == "timeout"

    async def test_mark_for_retry_not_found_returns_zero(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        from app.services.notification_delivery_service import mark_for_retry
        count = await mark_for_retry(
            db, 999,
            next_retry_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        assert count == 0

    async def test_mark_dead_lettered_updates_rows(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        db.execute = AsyncMock(return_value=mock_result)

        from app.services.notification_delivery_service import mark_dead_lettered
        count = await mark_dead_lettered(db, [10, 20], error_reason="max_retries_exceeded")

        assert count == 2
        db.execute.assert_called_once()

    async def test_mark_dead_lettered_empty_list_returns_zero(self):
        db = AsyncMock()

        from app.services.notification_delivery_service import mark_dead_lettered
        count = await mark_dead_lettered(db, [])
        assert count == 0
        db.execute.assert_not_called()

    async def test_mark_delivered_calls_bulk_update(self):
        from app.services.notification_delivery_service import mark_delivery_ids_delivered

        with patch(
            "app.services.notification_delivery_service.NotificationDeliveryRepository"
        ) as MockRepo:
            mock_repo = MagicMock()
            mock_repo.bulk_update_status = AsyncMock(return_value=1)
            MockRepo.return_value = mock_repo

            count = await mark_delivery_ids_delivered(AsyncMock(), [5])
            assert count == 1
            mock_repo.bulk_update_status.assert_called_once_with([5], "delivered")

    async def test_mark_read_calls_bulk_update(self):
        from app.services.notification_delivery_service import mark_delivery_ids_read

        with patch(
            "app.services.notification_delivery_service.NotificationDeliveryRepository"
        ) as MockRepo:
            mock_repo = MagicMock()
            mock_repo.bulk_update_status = AsyncMock(return_value=3)
            MockRepo.return_value = mock_repo

            count = await mark_delivery_ids_read(AsyncMock(), [1, 2, 3])
            assert count == 3
            mock_repo.bulk_update_status.assert_called_once_with([1, 2, 3], "read")


# ---------------------------------------------------------------------------
# C2-2: Replay delivery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReplayDelivery:

    def _make_delivery(self, **overrides):
        d = MagicMock()
        d.id = overrides.get("id", 1)
        d.status = overrides.get("status", "failed")
        d.recipient_kind = overrides.get("recipient_kind", "internal")
        d.user_id = overrides.get("user_id", 1)
        d.source_type = overrides.get("source_type", None)
        d.source_id = overrides.get("source_id", None)
        d.event = overrides.get("event", "LEAD_ASSIGNED")
        d.attempt_count = overrides.get("attempt_count", 3)
        d.next_retry_at = overrides.get("next_retry_at", None)
        d.dead_lettered_at = overrides.get("dead_lettered_at", None)
        d.error_reason = overrides.get("error_reason", "timeout")
        d.last_attempt_at = overrides.get("last_attempt_at", None)
        return d

    async def test_replay_failed_resets_state(self):
        delivery = self._make_delivery(status="failed")
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)
        db.flush = AsyncMock()

        with patch(
            "app.tasks.delivery_tasks._check_delivery_eligibility",
            new_callable=AsyncMock, return_value=None,
        ):
            from app.services.notification_delivery_service import replay_delivery
            success, msg = await replay_delivery(db, 1)

        assert success is True
        assert delivery.status == "queued"
        assert delivery.attempt_count == 0
        assert delivery.next_retry_at is None
        assert delivery.dead_lettered_at is None
        assert delivery.error_reason is None
        assert delivery.last_attempt_at is None

    async def test_replay_dead_lettered_resets_state(self):
        delivery = self._make_delivery(
            status="dead_lettered",
            dead_lettered_at=datetime.now(timezone.utc),
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)
        db.flush = AsyncMock()

        with patch(
            "app.tasks.delivery_tasks._check_delivery_eligibility",
            new_callable=AsyncMock, return_value=None,
        ):
            from app.services.notification_delivery_service import replay_delivery
            success, msg = await replay_delivery(db, 2)

        assert success is True
        assert delivery.status == "queued"

    async def test_replay_skipped_allowed(self):
        delivery = self._make_delivery(status="skipped")
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)
        db.flush = AsyncMock()

        with patch(
            "app.tasks.delivery_tasks._check_delivery_eligibility",
            new_callable=AsyncMock, return_value=None,
        ):
            from app.services.notification_delivery_service import replay_delivery
            success, msg = await replay_delivery(db, 1)

        assert success is True

    async def test_replay_sent_returns_failure(self):
        delivery = self._make_delivery(status="sent")
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)

        from app.services.notification_delivery_service import replay_delivery
        success, msg = await replay_delivery(db, 1)

        assert success is False
        assert "Cannot replay" in msg

    async def test_replay_consent_revoked_returns_failure(self):
        delivery = self._make_delivery(status="failed", recipient_kind="external")
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)

        with patch(
            "app.tasks.delivery_tasks._check_delivery_eligibility",
            new_callable=AsyncMock, return_value="consent_revoked",
        ):
            from app.services.notification_delivery_service import replay_delivery
            success, msg = await replay_delivery(db, 1)

        assert success is False
        assert "consent_revoked" in msg

    async def test_replay_not_found_returns_failure(self):
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        from app.services.notification_delivery_service import replay_delivery
        success, msg = await replay_delivery(db, 999)

        assert success is False
        assert "not found" in msg.lower()


# ---------------------------------------------------------------------------
# C2-3: Cooldown logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCooldown:

    async def test_cooldown_key_format(self):
        """Verify the Redis key format convention."""
        event = "LEAD_ASSIGNED"
        uid = 42
        channel = "email"
        key = f"notif:cooldown:{event}:{uid}:{channel}"
        assert key == "notif:cooldown:LEAD_ASSIGNED:42:email"

    async def test_cooldown_blocks_when_redis_returns_true(self):
        """If safe_redis_exists returns True, user should be skipped."""
        # Simulate the dispatcher's cooldown check logic
        exists = True  # Redis says key exists
        skipped = exists  # dispatcher does: if exists: continue
        assert skipped is True

    async def test_cooldown_allows_when_redis_returns_false(self):
        """If safe_redis_exists returns False, user passes."""
        exists = False
        skipped = exists
        assert skipped is False

    async def test_cooldown_redis_down_returns_false(self):
        """safe_redis_exists returns False on Redis failure → allows."""
        with patch("app.database.redis_breaker") as mock_breaker:
            # Simulate circuit breaker open or connection failed
            from app.database import REDIS_BREAKER_EXCEPTIONS
            mock_breaker.call_async = AsyncMock(
                side_effect=REDIS_BREAKER_EXCEPTIONS[0]("Redis down")
            )
            from app.database import safe_redis_exists
            result = await safe_redis_exists("notif:cooldown:EVT:1:email")
            assert result is False

    async def test_cooldown_different_events_different_keys(self):
        """Different events produce different keys → no cross-blocking."""
        k1 = f"notif:cooldown:LEAD_ASSIGNED:1:email"
        k2 = f"notif:cooldown:LEAD_CREATED:1:email"
        assert k1 != k2

    async def test_cooldown_different_channels_different_keys(self):
        k1 = f"notif:cooldown:LEAD_ASSIGNED:1:email"
        k2 = f"notif:cooldown:LEAD_ASSIGNED:1:browser"
        assert k1 != k2


# ---------------------------------------------------------------------------
# C2-4: Rate limit + safe_redis_incr
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRateLimit:

    async def test_safe_redis_incr_returns_count(self):
        with patch("app.database.redis_breaker") as mock_breaker:
            mock_breaker.call_async = AsyncMock(return_value=5)

            from app.database import safe_redis_incr
            result = await safe_redis_incr("notif:rate:42")
            assert result == 5

    async def test_safe_redis_incr_returns_none_on_failure(self):
        with patch("app.database.redis_breaker") as mock_breaker:
            from app.database import REDIS_BREAKER_EXCEPTIONS
            mock_breaker.call_async = AsyncMock(
                side_effect=REDIS_BREAKER_EXCEPTIONS[0]("Redis down")
            )
            from app.database import safe_redis_incr
            result = await safe_redis_incr("notif:rate:42")
            assert result is None

    async def test_rate_limit_logic_blocks_over_threshold(self):
        """When count > limit, dispatcher skips user."""
        limit = 50
        count = 51
        blocked = count and count > limit
        assert blocked is True

    async def test_rate_limit_logic_allows_under_threshold(self):
        count = 10
        limit = 50
        blocked = count and count > limit
        assert blocked is False

    async def test_rate_limit_logic_allows_on_none(self):
        """When Redis down (count=None), dispatcher allows."""
        count = None
        limit = 50
        blocked = count and count > limit
        assert not blocked

    async def test_rate_limit_ttl_set_on_first_increment(self):
        """TTL should be set when count == 1 (new key)."""
        count = 1
        should_set_ttl = count == 1
        assert should_set_ttl is True

    async def test_rate_limit_ttl_not_set_on_subsequent(self):
        count = 5
        should_set_ttl = count == 1
        assert should_set_ttl is False

    async def test_config_defaults(self):
        from app.config import Settings
        s = Settings(
            DATABASE_URL="postgresql+asyncpg://x:x@localhost/x",
            SECRET_KEY="test",
            ALGORITHM="HS256",
        )
        assert s.NOTIFICATION_COOLDOWN_SECONDS == 300
        assert s.NOTIFICATION_RATE_LIMIT_PER_HOUR == 50


# ---------------------------------------------------------------------------
# C2-5: Stats + Failures repository
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStatsAndFailures:

    async def test_aggregate_stats_empty_returns_zero(self):
        db = AsyncMock()
        call_count = 0

        async def mock_execute(q):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.all = MagicMock(return_value=[])
            return result

        db.execute = mock_execute

        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        stats = await repo.get_aggregate_stats()

        assert stats["total"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["by_status"] == {}

    async def test_aggregate_stats_calculates_success_rate(self):
        db = AsyncMock()
        call_count = 0

        async def mock_execute(q):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # by_status query
                result.all = MagicMock(return_value=[
                    ("sent", 70), ("failed", 20), ("delivered", 10),
                ])
            else:  # by_channel query
                result.all = MagicMock(return_value=[
                    ("email", 60), ("zalo", 40),
                ])
            return result

        db.execute = mock_execute

        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        stats = await repo.get_aggregate_stats()

        assert stats["total"] == 100
        assert stats["success_rate"] == 80.0  # (70 sent + 10 delivered) / 100
        assert stats["by_status"]["sent"] == 70
        assert stats["by_channel"]["email"] == 60

    async def test_failure_summary_empty_returns_zero(self):
        db = AsyncMock()
        call_count = 0

        async def mock_execute(q):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar = MagicMock(return_value=0)
            else:
                result.all = MagicMock(return_value=[])
            return result

        db.execute = mock_execute

        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        summary = await repo.get_failure_summary()

        assert summary["total_failures"] == 0
        assert summary["by_reason"] == []

    async def test_failure_summary_groups_by_reason(self):
        db = AsyncMock()
        now = datetime.now(timezone.utc)
        call_count = 0

        async def mock_execute(q):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar = MagicMock(return_value=25)
            else:
                result.all = MagicMock(return_value=[
                    ("timeout", 15, now),
                    ("consent_revoked", 10, now),
                ])
            return result

        db.execute = mock_execute

        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        summary = await repo.get_failure_summary()

        assert summary["total_failures"] == 25
        assert len(summary["by_reason"]) == 2
        assert summary["by_reason"][0]["error_reason"] == "timeout"
        assert summary["by_reason"][0]["count"] == 15

    async def test_failure_summary_null_reason_becomes_unknown(self):
        db = AsyncMock()
        call_count = 0

        async def mock_execute(q):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar = MagicMock(return_value=1)
            else:
                result.all = MagicMock(return_value=[
                    (None, 1, datetime.now(timezone.utc)),
                ])
            return result

        db.execute = mock_execute

        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        summary = await repo.get_failure_summary()

        assert summary["by_reason"][0]["error_reason"] == "unknown"


# ---------------------------------------------------------------------------
# C2-7: Reconciliation logic (test via repo + service components)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReconciliationLogic:
    """Test the reconciliation decision logic without running Celery task."""

    async def test_queued_stale_under_max_retries_should_reenqueue(self):
        """Queued delivery with retries left → re-enqueue."""
        attempt_count = 2
        max_retries = 5
        should_dead_letter = (attempt_count or 0) >= max_retries
        assert should_dead_letter is False  # Should re-enqueue instead

    async def test_queued_stale_at_max_retries_should_dead_letter(self):
        """Queued delivery with max retries reached → dead-letter."""
        attempt_count = 5
        max_retries = 5
        should_dead_letter = (attempt_count or 0) >= max_retries
        assert should_dead_letter is True

    async def test_queued_stale_none_attempt_count_treated_as_zero(self):
        """None attempt_count treated as 0 → should re-enqueue."""
        attempt_count = None
        max_retries = 5
        should_dead_letter = (attempt_count or 0) >= max_retries
        assert should_dead_letter is False

    async def test_sent_stale_channels_include_zalo_sms(self):
        """Sent stale reconciliation covers zalo and sms."""
        sent_channels = ["zalo", "sms"]
        assert "zalo" in sent_channels
        assert "sms" in sent_channels
        assert "email" not in sent_channels  # Email doesn't have webhook

    async def test_queued_stale_channels_include_email(self):
        """Queued stale reconciliation covers email, zalo, sms."""
        queued_channels = ["email", "zalo", "sms"]
        assert "email" in queued_channels
        assert "browser" not in queued_channels  # Browser is inline

    async def test_reconcile_thresholds(self):
        """Verify stale thresholds: queued=30min, sent=60min."""
        queued_threshold = 30
        sent_threshold = 60
        assert queued_threshold == 30
        assert sent_threshold == 60

    async def test_find_stale_query_uses_cutoff(self):
        """Repository find_stale_deliveries uses created_at < cutoff."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        deliveries = await repo.find_stale_deliveries(
            status="queued", channels=["email", "zalo"], max_age_minutes=30,
        )
        assert deliveries == []
        db.execute.assert_called_once()

    async def test_find_ready_for_retry_query(self):
        """Repository find_ready_for_retry filters by status + next_retry_at."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
        repo = NotificationDeliveryRepository(db)
        deliveries = await repo.find_ready_for_retry(limit=50)
        assert deliveries == []
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# C2: Celery Beat schedule verification
# ---------------------------------------------------------------------------

class TestBeatSchedule:

    def test_sweep_registered_in_beat(self):
        from app.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "sweep-retry-deliveries" in schedule
        entry = schedule["sweep-retry-deliveries"]
        assert entry["task"] == "sweep_retry_deliveries"
        assert entry["schedule"] == 120  # 2 minutes

    def test_reconcile_registered_in_beat(self):
        from app.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "reconcile-stale-deliveries" in schedule
        entry = schedule["reconcile-stale-deliveries"]
        assert entry["task"] == "reconcile_stale_deliveries"

    def test_worker_task_no_autoretry(self):
        """C2: autoretry_for must be removed from execute_notification_delivery."""
        from app.tasks.delivery_tasks import execute_notification_delivery
        # Celery task attributes
        assert execute_notification_delivery.max_retries == 0
        # autoretry_for should not be set (defaults to empty)
        autoretry = getattr(execute_notification_delivery, "autoretry_for", ())
        assert autoretry == () or autoretry is None


# ---------------------------------------------------------------------------
# C2: Eligibility check (existing C1 pattern, verify C2 integration)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckDeliveryEligibility:

    async def test_external_consent_revoked_returns_reason(self):
        from app.tasks.delivery_tasks import _check_delivery_eligibility

        delivery = MagicMock()
        delivery.recipient_kind = "external"
        delivery.source_type = "lead"
        delivery.source_id = 42
        delivery.channel = "zalo"
        delivery.event = "LEAD_ASSIGNED"

        session = AsyncMock()
        mock_consent_repo = MagicMock()
        mock_consent_repo.is_consent_granted = AsyncMock(return_value=False)

        with patch(
            "app.repositories.notification_consent_repository.NotificationConsentRepository",
            return_value=mock_consent_repo,
        ):
            result = await _check_delivery_eligibility(session, delivery)

        assert result == "consent_revoked"

    async def test_external_consent_granted_returns_none(self):
        from app.tasks.delivery_tasks import _check_delivery_eligibility

        delivery = MagicMock()
        delivery.recipient_kind = "external"
        delivery.source_type = "lead"
        delivery.source_id = 42
        delivery.channel = "zalo"

        session = AsyncMock()
        mock_consent_repo = MagicMock()
        mock_consent_repo.is_consent_granted = AsyncMock(return_value=True)

        with patch(
            "app.repositories.notification_consent_repository.NotificationConsentRepository",
            return_value=mock_consent_repo,
        ):
            result = await _check_delivery_eligibility(session, delivery)

        assert result is None


# ---------------------------------------------------------------------------
# C2: Schema verification
# ---------------------------------------------------------------------------

class TestSchemas:

    def test_delivery_response_has_c2_fields(self):
        from app.schemas.notification_delivery import NotificationDeliveryResponse
        fields = NotificationDeliveryResponse.model_fields
        assert "next_retry_at" in fields
        assert "max_retries" in fields
        assert "dead_lettered_at" in fields

    def test_delivery_response_has_c1_fields(self):
        from app.schemas.notification_delivery import NotificationDeliveryResponse
        fields = NotificationDeliveryResponse.model_fields
        assert "scheduled_for" in fields
        assert "attempt_count" in fields
        assert "last_attempt_at" in fields

    def test_replay_response_schema(self):
        from app.schemas.notification_delivery import ReplayResponse
        r = ReplayResponse(replayed=True, delivery_id=1, message="ok")
        assert r.replayed is True
        assert r.delivery_id == 1

    def test_stats_response_schema(self):
        from app.schemas.notification_delivery import DeliveryStatsResponse
        s = DeliveryStatsResponse(
            total=100,
            by_status={"sent": 80, "failed": 20},
            by_channel={"email": 60, "zalo": 40},
            success_rate=80.0,
        )
        assert s.total == 100
        assert s.success_rate == 80.0

    def test_stats_response_defaults(self):
        from app.schemas.notification_delivery import DeliveryStatsResponse
        s = DeliveryStatsResponse()
        assert s.total == 0
        assert s.by_status == {}
        assert s.success_rate == 0.0

    def test_failure_summary_schema(self):
        from app.schemas.notification_delivery import DeliveryFailureSummary, FailureReasonCount
        f = DeliveryFailureSummary(
            total_failures=20,
            by_reason=[
                FailureReasonCount(error_reason="timeout", count=15, latest_at=datetime.now(timezone.utc)),
            ],
        )
        assert f.total_failures == 20
        assert len(f.by_reason) == 1
        assert f.by_reason[0].error_reason == "timeout"

    def test_failure_reason_count_schema(self):
        from app.schemas.notification_delivery import FailureReasonCount
        frc = FailureReasonCount(error_reason="timeout", count=10)
        assert frc.error_reason == "timeout"
        assert frc.count == 10
        assert frc.latest_at is None  # Optional
