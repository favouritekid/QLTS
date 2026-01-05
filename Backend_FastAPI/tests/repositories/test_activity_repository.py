# tests/unit/repositories/test_activity_repository.py
"""
Unit tests for ActivityRepository

Tests the refactored activity_service.py and activity_repository.py
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.repositories.activity_repository import ActivityRepository


class TestActivityRepository:
    """Tests for ActivityRepository methods."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def repo(self, mock_db):
        """Create repository instance with mock db."""
        return ActivityRepository(mock_db)

    # =========================================================================
    # get_filtered tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_filtered_returns_tuple(self, repo, mock_db):
        """Test that get_filtered returns (count, list) tuple."""
        # Setup mocks
        mock_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=10)),  # count query
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # data query
        ]
        
        result = await repo.get_filtered(skip=0, limit=50)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == 10  # count
        assert result[1] == []  # empty list

    @pytest.mark.asyncio
    async def test_get_filtered_with_actor_filter(self, repo, mock_db):
        """Test filtering by actor_id."""
        mock_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=5)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
        
        result = await repo.get_filtered(skip=0, limit=50, actor_id=123)
        
        # Verify execute was called twice (count + data)
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_get_filtered_with_date_range(self, repo, mock_db):
        """Test filtering by date range."""
        mock_db.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=3)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
        
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        result = await repo.get_filtered(skip=0, limit=50, start_date=start, end_date=end)
        
        assert result[0] == 3

    # =========================================================================
    # _build_filters tests
    # =========================================================================

    def test_build_filters_empty(self, repo):
        """Test building filters with no params."""
        filters = repo._build_filters()
        assert filters == []

    def test_build_filters_with_actor_id(self, repo):
        """Test building filters with actor_id."""
        filters = repo._build_filters(actor_id=123)
        assert len(filters) == 1

    def test_build_filters_with_all_params(self, repo):
        """Test building filters with all parameters."""
        filters = repo._build_filters(
            actor_id=1,
            target_user_id=2,
            action="login",
            resource_type="user",
            start_date=datetime.now(),
            end_date=datetime.now(),
        )
        assert len(filters) == 6

    # =========================================================================
    # User statistics tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_counts_by_status(self, repo, mock_db):
        """Test getting user counts by status."""
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            MagicMock(status="active", count=100),
            MagicMock(status="pending", count=5),
            MagicMock(status="banned", count=2),
        ]))
        mock_db.execute.return_value = mock_result
        
        result = await repo.get_user_counts_by_status()
        
        assert result["active"] == 100
        assert result["pending"] == 5
        assert result["banned"] == 2

    @pytest.mark.asyncio
    async def test_get_total_user_count(self, repo, mock_db):
        """Test getting total user count."""
        mock_db.execute.return_value = MagicMock(scalar=MagicMock(return_value=107))
        
        result = await repo.get_total_user_count()
        
        assert result == 107

    @pytest.mark.asyncio
    async def test_get_user_counts_by_role(self, repo, mock_db):
        """Test getting user counts by role."""
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            MagicMock(role="admin", count=2),
            MagicMock(role="manager", count=10),
            MagicMock(role="officer", count=50),
        ]))
        mock_db.execute.return_value = mock_result
        
        result = await repo.get_user_counts_by_role()
        
        assert result["admin"] == 2
        assert result["manager"] == 10
        assert result["officer"] == 50
