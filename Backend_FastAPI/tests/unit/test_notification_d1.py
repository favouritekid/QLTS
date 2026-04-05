"""
Phase D1: Quota/Budget System — Unit Tests

Covers: quota check, record_send, sync_zalo_quota, delivery task quota gate.
Strategy: test service functions with mocked DB/Redis, following C2 patterns.
"""

import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# D1-1: Quota check logic
# ---------------------------------------------------------------------------

class TestQuotaCheck:
    """Test check_quota service function."""

    @pytest.mark.asyncio
    async def test_check_quota_allowed_when_under_limit(self):
        """Quota available → returns True."""
        from app.services.notification_quota_service import check_quota

        mock_db = AsyncMock()
        mock_quota = MagicMock()
        mock_quota.blocked = False
        mock_quota.quota_used = 10
        mock_quota.quota_limit = 500

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo, patch(
            "app.services.notification_quota_service.database"
        ) as mock_database:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)  # Cache miss
            mock_database.get_redis = AsyncMock(return_value=mock_redis)

            repo_instance = AsyncMock()
            repo_instance.is_over_quota = AsyncMock(return_value=False)
            MockRepo.return_value = repo_instance

            result = await check_quota(mock_db, "zalo")
            assert result is True

    @pytest.mark.asyncio
    async def test_check_quota_blocked_when_over_limit(self):
        """Quota exhausted → returns False."""
        from app.services.notification_quota_service import check_quota

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo, patch(
            "app.services.notification_quota_service.database"
        ) as mock_database:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_database.get_redis = AsyncMock(return_value=mock_redis)

            repo_instance = AsyncMock()
            repo_instance.is_over_quota = AsyncMock(return_value=True)
            MockRepo.return_value = repo_instance

            result = await check_quota(mock_db, "zalo")
            assert result is False

    @pytest.mark.asyncio
    async def test_check_quota_uses_redis_cache_ok(self):
        """Redis cache says 'ok' → skip DB check."""
        from app.services.notification_quota_service import check_quota

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo, patch(
            "app.services.notification_quota_service.database"
        ) as mock_database:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value="ok")
            mock_database.get_redis = AsyncMock(return_value=mock_redis)

            result = await check_quota(mock_db, "zalo")
            assert result is True
            # DB should NOT be queried (cache hit)
            MockRepo.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_quota_uses_redis_cache_blocked(self):
        """Redis cache says 'blocked' → skip DB, return False."""
        from app.services.notification_quota_service import check_quota

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo, patch(
            "app.services.notification_quota_service.database"
        ) as mock_database:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value="blocked")
            mock_database.get_redis = AsyncMock(return_value=mock_redis)

            result = await check_quota(mock_db, "zalo")
            assert result is False


# ---------------------------------------------------------------------------
# D1-2: Record send
# ---------------------------------------------------------------------------

class TestRecordSend:
    """Test record_send quota increment."""

    @pytest.mark.asyncio
    async def test_record_send_increments_existing_quota(self):
        """Existing quota row → increment quota_used."""
        from app.services.notification_quota_service import record_send

        mock_db = AsyncMock()
        mock_quota = MagicMock()
        mock_quota.quota_used = 10
        mock_quota.quota_limit = 500

        mock_updated = MagicMock()
        mock_updated.quota_used = 11
        mock_updated.quota_limit = 500

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo:
            repo_instance = AsyncMock()
            repo_instance.get_current_quota = AsyncMock(return_value=mock_quota)
            repo_instance.increment_used = AsyncMock(return_value=mock_updated)
            MockRepo.return_value = repo_instance

            await record_send(mock_db, "zalo")
            repo_instance.increment_used.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_send_auto_creates_quota_row(self):
        """No quota row → auto-create with configured limit."""
        from app.services.notification_quota_service import record_send

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo, patch(
            "app.services.notification_quota_service.settings"
        ) as mock_settings:
            mock_settings.ZALO_DAILY_QUOTA_LIMIT = 500
            repo_instance = AsyncMock()
            repo_instance.get_current_quota = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            await record_send(mock_db, "zalo")
            repo_instance.upsert_quota.assert_awaited_once()
            call_kwargs = repo_instance.upsert_quota.call_args[1]
            assert call_kwargs["quota_limit"] == 500
            assert call_kwargs["quota_used"] == 1


