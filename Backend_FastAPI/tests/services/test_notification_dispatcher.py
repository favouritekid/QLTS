# tests/services/test_notification_dispatcher.py
"""
Integration tests for notification dispatcher.

These tests verify the complete flow from event dispatch to notification
creation and Celery task queuing.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.events import SystemEvents
from app.services.notification_dispatcher import (
    dispatch,
    dispatch_to_user,
    dispatch_to_users,
    dispatch_system_alert,
    _apply_deduplication,
)


# =============================================================================
# DISPATCHER TESTS
# =============================================================================

class TestDispatcher:
    """Tests for the main dispatch function."""

    @pytest.mark.asyncio
    @patch("app.services.notification_dispatcher.get_event_config")
    async def test_dispatch_returns_empty_for_unregistered_event(
        self, mock_get_config
    ):
        """Should return empty list for events not in registry."""
        mock_get_config.return_value = None
        db = AsyncMock()

        result = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload={"lead_id": 1}
        )

        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.notification_dispatcher._dispatch_broadcast_task")
    @patch("app.services.notification_dispatcher._bulk_create_notifications")
    @patch("app.services.notification_dispatcher.notification_preference_service")
    @patch("app.services.notification_dispatcher.get_event_config")
    async def test_dispatch_full_flow(
        self,
        mock_get_config,
        mock_pref_service,
        mock_bulk_create,
        mock_dispatch_task
    ):
        """Should execute full dispatch flow."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.resolver.resolve_users = AsyncMock(return_value=[1, 2, 3])
        mock_config.render_title.return_value = "Test Title"
        mock_config.render_message.return_value = "Test Message"
        mock_config.render_link.return_value = "/test"
        mock_config.notification_type = "info"
        mock_config.group.value = "lead"
        mock_config.channels = ["browser", "email"]
        mock_get_config.return_value = mock_config

        mock_pref_service.filter_users_by_group = AsyncMock(return_value=[1, 2, 3])
        mock_bulk_create.return_value = [100, 101, 102]

        db = AsyncMock()
        db.commit = AsyncMock()

        result = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload={"lead_id": 1, "officer_id": 2}
        )

        assert result == [100, 101, 102]
        mock_bulk_create.assert_called_once()
        db.commit.assert_called_once()
        mock_dispatch_task.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.notification_dispatcher.get_event_config")
    async def test_dispatch_returns_empty_when_no_recipients(
        self, mock_get_config
    ):
        """Should return empty list when resolver returns no users."""
        mock_config = MagicMock()
        mock_config.resolver.resolve_users = AsyncMock(return_value=[])
        mock_get_config.return_value = mock_config

        db = AsyncMock()

        result = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNED,
            payload={"lead_id": 1}
        )

        assert result == []

    @pytest.mark.asyncio
    @patch("app.services.notification_dispatcher._dispatch_broadcast_task")
    @patch("app.services.notification_dispatcher._bulk_create_notifications")
    @patch("app.services.notification_dispatcher.get_event_config")
    async def test_dispatch_skip_preference_check(
        self,
        mock_get_config,
        mock_bulk_create,
        mock_dispatch_task
    ):
        """Should skip preference filtering when flag is set."""
        mock_config = MagicMock()
        mock_config.resolver.resolve_users = AsyncMock(return_value=[1, 2])
        mock_config.render_title.return_value = "Title"
        mock_config.render_message.return_value = "Message"
        mock_config.render_link.return_value = None
        mock_config.notification_type = "info"
        mock_config.group.value = "system"
        mock_config.channels = ["browser"]
        mock_get_config.return_value = mock_config

        mock_bulk_create.return_value = [1, 2]

        db = AsyncMock()
        db.commit = AsyncMock()

        result = await dispatch(
            db=db,
            event=SystemEvents.SYSTEM_ALERT,
            payload={"severity": "error", "message": "Test"},
            skip_preference_check=True
        )

        assert result == [1, 2]


# =============================================================================
# DEDUPLICATION TESTS
# =============================================================================

class TestDeduplication:
    """Tests for deduplication logic."""

    @pytest.mark.asyncio
    async def test_deduplication_filters_existing(self):
        """Should filter out users who already have notification."""
        db = AsyncMock()
        # The execute returns a result that has fetchall()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1,), (3,)]  # Users 1 and 3 already have it
        # Make execute return the mock_result directly (not awaitable since we use AsyncMock)
        db.execute = AsyncMock(return_value=mock_result)

        result = await _apply_deduplication(
            db=db,
            user_ids=[1, 2, 3, 4],
            dedupe_key="lead_assigned:123:456"
        )

        assert result == [2, 4]  # Only 2 and 4 don't have it

    @pytest.mark.asyncio
    async def test_deduplication_fail_safe(self):
        """Should return all users on database error."""
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB Error"))

        result = await _apply_deduplication(
            db=db,
            user_ids=[1, 2, 3],
            dedupe_key="test_key"
        )

        # On error, should return all users (fail-safe)
        assert result == [1, 2, 3]


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience wrapper functions."""

    @pytest.mark.asyncio
    @patch("app.services.notification_dispatcher.dispatch")
    async def test_dispatch_to_user(self, mock_dispatch):
        """Should set user_id in payload."""
        mock_dispatch.return_value = [100]
        db = AsyncMock()

        payload = {"old_role": "user", "new_role": "admin"}
        result = await dispatch_to_user(
            db=db,
            user_id=42,
            event=SystemEvents.USER_ROLE_CHANGED,
            payload=payload
        )

        assert result == [100]
        # dispatch is called with positional args: (db, event, payload, dedupe_key)
        call_args = mock_dispatch.call_args
        # The payload is the dict passed, which gets modified in-place
        assert payload["user_id"] == 42

    @pytest.mark.asyncio
    @patch("app.services.notification_dispatcher.dispatch")
    async def test_dispatch_to_users(self, mock_dispatch):
        """Should set user_ids in payload."""
        mock_dispatch.return_value = [100, 101, 102]
        db = AsyncMock()

        payload = {"title": "Test", "message": "Hello"}
        result = await dispatch_to_users(
            db=db,
            user_ids=[1, 2, 3],
            event=SystemEvents.SYSTEM_ANNOUNCEMENT,
            payload=payload
        )

        assert result == [100, 101, 102]
        # The payload is the dict passed, which gets modified in-place
        assert payload["user_ids"] == [1, 2, 3]

    @pytest.mark.asyncio
    @patch("app.services.notification_dispatcher.dispatch")
    async def test_dispatch_system_alert(self, mock_dispatch):
        """Should dispatch SYSTEM_ALERT with correct payload."""
        mock_dispatch.return_value = [100]
        db = AsyncMock()

        result = await dispatch_system_alert(
            db=db,
            severity="warning",
            message="Test warning",
            action_url="/action"
        )

        assert result == [100]
        # Check that dispatch was called with correct event
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args
        # Positional args: (db, event, payload, dedupe_key=None, skip_preference_check)
        assert call_args[1].get("event") == SystemEvents.SYSTEM_ALERT or \
               call_args[0][1] == SystemEvents.SYSTEM_ALERT
