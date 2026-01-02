# tests/services/test_activity_service.py
"""
Unit tests for activity_service.py

Tests the refactored service functions that use ActivityRepository.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import activity_service
from app import models, schemas


class TestLogActivity:
    """Tests for log_activity function."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_log_activity_returns_tuple(self, mock_db):
        """Test that log_activity returns (log, callback) tuple."""
        result = await activity_service.log_activity(
            db=mock_db,
            action="test_action",
            resource_type="test",
        )
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        # First element should be UserActivityLog
        assert isinstance(result[0], models.UserActivityLog)
        # Second element should be callable
        assert callable(result[1])

    @pytest.mark.asyncio
    async def test_log_activity_creates_log_with_correct_data(self, mock_db):
        """Test that log_activity creates log with all provided data."""
        log, callback = await activity_service.log_activity(
            db=mock_db,
            action="login",
            resource_type="user",
            actor_id=123,
            target_user_id=456,
            resource_id=789,
            description="User logged in",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )
        
        assert log.action == "login"
        assert log.resource_type == "user"
        assert log.actor_id == 123
        assert log.target_user_id == 456
        assert log.resource_id == 789
        assert log.description == "User logged in"
        assert log.ip_address == "192.168.1.1"
        assert log.user_agent == "Mozilla/5.0"

    @pytest.mark.asyncio
    async def test_log_activity_calls_flush_and_refresh(self, mock_db):
        """Test that log_activity calls db.flush() and db.refresh()."""
        await activity_service.log_activity(
            db=mock_db,
            action="test",
            resource_type="test",
        )
        
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_activity_callback_is_async(self, mock_db):
        """Test that the callback is awaitable."""
        log, callback = await activity_service.log_activity(
            db=mock_db,
            action="test",
            resource_type="test",
        )
        
        # Should not raise
        await callback()


class TestGetActivityLogs:
    """Tests for get_activity_logs function."""

    @pytest.mark.asyncio
    async def test_get_activity_logs_returns_tuple(self):
        """Test that get_activity_logs returns (count, list) tuple."""
        mock_db = AsyncMock()
        
        with patch('app.repositories.activity_repository.ActivityRepository') as MockRepo:
            mock_instance = AsyncMock()
            mock_instance.get_filtered = AsyncMock(return_value=(0, []))
            MockRepo.return_value = mock_instance
            
            # Need to patch at import location
            with patch('app.repositories.ActivityRepository', MockRepo):
                result = await activity_service.get_activity_logs(db=mock_db)
        
                assert isinstance(result, tuple)
                assert len(result) == 2
                assert isinstance(result[0], int)
                assert isinstance(result[1], list)

    @pytest.mark.asyncio
    async def test_get_activity_logs_passes_filters_to_repo(self):
        """Test that filters are passed to repository."""
        mock_db = AsyncMock()
        
        with patch('app.repositories.ActivityRepository') as MockRepo:
            mock_instance = AsyncMock()
            mock_instance.get_filtered = AsyncMock(return_value=(0, []))
            MockRepo.return_value = mock_instance
            
            await activity_service.get_activity_logs(
                db=mock_db,
                skip=10,
                limit=20,
                actor_id=123,
                action="login",
            )
            
            mock_instance.get_filtered.assert_awaited_once_with(
                skip=10,
                limit=20,
                actor_id=123,
                target_user_id=None,
                action="login",
                resource_type=None,
                start_date=None,
                end_date=None,
            )


class TestGetUserStatistics:
    """Tests for get_user_statistics function."""

    @pytest.mark.asyncio
    async def test_get_user_statistics_returns_schema(self):
        """Test that get_user_statistics returns UserStatistics schema."""
        mock_db = AsyncMock()
        
        with patch('app.repositories.ActivityRepository') as MockRepo:
            mock_instance = AsyncMock()
            mock_instance.get_user_counts_by_status = AsyncMock(return_value={
                "active": 100,
                "pending": 5,
                "banned": 2,
            })
            mock_instance.get_total_user_count = AsyncMock(return_value=107)
            mock_instance.get_user_counts_by_role = AsyncMock(return_value={
                "admin": 2,
                "officer": 50,
            })
            mock_instance.get_filtered = AsyncMock(return_value=(0, []))
            MockRepo.return_value = mock_instance
            
            result = await activity_service.get_user_statistics(db=mock_db)
            
            assert isinstance(result, schemas.UserStatistics)
            assert result.total_users == 107
            assert result.active_users == 100
            assert result.pending_users == 5
            assert result.banned_users == 2

    @pytest.mark.asyncio
    async def test_get_user_statistics_uses_repository_methods(self):
        """Test that get_user_statistics uses all repository methods."""
        mock_db = AsyncMock()
        
        with patch('app.repositories.ActivityRepository') as MockRepo:
            mock_instance = AsyncMock()
            mock_instance.get_user_counts_by_status = AsyncMock(return_value={})
            mock_instance.get_total_user_count = AsyncMock(return_value=0)
            mock_instance.get_user_counts_by_role = AsyncMock(return_value={})
            mock_instance.get_filtered = AsyncMock(return_value=(0, []))
            MockRepo.return_value = mock_instance
            
            await activity_service.get_user_statistics(db=mock_db)
            
            mock_instance.get_user_counts_by_status.assert_awaited_once()
            mock_instance.get_total_user_count.assert_awaited_once()
            mock_instance.get_user_counts_by_role.assert_awaited_once()
