# tests/services/test_notification_preference.py
"""
Integration tests for notification preference service.

These tests verify preference management and group-based filtering
against the real database schema.
"""
import pytest
from datetime import time
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services.notification_preference_service import (
    get_group_preference,
    filter_users_by_group,
)


@pytest.mark.integration
class TestNotificationPreferenceService:
    """Integration tests for notification preference service."""

    # =========================================================================
    # GET GROUP PREFERENCE LOGIC
    # =========================================================================

    def test_get_group_preference_logic(self):
        """Test the pure logic of group preference resolution."""
        # Default should be True
        assert get_group_preference(None, "lead", "browser") is True
        assert get_group_preference({}, "lead", "browser") is True
        
        # Specific overrides
        prefs = {"lead": {"browser": False, "email": True}}
        assert get_group_preference(prefs, "lead", "browser") is False
        assert get_group_preference(prefs, "lead", "email") is True
        
        # Case insensitivity
        assert get_group_preference(prefs, "LEAD", "BROWSER") is False
        
        # Missing group/channel defaults to True
        assert get_group_preference(prefs, "finance", "browser") is True
        assert get_group_preference(prefs, "lead", "sms") is True

    # =========================================================================
    # FILTER USERS BY GROUP (DATABASE INTEGRATION)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_filter_users_by_group_no_prefs(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict
    ):
        """Should include users who have no preference record (default enabled)."""
        user_id = officer_user_in_db["id"]
        
        result = await filter_users_by_group(db, [user_id], "lead", "browser")
        
        assert result == [user_id]

    @pytest.mark.asyncio
    async def test_filter_users_by_group_disabled_global_channel(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict
    ):
        """Should filter out users with disabled global channel."""
        user_id = officer_user_in_db["id"]
        
        # Create preference with browser disabled
        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=False,
            email_enabled=True
        )
        db.add(pref)
        await db.commit()
        
        # Check browser (should be filtered)
        result_browser = await filter_users_by_group(db, [user_id], "lead", "browser")
        assert result_browser == []
        
        # Check email (should be allowed)
        result_email = await filter_users_by_group(db, [user_id], "lead", "email")
        assert result_email == [user_id]

    @pytest.mark.asyncio
    async def test_filter_users_by_group_disabled_specific(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict
    ):
        """Should filter out users with disabled group-specific preference."""
        user_id = officer_user_in_db["id"]
        
        # Enable global but disable specific group "lead"
        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=True,
            type_preferences={"lead": {"browser": False}}
        )
        db.add(pref)
        await db.commit()
        
        result = await filter_users_by_group(db, [user_id], "lead", "browser")
        assert result == []
        
        # Other groups should still work
        result_other = await filter_users_by_group(db, [user_id], "finance", "browser")
        assert result_other == [user_id]

    @pytest.mark.asyncio
    async def test_filter_users_by_group_quiet_hours(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict,
        mocker
    ):
        """Should filter out users during their configured quiet hours."""
        user_id = officer_user_in_db["id"]
        
        # Set 24h quiet period
        pref = models.NotificationPreference(
            user_id=user_id,
            quiet_hours_enabled=True,
            quiet_hours_start=time(0, 0),
            quiet_hours_end=time(23, 59)
        )
        db.add(pref)
        await db.commit()

        # Mock current time to be 12:00 (inside 00:00-23:59)
        mock_now = mocker.patch("app.services.notification_preference_service.datetime")
        mock_now.now.return_value.time.return_value = time(12, 0)
        
        result = await filter_users_by_group(db, [user_id], "lead", "browser")
        
        assert result == []

    @pytest.mark.asyncio
    async def test_filter_multiple_users_mixed_prefs(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict,
        admin_user_in_db: dict
    ):
        """Should correctly filter list with mixed preferences."""
        u1_id = officer_user_in_db["id"]
        u2_id = admin_user_in_db["id"]
        
        # User 1: Global Disabled
        p1 = models.NotificationPreference(user_id=u1_id, browser_enabled=False)
        # User 2: Specific Disabled
        p2 = models.NotificationPreference(user_id=u2_id, type_preferences={"lead": {"browser": False}})
        # User 3: No Pref (Enabled)
        u3_id = 9999 # Dummy ID that isn't in preferences
        
        db.add_all([p1, p2])
        await db.commit()
        
        result = await filter_users_by_group(db, [u1_id, u2_id, u3_id], "lead", "browser")
        
        # Only User 3 should remain
        assert result == [u3_id]
