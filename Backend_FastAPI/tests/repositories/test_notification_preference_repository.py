# tests/repositories/test_notification_preference_repository.py
"""
Integration tests for NotificationPreferenceRepository.

Covers user preference CRUD, get_or_create pattern, and bulk fetch.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories import NotificationPreferenceRepository


@pytest.mark.asyncio
@pytest.mark.integration
class TestNotificationPreferenceRepository:
    """Integration tests for NotificationPreferenceRepository."""

    # =========================================================================
    # GET BY USER ID
    # =========================================================================

    async def test_get_by_user_id_returns_preference(
        self, 
        db: AsyncSession, 
        officer_user_in_db: dict
    ):
        """Should return preference for existing user."""
        user_id = officer_user_in_db["id"]
        
        # Arrange - Create preference
        pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=False,
            email_enabled=True
        )
        db.add(pref)
        await db.commit()
        
        # Act
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_by_user_id(user_id)
        
        # Assert
        assert result is not None
        assert result.browser_enabled is False
        assert result.email_enabled is True

    async def test_get_by_user_id_not_found(self, db: AsyncSession):
        """Should return None for user without preference."""
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_by_user_id(99999)
        assert result is None

    # =========================================================================
    # GET BY USER IDS (Bulk Fetch)
    # =========================================================================

    async def test_get_by_user_ids_returns_dict(
        self, 
        db: AsyncSession,
        officer_user_in_db: dict,
        admin_user_in_db: dict
    ):
        """Should return dict mapping user_id to preference."""
        u1_id = officer_user_in_db["id"]
        u2_id = admin_user_in_db["id"]
        
        # Arrange
        pref1 = models.NotificationPreference(user_id=u1_id, browser_enabled=True)
        pref2 = models.NotificationPreference(user_id=u2_id, browser_enabled=False)
        db.add_all([pref1, pref2])
        await db.commit()
        
        # Act
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_by_user_ids([u1_id, u2_id])
        
        # Assert
        assert isinstance(result, dict)
        assert u1_id in result
        assert u2_id in result
        assert result[u1_id].browser_enabled is True
        assert result[u2_id].browser_enabled is False

    async def test_get_by_user_ids_empty_list(self, db: AsyncSession):
        """Should return empty dict for empty input."""
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_by_user_ids([])
        assert result == {}

    async def test_get_by_user_ids_partial_match(
        self, 
        db: AsyncSession,
        officer_user_in_db: dict
    ):
        """Should only return preferences for users who have them."""
        user_id = officer_user_in_db["id"]
        non_existent_id = 88888
        
        # Arrange
        pref = models.NotificationPreference(user_id=user_id, browser_enabled=True)
        db.add(pref)
        await db.commit()
        
        # Act
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_by_user_ids([user_id, non_existent_id])
        
        # Assert
        assert user_id in result
        assert non_existent_id not in result
        assert len(result) == 1

    # =========================================================================
    # GET OR CREATE
    # =========================================================================

    async def test_get_or_create_returns_existing(
        self, 
        db: AsyncSession,
        officer_user_in_db: dict
    ):
        """Should return existing preference without creating new one."""
        user_id = officer_user_in_db["id"]
        
        # Arrange - Create existing preference with custom settings
        existing_pref = models.NotificationPreference(
            user_id=user_id,
            browser_enabled=False,
            email_enabled=False,
            sound_enabled=False
        )
        db.add(existing_pref)
        await db.commit()
        original_id = existing_pref.id
        
        # Act
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_or_create(user_id)
        
        # Assert
        assert result.id == original_id
        assert result.browser_enabled is False  # Preserved original setting

    async def test_get_or_create_creates_default(
        self, 
        db: AsyncSession,
        admin_user_in_db: dict
    ):
        """Should create default preference for user without one."""
        user_id = admin_user_in_db["id"]
        
        # Ensure no preference exists
        repo = NotificationPreferenceRepository(db)
        existing = await repo.get_by_user_id(user_id)
        if existing:
            await db.delete(existing)
            await db.commit()
        
        # Act
        result = await repo.get_or_create(user_id)
        await db.commit()
        
        # Assert - Should have default values
        assert result.id is not None
        assert result.user_id == user_id
        assert result.email_enabled is True  # Default
        assert result.browser_enabled is True  # Default
        assert result.sound_enabled is True  # Default
        assert result.quiet_hours_enabled is False  # Default

    async def test_get_or_create_default_type_preferences(
        self, 
        db: AsyncSession,
        manager_user_in_db: dict
    ):
        """Should create preference with empty type_preferences dict."""
        # Use real user from fixture
        user_id = manager_user_in_db["id"]
        
        # Act
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_or_create(user_id)
        await db.commit()
        
        # Assert
        assert result.type_preferences == {}

    # =========================================================================
    # GET FILTERED (Abstract method)
    # =========================================================================

    async def test_get_filtered_with_user_id(
        self, 
        db: AsyncSession,
        officer_user_in_db: dict
    ):
        """Should filter by user_id."""
        user_id = officer_user_in_db["id"]
        
        # Arrange
        pref = models.NotificationPreference(user_id=user_id)
        db.add(pref)
        await db.commit()
        
        # Act
        repo = NotificationPreferenceRepository(db)
        total, results = await repo.get_filtered(user_id=user_id)
        
        # Assert
        assert total >= 1
        assert any(p.user_id == user_id for p in results)

    async def test_get_filtered_pagination(
        self, 
        db: AsyncSession,
        officer_user_in_db: dict,
        admin_user_in_db: dict,
        manager_user_in_db: dict
    ):
        """Should respect skip and limit."""
        # Arrange - Create multiple preferences using real users
        user_ids = [officer_user_in_db["id"], admin_user_in_db["id"], manager_user_in_db["id"]]
        for uid in user_ids:
            pref = models.NotificationPreference(user_id=uid)
            db.add(pref)
        await db.commit()
        
        # Act
        repo = NotificationPreferenceRepository(db)
        total, results = await repo.get_filtered(skip=0, limit=2)
        
        # Assert
        assert len(results) <= 2
        assert total >= 3

    # =========================================================================
    # EDGE CASES
    # =========================================================================

    async def test_preference_with_type_preferences_json(
        self, 
        db: AsyncSession,
        officer_user_in_db: dict
    ):
        """Should correctly store and retrieve type_preferences JSON."""
        user_id = officer_user_in_db["id"]
        
        # Arrange
        type_prefs = {
            "lead": {"browser": False, "email": True},
            "finance": {"browser": True}
        }
        pref = models.NotificationPreference(
            user_id=user_id,
            type_preferences=type_prefs
        )
        db.add(pref)
        await db.commit()
        
        # Act
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_by_user_id(user_id)
        
        # Assert
        assert result.type_preferences["lead"]["browser"] is False
        assert result.type_preferences["lead"]["email"] is True
        assert result.type_preferences["finance"]["browser"] is True

    async def test_preference_with_quiet_hours(
        self, 
        db: AsyncSession,
        admin_user_in_db: dict
    ):
        """Should correctly store and retrieve quiet hours settings."""
        from datetime import time
        
        user_id = admin_user_in_db["id"]
        
        # Arrange
        pref = models.NotificationPreference(
            user_id=user_id,
            quiet_hours_enabled=True,
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(8, 0)
        )
        db.add(pref)
        await db.commit()
        
        # Act
        repo = NotificationPreferenceRepository(db)
        result = await repo.get_by_user_id(user_id)
        
        # Assert
        assert result.quiet_hours_enabled is True
        assert result.quiet_hours_start == time(22, 0)
        assert result.quiet_hours_end == time(8, 0)
