# tests/services/test_notification_preference_service.py
"""
Tests for notification preference service.

These tests verify preference management and group-based filtering.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.notification_preference_service import (
    get_group_preference,
    filter_users_by_group,
)


# =============================================================================
# GET GROUP PREFERENCE TESTS
# =============================================================================

class TestGetGroupPreference:
    """Tests for get_group_preference function."""

    def test_returns_true_for_none_preferences(self):
        """Should return True when preferences are None."""
        result = get_group_preference(None, "lead", "browser")
        assert result is True

    def test_returns_true_for_empty_preferences(self):
        """Should return True when preferences are empty."""
        result = get_group_preference({}, "lead", "browser")
        assert result is True

    def test_returns_true_for_missing_group(self):
        """Should return True when group is not configured."""
        prefs = {"finance": {"browser": False}}
        result = get_group_preference(prefs, "lead", "browser")
        assert result is True

    def test_returns_true_for_missing_channel(self):
        """Should return True when channel is not configured in group."""
        prefs = {"lead": {"email": False}}
        result = get_group_preference(prefs, "lead", "browser")
        assert result is True

    def test_returns_configured_value_true(self):
        """Should return configured True value."""
        prefs = {"lead": {"browser": True, "email": False}}
        result = get_group_preference(prefs, "lead", "browser")
        assert result is True

    def test_returns_configured_value_false(self):
        """Should return configured False value."""
        prefs = {"lead": {"browser": False, "email": True}}
        result = get_group_preference(prefs, "lead", "browser")
        assert result is False

    def test_case_insensitive_group(self):
        """Should handle case insensitive group names."""
        prefs = {"lead": {"browser": False}}
        result = get_group_preference(prefs, "LEAD", "browser")
        assert result is False

    def test_case_insensitive_channel(self):
        """Should handle case insensitive channel names."""
        prefs = {"lead": {"browser": False}}
        result = get_group_preference(prefs, "lead", "BROWSER")
        assert result is False


# =============================================================================
# FILTER USERS BY GROUP TESTS
# =============================================================================

class TestFilterUsersByGroup:
    """Tests for filter_users_by_group function."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_input(self):
        """Should return empty list for empty input."""
        db = AsyncMock()
        result = await filter_users_by_group(db, [], "lead", "browser")
        assert result == []

    @pytest.mark.asyncio
    async def test_includes_users_without_preferences(self):
        """Should include users who have no preference record (default enabled)."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []  # No preferences
        db.execute.return_value = mock_result

        result = await filter_users_by_group(
            db=db,
            user_ids=[1, 2, 3],
            group="lead",
            channel="browser"
        )

        # All users should be included (default = enabled)
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_filters_users_with_disabled_global_channel(self):
        """Should filter out users with disabled global channel."""
        db = AsyncMock()

        # Create mock preference with browser_enabled=False
        mock_pref = MagicMock()
        mock_pref.user_id = 1
        mock_pref.browser_enabled = False
        mock_pref.email_enabled = True
        mock_pref.sound_enabled = True
        mock_pref.type_preferences = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_pref]
        db.execute.return_value = mock_result

        result = await filter_users_by_group(
            db=db,
            user_ids=[1, 2],
            group="lead",
            channel="browser"
        )

        # User 1 should be filtered out, user 2 (no pref) included
        assert 1 not in result
        assert 2 in result

    @pytest.mark.asyncio
    async def test_filters_users_with_disabled_group_preference(self):
        """Should filter out users with disabled group preference."""
        db = AsyncMock()

        # Create mock preference with lead.browser=False
        mock_pref = MagicMock()
        mock_pref.user_id = 1
        mock_pref.browser_enabled = True
        mock_pref.email_enabled = True
        mock_pref.sound_enabled = True
        mock_pref.type_preferences = {"lead": {"browser": False, "email": True}}

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_pref]
        db.execute.return_value = mock_result

        # Mock is_quiet_hours to return False
        with patch(
            "app.services.notification_preference_service.is_quiet_hours",
            new_callable=AsyncMock,
            return_value=False
        ):
            result = await filter_users_by_group(
                db=db,
                user_ids=[1, 2],
                group="lead",
                channel="browser"
            )

        # User 1 should be filtered out (lead.browser=False)
        assert 1 not in result
        assert 2 in result

    @pytest.mark.asyncio
    async def test_includes_users_with_enabled_preference(self):
        """Should include users with enabled preference."""
        db = AsyncMock()

        mock_pref = MagicMock()
        mock_pref.user_id = 1
        mock_pref.browser_enabled = True
        mock_pref.email_enabled = True
        mock_pref.sound_enabled = True
        mock_pref.type_preferences = {"lead": {"browser": True, "email": True}}

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_pref]
        db.execute.return_value = mock_result

        with patch(
            "app.services.notification_preference_service.is_quiet_hours",
            new_callable=AsyncMock,
            return_value=False
        ):
            result = await filter_users_by_group(
                db=db,
                user_ids=[1],
                group="lead",
                channel="browser"
            )

        assert 1 in result


# =============================================================================
# JSON SCHEMA TESTS
# =============================================================================

class TestPreferenceJsonSchema:
    """Tests for preference JSON schema compliance."""

    def test_schema_structure(self):
        """Test that the expected schema structure works correctly."""
        # Expected schema from spec:
        # {
        #     "lead": {"browser": true, "email": true, "sms": false},
        #     "finance": {"browser": false, "email": true}
        # }
        prefs = {
            "lead": {"browser": True, "email": True, "sms": False},
            "finance": {"browser": False, "email": True}
        }

        # Test lead group
        assert get_group_preference(prefs, "lead", "browser") is True
        assert get_group_preference(prefs, "lead", "email") is True
        assert get_group_preference(prefs, "lead", "sms") is False

        # Test finance group
        assert get_group_preference(prefs, "finance", "browser") is False
        assert get_group_preference(prefs, "finance", "email") is True
        # sms not defined, should default to True
        assert get_group_preference(prefs, "finance", "sms") is True

        # Test undefined group
        assert get_group_preference(prefs, "dorm", "browser") is True
