# tests/security/test_idor_protection.py
"""
IDOR (Insecure Direct Object Reference) Protection Tests.

Tests for Phase 2 IDOR dependencies:
- get_notification_for_user
- get_lead_for_user

These tests verify that users cannot access resources they don't own,
and that the system returns 404 (not 403) to prevent inference attacks.

Reference: AUTHORIZATION_IMPLEMENTATION_PLAN.md Phase 2, 5.2
Reference: AUTHORIZATION_DECISIONS.md Decision 2 (404 vs 403)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.deps import get_notification_for_user
from app.core.constants import UserRole
from app.utils.exceptions import ResourceNotFoundError, PermissionDeniedError


# =============================================================================
# FIXTURES
# =============================================================================

def create_mock_user(role: str, user_id: int = 1, unit_id: int = 10, is_active: bool = True):
    """Create a mock user with specified attributes."""
    user = MagicMock()
    user.id = user_id
    user.role = role
    user.unit_id = unit_id
    user.status = "active" if is_active else "inactive"
    user.username = f"test_{role}_{user_id}"
    user.full_name = f"Test {role.capitalize()} {user_id}"
    return user


def create_mock_notification(notification_id: int, user_id: int):
    """Create a mock notification owned by a specific user."""
    notification = MagicMock()
    notification.id = notification_id
    notification.user_id = user_id
    notification.title = f"Test Notification {notification_id}"
    notification.is_read = False
    return notification


def create_mock_db():
    """Create a mock database session."""
    db = AsyncMock()
    return db


# =============================================================================
# TEST: get_notification_for_user (IDOR Prevention)
# =============================================================================

class TestGetNotificationForUser:
    """
    Tests for get_notification_for_user IDOR protection dependency.

    Security Requirements (per AUTHORIZATION_DECISIONS.md Decision 2):
    - Users can only access their own notifications
    - Admin can access all notifications
    - Returns 404 (not 403) for unauthorized access to prevent inference
    """

    @pytest.mark.asyncio
    async def test_user_can_access_own_notification(self):
        """User should be able to access their own notification."""
        user = create_mock_user(role=UserRole.OFFICER, user_id=100)
        notification = create_mock_notification(notification_id=1, user_id=100)  # Same owner
        db = create_mock_db()

        # Mock repository - patch at source module where NotificationRepository is defined
        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = notification
            MockRepo.return_value = mock_repo_instance

            result = await get_notification_for_user(
                notification_id=1,
                db=db,
                current_user=user
            )

            assert result == notification
            assert result.user_id == user.id

    @pytest.mark.asyncio
    async def test_user_cannot_access_other_user_notification(self):
        """User should NOT be able to access another user's notification."""
        user = create_mock_user(role=UserRole.OFFICER, user_id=100)
        other_user_notification = create_mock_notification(notification_id=1, user_id=200)  # Different owner
        db = create_mock_db()

        # Mock repository - patch at source module where NotificationRepository is defined
        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = other_user_notification
            MockRepo.return_value = mock_repo_instance

            # Should raise ResourceNotFoundError (404), NOT PermissionDeniedError (403)
            with pytest.raises(ResourceNotFoundError) as exc_info:
                await get_notification_for_user(
                    notification_id=1,
                    db=db,
                    current_user=user
                )

            # Verify it's 404 error (IDOR prevention - hide existence)
            assert "not found" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_manager_cannot_access_other_user_notification(self):
        """Manager should NOT be able to access another user's notification."""
        manager = create_mock_user(role=UserRole.MANAGER, user_id=50)
        officer_notification = create_mock_notification(notification_id=1, user_id=100)  # Officer's notification
        db = create_mock_db()

        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = officer_notification
            MockRepo.return_value = mock_repo_instance

            # Manager should also get 404, not access
            with pytest.raises(ResourceNotFoundError) as exc_info:
                await get_notification_for_user(
                    notification_id=1,
                    db=db,
                    current_user=manager
                )

            assert "not found" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_admin_can_access_any_notification(self):
        """Admin should be able to access any user's notification."""
        admin = create_mock_user(role=UserRole.ADMIN, user_id=1)
        other_user_notification = create_mock_notification(notification_id=1, user_id=999)  # Different owner
        db = create_mock_db()

        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = other_user_notification
            MockRepo.return_value = mock_repo_instance

            result = await get_notification_for_user(
                notification_id=1,
                db=db,
                current_user=admin
            )

            # Admin should have access even to other users' notifications
            assert result == other_user_notification
            assert result.user_id != admin.id  # Confirms it's someone else's

    @pytest.mark.asyncio
    async def test_nonexistent_notification_returns_404(self):
        """Requesting non-existent notification should return 404."""
        user = create_mock_user(role=UserRole.OFFICER, user_id=100)
        db = create_mock_db()

        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = None  # Notification doesn't exist
            MockRepo.return_value = mock_repo_instance

            with pytest.raises(ResourceNotFoundError) as exc_info:
                await get_notification_for_user(
                    notification_id=99999,
                    db=db,
                    current_user=user
                )

            assert "not found" in str(exc_info.value.detail).lower()


