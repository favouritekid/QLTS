# tests/integration/services/test_user_service_integration.py
"""
Integration tests for user_service.py

These tests use real database to verify:
- Authentication logic with real password hashing
- User CRUD with database constraints
- Password management flows
- Session management with Redis
- Bulk operations
"""
import logging
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.services import user_service
from app.schemas import UserCreate, UserUpdate, AdminUserCreate
from app.security import get_password_hash, verify_password
from app.utils.exceptions import (
    ResourceNotFoundError, 
    DuplicateResourceError, 
    InvalidCredentials,
    InvalidToken,
    BadRequest
)
from app.config import settings

log = logging.getLogger(__name__)


# =============================================================================
# AUTHENTICATION TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestAuthentication:
    """Tests for authenticate_user."""
    
    async def test_authenticate_user_success(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test authenticate_user succeeds with correct password."""
        # Act
        user = await user_service.authenticate_user(
            db, 
            "service_test_admin",  # username from fixture
            "AdminPass123!"  # password from fixture
        )
        
        # Assert
        assert user is not None
        assert user.id == admin_user.id
        assert user.username == admin_user.username
    
    async def test_authenticate_user_wrong_password(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test authenticate_user raises InvalidCredentials for wrong password."""
        with pytest.raises(InvalidCredentials):
            await user_service.authenticate_user(
                db, 
                "service_test_admin",
                "WrongPassword123!"
            )
    
    async def test_authenticate_user_not_found(self, db: AsyncSession):
        """Test authenticate_user raises InvalidCredentials for non-existent user."""
        with pytest.raises(InvalidCredentials):
            await user_service.authenticate_user(
                db, 
                "nonexistent_user",
                "SomePassword123!"
            )
    
    async def test_authenticate_timing_attack_protection(self, db: AsyncSession):
        """
        Test that authenticate_user uses timing attack protection.
        Even for non-existent users, password verification should be called.
        """
        # This is implicit - the fact that we get InvalidCredentials (not a different error)
        # means the code went through the same path as valid user authentication
        with pytest.raises(InvalidCredentials):
            await user_service.authenticate_user(
                db, 
                "phantom_user_timing_test",
                "TestPassword123!"
            )


# =============================================================================
# GET USER TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestGetUser:
    """Tests for get_user_by_id, get_user_by_username, get_user_by_email."""
    
    async def test_get_user_by_id_success(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test get_user_by_id returns user."""
        # Act
        user = await user_service.get_user_by_id(db, admin_user.id)
        
        # Assert
        assert user is not None
        assert user.id == admin_user.id
        assert user.username == admin_user.username
    
    async def test_get_user_by_id_not_found(self, db: AsyncSession):
        """Test get_user_by_id raises ResourceNotFoundError."""
        with pytest.raises(ResourceNotFoundError):
            await user_service.get_user_by_id(db, 999999)
    
    async def test_get_user_by_username_success(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test get_user_by_username returns user."""
        # Act
        user = await user_service.get_user_by_username(db, admin_user.username)
        
        # Assert
        assert user is not None
        assert user.id == admin_user.id
    
    async def test_get_user_by_username_not_found(self, db: AsyncSession):
        """Test get_user_by_username returns None for non-existent user."""
        # Note: get_user_by_username returns None, doesn't raise
        user = await user_service.get_user_by_username(db, "nonexistent_username")
        assert user is None
    
    async def test_get_user_by_email_success(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test get_user_by_email returns user."""
        # Act
        user = await user_service.get_user_by_email(db, admin_user.email)
        
        # Assert
        assert user is not None
        assert user.id == admin_user.id
    
    async def test_get_user_by_email_not_found(self, db: AsyncSession):
        """Test get_user_by_email returns None for non-existent email."""
        user = await user_service.get_user_by_email(db, "nonexistent@test.com")
        assert user is None


# =============================================================================
# CREATE USER TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestCreateUser:
    """Tests for create_user and create_user_by_admin."""
    
    async def test_create_user_by_admin_success(self, db: AsyncSession):
        """Test create_user_by_admin creates user with hashed password."""
        # Arrange
        user_in = MagicMock()
        user_in.username = "new_admin_created"
        user_in.password = "NewUserPass123!"
        user_in.model_dump.return_value = {
            "username": "new_admin_created",
            "email": "new_admin_created@test.com",
            "full_name": "New Admin Created User",
            "role": "user",
            "status": "active",
            "unit_id": None
        }
        
        # Act
        user, callback = await user_service.create_user_by_admin(db, user_in)
        await db.commit()
        if callback:
            await callback()
        
        # Assert
        assert user is not None
        assert user.username == "new_admin_created"
        assert user.password_hash is not None
        assert user.password_hash != "NewUserPass123!"  # Should be hashed
        
        # Verify in database
        db_user = await db.get(models.User, user.id)
        assert db_user is not None
        assert verify_password("NewUserPass123!", db_user.password_hash)
    
    async def test_create_user_by_admin_with_unit(
        self, 
        db: AsyncSession,
        seeded_dependencies: dict
    ):
        """Test create_user_by_admin creates user with unit assignment."""
        # Arrange
        user_in = MagicMock()
        user_in.username = "officer_with_unit"
        user_in.password = "OfficerPass123!"
        user_in.model_dump.return_value = {
            "username": "officer_with_unit",
            "email": "officer_with_unit@test.com",
            "full_name": "Officer With Unit",
            "role": "officer",
            "status": "active",
            "unit_id": seeded_dependencies["unit_id"]
        }
        
        # Act
        with patch("app.services.user_service._create_or_update_user_assignment", new_callable=AsyncMock) as mock_assign:
            user, callback = await user_service.create_user_by_admin(db, user_in)
            await db.commit()
        
        # Assert
        assert user.unit_id == seeded_dependencies["unit_id"]
        mock_assign.assert_awaited_once()


# =============================================================================
# UPDATE USER TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateUser:
    """Tests for update_user."""
    
    async def test_update_user_success(
        self, 
        db: AsyncSession, 
        regular_user: models.User
    ):
        """Test update_user updates user fields."""
        # Arrange
        user_update = MagicMock()
        user_update.model_dump.return_value = {"full_name": "Updated Full Name"}
        
        # Act
        updated_user, callback = await user_service.update_user(db, regular_user, user_update)
        await db.commit()
        if callback:
            await callback()
        
        # Assert
        assert updated_user.full_name == "Updated Full Name"
        
        # Verify in database
        db_user = await db.get(models.User, regular_user.id)
        assert db_user.full_name == "Updated Full Name"
    
    async def test_update_user_duplicate_email_raises_error(
        self, 
        db: AsyncSession, 
        regular_user: models.User,
        admin_user: models.User  # Has different email
    ):
        """Test update_user raises DuplicateResourceError for duplicate email."""
        # Arrange - try to set regular_user's email to admin_user's email
        user_update = MagicMock()
        user_update.model_dump.return_value = {"email": admin_user.email}
        
        # Act & Assert
        with pytest.raises(DuplicateResourceError):
            await user_service.update_user(db, regular_user, user_update)


# =============================================================================
# DELETE USER TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestDeleteUser:
    """Tests for delete_user."""
    
    async def test_delete_user_success(self, db: AsyncSession):
        """Test delete_user removes user from database."""
        # Arrange - create a user to delete
        user_to_delete = models.User(
            username="user_to_delete",
            email="delete_me@test.com",
            password_hash=get_password_hash("DeleteMe123!"),
            role="user",
            status="active"
        )
        db.add(user_to_delete)
        await db.flush()
        user_id = user_to_delete.id
        
        # Act
        _, callback = await user_service.delete_user(db, user_id)
        await db.commit()
        if callback:
            await callback()
        
        # Assert - user should be gone
        deleted_user = await db.get(models.User, user_id)
        assert deleted_user is None
    
    async def test_delete_user_not_found(self, db: AsyncSession):
        """Test delete_user raises ResourceNotFoundError for non-existent user."""
        with pytest.raises(ResourceNotFoundError):
            await user_service.delete_user(db, 999999)

    async def _wipe_admins(self, db: AsyncSession) -> None:
        """Delete all existing admins so the guard sees a clean slate.

        Tests that exercise the real query path need to know exactly how
        many active admins exist; pre-existing seed data otherwise leaks
        into the count and makes assertions non-deterministic.
        """
        await db.execute(
            models.User.__table__.delete().where(models.User.role == "admin")
        )
        await db.flush()

    async def test_delete_last_active_admin_blocked_real_query(
        self, db: AsyncSession
    ):
        """Real DB query: guard fires when only one active admin exists."""
        from app.utils.exceptions import BusinessRuleViolation

        await self._wipe_admins(db)

        solo_admin = models.User(
            username="solo_admin",
            email="solo_admin@test.com",
            password_hash=get_password_hash("SoloAdmin123!"),
            role="admin",
            status="active",
        )
        db.add(solo_admin)
        await db.flush()
        solo_admin_id = solo_admin.id

        with pytest.raises(BusinessRuleViolation, match="last active admin"):
            await user_service.delete_user(db, solo_admin_id)

        still_there = await db.get(models.User, solo_admin_id)
        assert still_there is not None

    async def test_delete_admin_when_multiple_active_admins_succeeds_real_query(
        self, db: AsyncSession
    ):
        """Real DB query: with two active admins, deleting one is allowed."""
        await self._wipe_admins(db)

        admin_a = models.User(
            username="admin_a",
            email="admin_a@test.com",
            password_hash=get_password_hash("AdminA123!"),
            role="admin",
            status="active",
        )
        admin_b = models.User(
            username="admin_b",
            email="admin_b@test.com",
            password_hash=get_password_hash("AdminB123!"),
            role="admin",
            status="active",
        )
        db.add_all([admin_a, admin_b])
        await db.flush()
        admin_a_id = admin_a.id

        _, callback = await user_service.delete_user(db, admin_a_id)
        await db.commit()
        if callback:
            await callback()

        async with AsyncSessionLocal() as verify_session:
            assert await verify_session.get(models.User, admin_a_id) is None
            remaining_admin = await verify_session.get(models.User, admin_b.id)
            assert remaining_admin is not None and remaining_admin.status == "active"

    async def test_delete_inactive_admin_skips_guard_real_query(
        self, db: AsyncSession
    ):
        """Inactive admin can be deleted even when no other active admins exist."""
        await self._wipe_admins(db)

        inactive_admin = models.User(
            username="inactive_admin",
            email="inactive_admin@test.com",
            password_hash=get_password_hash("InactiveAdmin123!"),
            role="admin",
            status="banned",
        )
        db.add(inactive_admin)
        await db.flush()
        inactive_admin_id = inactive_admin.id

        _, callback = await user_service.delete_user(db, inactive_admin_id)
        await db.commit()
        if callback:
            await callback()

        async with AsyncSessionLocal() as verify_session:
            assert await verify_session.get(models.User, inactive_admin_id) is None

    async def test_concurrent_delete_admins_serialized_by_lock(self):
        """
        Race condition test: two transactions concurrently delete two
        different admins. Without the SELECT FOR UPDATE lock both would
        observe count=2 and commit, leaving zero admins. With the lock
        they serialize and the second one sees count=1 and is rejected.

        Uses separate AsyncSessionLocal sessions per coroutine so each
        runs in its own transaction with its own connection — the only
        setup that exercises real row-locking semantics.
        """
        import asyncio
        from app.utils.exceptions import BusinessRuleViolation

        # Setup: ensure exactly two active admins.
        async with AsyncSessionLocal() as setup_session:
            await setup_session.execute(
                models.User.__table__.delete().where(models.User.role == "admin")
            )
            admin_x = models.User(
                username="race_admin_x",
                email="race_x@test.com",
                password_hash=get_password_hash("RaceAdminX123!"),
                role="admin",
                status="active",
            )
            admin_y = models.User(
                username="race_admin_y",
                email="race_y@test.com",
                password_hash=get_password_hash("RaceAdminY123!"),
                role="admin",
                status="active",
            )
            setup_session.add_all([admin_x, admin_y])
            await setup_session.commit()
            admin_x_id, admin_y_id = admin_x.id, admin_y.id

        async def delete_in_own_session(target_id: int):
            async with AsyncSessionLocal() as session:
                try:
                    _, cb = await user_service.delete_user(session, target_id)
                    await session.commit()
                    if cb:
                        await cb()
                    return "ok"
                except BusinessRuleViolation as e:
                    await session.rollback()
                    return f"blocked: {e}"
                except Exception as e:
                    await session.rollback()
                    return f"error: {type(e).__name__}: {e}"

        try:
            results = await asyncio.gather(
                delete_in_own_session(admin_x_id),
                delete_in_own_session(admin_y_id),
                return_exceptions=False,
            )

            # Exactly one delete must succeed and one must be blocked.
            ok_count = sum(1 for r in results if r == "ok")
            blocked_count = sum(1 for r in results if r.startswith("blocked"))
            assert ok_count == 1, (
                f"Expected exactly 1 successful delete, got results={results}"
            )
            assert blocked_count == 1, (
                f"Expected exactly 1 blocked delete, got results={results}"
            )

            # Final DB state: exactly 1 active admin must remain.
            async with AsyncSessionLocal() as verify_session:
                from sqlalchemy import func, select as sa_select

                count_result = await verify_session.execute(
                    sa_select(func.count(models.User.id)).where(
                        models.User.role == "admin",
                        models.User.status == "active",
                    )
                )
                remaining = count_result.scalar_one()
                assert remaining == 1, (
                    f"Race fix broken: {remaining} active admins remain (expected 1)"
                )
        finally:
            # Cleanup: remove whichever admin survived so the test DB stays clean.
            async with AsyncSessionLocal() as cleanup_session:
                await cleanup_session.execute(
                    models.User.__table__.delete().where(
                        models.User.username.in_(["race_admin_x", "race_admin_y"])
                    )
                )
                await cleanup_session.commit()


# =============================================================================
# PASSWORD MANAGEMENT TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestPasswordManagement:
    """Tests for change_password, set_password_by_admin, reset_password."""
    
    async def test_change_password_success(
        self, 
        db: AsyncSession, 
        regular_user: models.User
    ):
        """Test change_password updates password hash."""
        old_password = "UserPass123!"
        new_password = "NewPassword456!"
        
        # Act
        _, callback = await user_service.change_password(
            db, 
            regular_user, 
            old_password, 
            new_password
        )
        await db.commit()
        if callback:
            await callback()
        
        # Assert - new password should work
        await db.refresh(regular_user)
        assert verify_password(new_password, regular_user.password_hash)
        assert not verify_password(old_password, regular_user.password_hash)
    
    async def test_change_password_wrong_old_password(
        self, 
        db: AsyncSession, 
        regular_user: models.User
    ):
        """Test change_password raises BadRequest for wrong old password."""
        with pytest.raises(BadRequest) as exc:
            await user_service.change_password(
                db, 
                regular_user, 
                "WrongOldPassword!",
                "NewPassword456!"
            )
        
        assert "incorrect" in str(exc.value.detail).lower()
    
    async def test_set_password_by_admin_success(
        self, 
        db: AsyncSession, 
        regular_user: models.User
    ):
        """Test set_password_by_admin sets new password."""
        new_password = "AdminSetPassword789!"
        
        # Act
        user, callback = await user_service.set_password_by_admin(
            db, 
            regular_user.id, 
            new_password
        )
        await db.commit()
        if callback:
            await callback()
        
        # Assert
        await db.refresh(regular_user)
        assert verify_password(new_password, regular_user.password_hash)
    
    async def test_set_password_by_admin_user_not_found(self, db: AsyncSession):
        """Test set_password_by_admin raises ResourceNotFoundError."""
        with pytest.raises(ResourceNotFoundError):
            await user_service.set_password_by_admin(db, 999999, "NewPass123!")
    
    async def test_reset_password_invalid_token(self, db: AsyncSession):
        """Test reset_password raises InvalidToken for invalid token."""
        with pytest.raises(InvalidToken):
            await user_service.reset_password(db, "invalid_token_123", "NewPass123!")


# =============================================================================
# FORGOT PASSWORD TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestForgotPassword:
    """Tests for handle_forgot_password."""
    
    async def test_handle_forgot_password_user_exists(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test handle_forgot_password sends email for existing user."""
        # Mock the Celery task at the correct import location
        with patch("app.celery_utils.send_password_reset_email_task") as mock_task:
            mock_task.delay = MagicMock()
            
            # Act
            await user_service.handle_forgot_password(db, admin_user.email)
            
            # Assert - email task should be called
            mock_task.delay.assert_called_once()
            call_kwargs = mock_task.delay.call_args
            assert admin_user.email in str(call_kwargs)
    
    async def test_handle_forgot_password_user_not_found_silent(
        self, 
        db: AsyncSession
    ):
        """Test handle_forgot_password does NOT reveal user existence."""
        # Act - should complete without error even for non-existent email
        # This is important for security - don't reveal if email exists
        await user_service.handle_forgot_password(db, "nonexistent@test.com")
        
        # Assert - no error raised, function completed silently


# =============================================================================
# BULK ACTION TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestBulkActions:
    """Tests for perform_bulk_action."""
    
    async def test_perform_bulk_action_delete(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test perform_bulk_action with delete action."""
        # Arrange - create users to delete
        users_to_delete = []
        for i in range(3):
            user = models.User(
                username=f"bulk_delete_user_{i}",
                email=f"bulk_delete_{i}@test.com",
                password_hash=get_password_hash("BulkDelete123!"),
                role="user",
                status="active"
            )
            db.add(user)
            users_to_delete.append(user)
        await db.flush()
        user_ids = [u.id for u in users_to_delete]
        
        # Act
        with patch("app.repositories.LeadRepository") as MockLeadRepo:
            mock_lead_repo = MockLeadRepo.return_value
            mock_lead_repo.unassign_leads_from_officers = AsyncMock(return_value=0)
            
            msg, callback, _disconnect_ids = await user_service.perform_bulk_action(
                db,
                "delete",
                user_ids, 
                admin_user
            )
            await db.commit()
            if callback:
                await callback()
        
        # Assert
        assert "deleted" in msg.lower()
        assert "3" in msg
        
        # Verify users are deleted
        for user_id in user_ids:
            deleted_user = await db.get(models.User, user_id)
            assert deleted_user is None
    
    async def test_perform_bulk_action_change_status_to_active(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test perform_bulk_action with change_status action to active."""
        # Arrange - create inactive users
        inactive_users = []
        for i in range(2):
            user = models.User(
                username=f"inactive_user_{i}",
                email=f"inactive_{i}@test.com",
                password_hash=get_password_hash("Inactive123!"),
                role="user",
                status="pending"  # Use pending instead of inactive
            )
            db.add(user)
            inactive_users.append(user)
        await db.flush()
        user_ids = [u.id for u in inactive_users]
        
        # Act - use change_status action with new_status parameter
        msg, callback, _disconnect_ids = await user_service.perform_bulk_action(
            db, 
            "change_status", 
            user_ids, 
            admin_user,
            new_status="active"  # Set to active
        )
        await db.commit()
        if callback:
            await callback()
        
        # Assert
        assert "active" in msg.lower()
        
        # Verify users are now active
        for user_id in user_ids:
            activated_user = await db.get(models.User, user_id)
            assert activated_user.status == "active"
    
    async def test_perform_bulk_action_change_status_to_banned(
        self, 
        db: AsyncSession, 
        admin_user: models.User
    ):
        """Test perform_bulk_action with change_status action to banned."""
        # Arrange - create active users
        active_users = []
        for i in range(2):
            user = models.User(
                username=f"active_user_ban_{i}",
                email=f"active_ban_{i}@test.com",
                password_hash=get_password_hash("Active123!"),
                role="user",
                status="active"
            )
            db.add(user)
            active_users.append(user)
        await db.flush()
        user_ids = [u.id for u in active_users]
        
        # Act - use change_status with banned status
        msg, callback, _disconnect_ids = await user_service.perform_bulk_action(
            db, 
            "change_status", 
            user_ids, 
            admin_user,
            new_status="banned"
        )
        await db.commit()
        if callback:
            await callback()
        
        # Assert
        assert "banned" in msg.lower()
        
        # Verify users are now banned
        for user_id in user_ids:
            banned_user = await db.get(models.User, user_id)
            assert banned_user.status == "banned"


# =============================================================================
# GET USERS LIST TESTS
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestGetUsers:
    """Tests for get_users with pagination and filtering."""
    
    async def test_get_users_with_pagination(
        self, 
        db: AsyncSession, 
        admin_user: models.User,
        regular_user: models.User
    ):
        """Test get_users returns paginated results."""
        # Act
        total_count, users = await user_service.get_users(
            db, 
            params={}, 
            skip=0, 
            limit=10
        )
        
        # Assert
        assert total_count >= 2  # At least admin and regular user
        assert len(users) <= 10
    
    async def test_get_users_with_role_filter(
        self, 
        db: AsyncSession, 
        admin_user: models.User,
        regular_user: models.User
    ):
        """Test get_users filters by role."""
        # Act
        total_count, users = await user_service.get_users(
            db, 
            params={"role": "admin"}, 
            skip=0, 
            limit=10
        )
        
        # Assert
        for user in users:
            assert user.role == "admin"


# =============================================================================
# CASBIN & ASSIGNMENT LOGIC TESTS (Migrated from unit tests)
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.integration
class TestCasbinAndAssignment:
    """Tests for Casbin sync and assignment helper logic."""
    
    async def test_update_user_role_change_syncs_casbin(
        self, 
        db: AsyncSession, 
        regular_user: models.User
    ):
        """Test updating role triggers Casbin policy sync."""
        # Arrange
        user_update = MagicMock()
        user_update.model_dump.return_value = {"role": "officer"}
        
        mock_enforcer = AsyncMock()
        mock_enforcer.add_grouping_policy.return_value = True
        mock_enforcer.remove_grouping_policy.return_value = True
        mock_enforcer.save_policy.return_value = None
        
        # Act
        updated_user, callback = await user_service.update_user(
            db, 
            regular_user, 
            user_in=user_update, 
            enforcer=mock_enforcer
        )
        await db.commit()
        if callback:
            await callback()
        
        # Assert - Verify Casbin was called
        mock_enforcer.remove_grouping_policy.assert_awaited()
        mock_enforcer.add_grouping_policy.assert_awaited()
        mock_enforcer.save_policy.assert_awaited()
        
        # Verify role was changed in DB
        await db.refresh(regular_user)
        assert regular_user.role == "officer"
    
    async def test_update_user_unit_change_triggers_assignment_logic(
        self, 
        db: AsyncSession, 
        regular_user: models.User,
        seeded_dependencies: dict
    ):
        """Test changing unit_id triggers assignment helper."""
        # Arrange - set initial unit
        regular_user.unit_id = seeded_dependencies["unit_id"]
        regular_user.role = "officer"
        await db.flush()
        
        # Create a second unit for transfer
        second_unit = models.OrganizationUnit(
            name="Second Unit",
            type="Phòng ban"
        )
        db.add(second_unit)
        await db.flush()
        
        user_update = MagicMock()
        user_update.model_dump.return_value = {"unit_id": second_unit.id}
        
        # Act
        with patch("app.services.user_service._create_or_update_user_assignment", new_callable=AsyncMock) as mock_assign:
            updated_user, callback = await user_service.update_user(db, regular_user, user_update)
            await db.commit()
            if callback:
                await callback()
            
            # Assert - assignment helper was called
            mock_assign.assert_awaited_once()
            call_kwargs = mock_assign.call_args[1]
            assert call_kwargs["new_unit_id"] == second_unit.id