# ---------------------------------------------------------------------------
# D1-3: Sync Zalo quota from provider
# ---------------------------------------------------------------------------

class TestSyncZaloQuota:
    """Test sync_zalo_quota with provider response."""

    @pytest.mark.asyncio
    async def test_sync_zalo_quota_persists_remaining(self):
        """Provider reports quota_remaining → upsert with correct values."""
        from app.services.notification_quota_service import sync_zalo_quota

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo, patch(
            "app.services.notification_quota_service.settings"
        ) as mock_settings, patch(
            "app.services.notification_quota_service.database"
        ) as mock_database:
            mock_settings.ZALO_DAILY_QUOTA_LIMIT = 500
            mock_redis = AsyncMock()
            mock_database.get_redis = AsyncMock(return_value=mock_redis)

            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance

            await sync_zalo_quota(mock_db, quota_remaining=350)

            repo_instance.upsert_quota.assert_awaited_once()
            call_kwargs = repo_instance.upsert_quota.call_args[1]
            assert call_kwargs["quota_remaining"] == 350
            assert call_kwargs["quota_used"] == 150  # 500 - 350
            assert call_kwargs["blocked"] is False

    @pytest.mark.asyncio
    async def test_sync_zalo_quota_blocks_when_zero(self):
        """Provider reports 0 remaining → mark blocked."""
        from app.services.notification_quota_service import sync_zalo_quota

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo, patch(
            "app.services.notification_quota_service.settings"
        ) as mock_settings, patch(
            "app.services.notification_quota_service.database"
        ) as mock_database:
            mock_settings.ZALO_DAILY_QUOTA_LIMIT = 500
            mock_redis = AsyncMock()
            mock_database.get_redis = AsyncMock(return_value=mock_redis)

            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance

            await sync_zalo_quota(mock_db, quota_remaining=0)

            call_kwargs = repo_instance.upsert_quota.call_args[1]
            assert call_kwargs["blocked"] is True

    @pytest.mark.asyncio
    async def test_sync_zalo_quota_ignores_none(self):
        """quota_remaining=None → noop."""
        from app.services.notification_quota_service import sync_zalo_quota

        mock_db = AsyncMock()

        with patch(
            "app.services.notification_quota_service.NotificationQuotaRepository"
        ) as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            await sync_zalo_quota(mock_db, quota_remaining=None)
            repo_instance.upsert_quota.assert_not_awaited()


# ---------------------------------------------------------------------------
# D1-4: Delivery task quota gate
# ---------------------------------------------------------------------------

class TestDeliveryTaskQuotaGate:
    """Test that delivery task checks quota before executing."""

    def test_quota_exhausted_error_is_transient(self):
        """quota_exhausted should NOT be in PERMANENT_ERRORS (allows retry)."""
        from app.tasks.delivery_tasks import _is_permanent_error

        assert _is_permanent_error("quota_exhausted") is False


# ---------------------------------------------------------------------------
# D1-5: Repository layer
# ---------------------------------------------------------------------------

class TestNotificationQuotaRepository:
    """Test repository methods with mocked DB."""

    @pytest.mark.asyncio
    async def test_is_over_quota_false_when_no_record(self):
        """No quota record → not over quota (unlimited)."""
        from app.repositories.notification_quota_repository import NotificationQuotaRepository

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = NotificationQuotaRepository(mock_db)
        result = await repo.is_over_quota("zalo")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_over_quota_true_when_blocked(self):
        """Blocked quota → over quota."""
        from app.repositories.notification_quota_repository import NotificationQuotaRepository

        mock_db = AsyncMock()
        mock_quota = MagicMock()
        mock_quota.blocked = True
        mock_quota.quota_used = 100
        mock_quota.quota_limit = 500
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_quota)
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = NotificationQuotaRepository(mock_db)
        result = await repo.is_over_quota("zalo")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_over_quota_true_when_used_equals_limit(self):
        """Used == limit → over quota."""
        from app.repositories.notification_quota_repository import NotificationQuotaRepository

        mock_db = AsyncMock()
        mock_quota = MagicMock()
        mock_quota.blocked = False
        mock_quota.quota_used = 500
        mock_quota.quota_limit = 500
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_quota)
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = NotificationQuotaRepository(mock_db)
        result = await repo.is_over_quota("zalo")
        assert result is True