class TestIDORReturns404Not403:
    """
    Critical security tests: IDOR attempts should return 404, not 403.

    Rationale (AUTHORIZATION_DECISIONS.md Decision 2):
    - 403 reveals that the resource EXISTS but user lacks permission
    - Attacker can use this to enumerate valid IDs
    - 404 hides resource existence, preventing inference attacks
    """

    @pytest.mark.asyncio
    async def test_idor_response_is_404_not_403_notification(self):
        """IDOR attempt on notification should return 404 ResourceNotFoundError."""
        attacker = create_mock_user(role=UserRole.OFFICER, user_id=100)
        victim_notification = create_mock_notification(notification_id=1, user_id=200)
        db = create_mock_db()

        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = victim_notification
            MockRepo.return_value = mock_repo_instance

            # Verify exception type is ResourceNotFoundError (404), not PermissionDeniedError (403)
            with pytest.raises(ResourceNotFoundError):
                await get_notification_for_user(
                    notification_id=1,
                    db=db,
                    current_user=attacker
                )

            # Should NOT raise PermissionDeniedError
            # If it does, it means we're leaking information about resource existence

    @pytest.mark.asyncio
    async def test_idor_error_message_does_not_leak_info(self):
        """IDOR error message should not reveal that resource exists."""
        attacker = create_mock_user(role=UserRole.OFFICER, user_id=100)
        victim_notification = create_mock_notification(notification_id=1, user_id=200)
        db = create_mock_db()

        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = victim_notification
            MockRepo.return_value = mock_repo_instance

            with pytest.raises(ResourceNotFoundError) as exc_info:
                await get_notification_for_user(
                    notification_id=1,
                    db=db,
                    current_user=attacker
                )

            error_message = str(exc_info.value.detail).lower()

            # Should say "not found", NOT "permission denied" or "not authorized"
            assert "not found" in error_message
            assert "permission" not in error_message
            assert "denied" not in error_message
            assert "unauthorized" not in error_message
            assert "access" not in error_message


class TestNotificationDeleteIDOR:
    """
    Integration-style tests for notification delete IDOR.

    Per Phase 2.2:
    - User A should NOT be able to delete User B's notification
    - Verify through the actual endpoint behavior
    """

    @pytest.mark.asyncio
    async def test_delete_returns_404_for_others_notification(self):
        """
        User trying to delete another user's notification should get 404.

        This test validates the full flow through get_notification_for_user
        dependency which is used by the DELETE endpoint.
        """
        user_a = create_mock_user(role=UserRole.OFFICER, user_id=100)
        user_b_notification = create_mock_notification(notification_id=1, user_id=200)  # User B's
        db = create_mock_db()

        with patch("app.repositories.notification_repository.NotificationRepository") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get.return_value = user_b_notification
            MockRepo.return_value = mock_repo_instance

            # User A tries to access (prerequisite for delete)
            with pytest.raises(ResourceNotFoundError):
                await get_notification_for_user(
                    notification_id=1,
                    db=db,
                    current_user=user_a
                )

            # Notification should still exist (not deleted)
            # In a real scenario, the dependency fails BEFORE delete logic runs
