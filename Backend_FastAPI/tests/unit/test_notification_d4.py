"""
Phase D4: IDOR Scoping for Delivery Ops — Unit Tests

Covers: DeliveryScopeFilter resolution, repo scope filtering.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDeliveryScopeFilter:
    """Test scope filter construction for different roles."""

    def test_scope_filter_all_for_admin(self):
        """Admin → scope_kind='all', allowed_user_ids=None."""
        from app.core.deps import DeliveryScopeFilter

        scope = DeliveryScopeFilter(scope_kind="all")
        assert scope.scope_kind == "all"
        assert scope.allowed_user_ids is None

    def test_scope_filter_unit_for_manager(self):
        """Manager → scope_kind='unit', allowed_user_ids=[...] from hierarchy."""
        from app.core.deps import DeliveryScopeFilter

        scope = DeliveryScopeFilter(scope_kind="unit", allowed_user_ids=[1, 2, 3])
        assert scope.scope_kind == "unit"
        assert scope.allowed_user_ids == [1, 2, 3]

    def test_scope_filter_self_for_officer(self):
        """Officer → scope_kind='self', allowed_user_ids=[self.id]."""
        from app.core.deps import DeliveryScopeFilter

        scope = DeliveryScopeFilter(scope_kind="self", allowed_user_ids=[42])
        assert scope.scope_kind == "self"
        assert scope.allowed_user_ids == [42]


class TestRepoScopeFilter:
    """Test that repo methods accept and apply allowed_user_ids."""

    @pytest.mark.asyncio
    async def test_list_deliveries_accepts_allowed_user_ids(self):
        """list_deliveries param allowed_user_ids is accepted."""
        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

        mock_db = AsyncMock()
        # Mock execute to return empty results
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = NotificationDeliveryRepository(mock_db)
        # Should not raise
        records, total = await repo.list_deliveries(
            allowed_user_ids=[1, 2, 3],
        )
        assert total == 0
        assert records == []

    @pytest.mark.asyncio
    async def test_get_aggregate_stats_accepts_allowed_user_ids(self):
        """get_aggregate_stats param allowed_user_ids is accepted."""
        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = NotificationDeliveryRepository(mock_db)
        # Should not raise - verifies param exists
        stats = await repo.get_aggregate_stats(allowed_user_ids=[1])
        assert "total" in stats

    @pytest.mark.asyncio
    async def test_get_failure_summary_accepts_allowed_user_ids(self):
        """get_failure_summary param allowed_user_ids is accepted."""
        from app.repositories.notification_delivery_repository import NotificationDeliveryRepository

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        repo = NotificationDeliveryRepository(mock_db)
        summary = await repo.get_failure_summary(allowed_user_ids=[1])
        assert "total_failures" in summary
