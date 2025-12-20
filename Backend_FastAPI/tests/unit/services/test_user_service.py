
# tests/unit/services/test_user_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from datetime import datetime, timezone

from app.services import user_service
from app.models.user import User
from app.schemas import UserCreate, AdminUserCreate, UserUpdate
from app.utils.exceptions import InvalidCredentials, ResourceNotFoundError, DuplicateResourceError

# Constants
TEST_USERNAME = "testuser"
TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "Password123!"
TEST_HASH = "$2b$12$fakehash"

@pytest.fixture(autouse=True)
def mock_logger():
    """Patch structlog to avoid TypeError: toDict() should return a dict, got MagicMock."""
    with patch("app.services.user_service.log") as mock_log:
        yield mock_log

@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = AsyncMock()
    session.begin_nested = MagicMock()
    # Support async context manager for begin_nested
    nested_ctx = AsyncMock()
    session.begin_nested.return_value = nested_ctx
    nested_ctx.__aenter__.return_value = session
    nested_ctx.__aexit__.return_value = None
    
    session.add = MagicMock()
    session.flush = AsyncMock()
    # refresh should not return None if we want to simulate object staying same, 
    # but here it's fine as long as it's awaited.
    session.refresh = AsyncMock() 
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    
    # Configure get to return None by default
    session.get = AsyncMock(return_value=None)
    
    return session

@pytest.fixture
def mock_repo():
    """Mock UserRepository."""
    # PATCH TARGET FIX: user_service imports it locally, so we must patch the SOURCE
    with patch("app.repositories.UserRepository") as MockRepo:
        repo_instance = MockRepo.return_value
        
        # Configure AsyncMethods
        repo_instance.get_by_id = AsyncMock(return_value=None)
        repo_instance.get_by_ids = AsyncMock(return_value=[])
        repo_instance.get_users_by_ids_for_delete = AsyncMock(return_value=[])
        
        yield repo_instance

@pytest.fixture
def mock_user_repo_class():
    """Mock UserRepository class for patching imports."""
    with patch("app.repositories.UserRepository") as MockRepo:
        yield MockRepo

# =============================================================================
# AUTHENTICATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_authenticate_user_success(mock_db_session):
    """Test successful authentication."""
    # Setup
    mock_user = User(
        id=1, 
        username=TEST_USERNAME, 
        password_hash=TEST_HASH,
        status="active"
    )
    
    # Mock get_user_by_username to return our user
    # Note: authenticate_user calls get_user_by_username internally
    with patch("app.services.user_service.get_user_by_username", new_callable=AsyncMock) as mock_get_user, \
         patch("app.services.user_service.verify_password", return_value=True) as mock_verify:
        
        mock_get_user.return_value = mock_user
        
        # Execute
        user = await user_service.authenticate_user(mock_db_session, TEST_USERNAME, TEST_PASSWORD)
        
        # Assert
        assert user == mock_user
        mock_verify.assert_called_with(TEST_PASSWORD, TEST_HASH)

@pytest.mark.asyncio
async def test_authenticate_user_invalid_password(mock_db_session):
    """Test authentication with wrong password."""
    mock_user = User(username=TEST_USERNAME, password_hash=TEST_HASH)
    
    with patch("app.services.user_service.get_user_by_username", new_callable=AsyncMock) as mock_get_user, \
         patch("app.services.user_service.verify_password", return_value=False):
        
        mock_get_user.return_value = mock_user
        
        with pytest.raises(InvalidCredentials):
            await user_service.authenticate_user(mock_db_session, TEST_USERNAME, "wrongpass")

@pytest.mark.asyncio
async def test_authenticate_user_not_found(mock_db_session):
    """Test authentication for non-existent user."""
    with patch("app.services.user_service.get_user_by_username", new_callable=AsyncMock) as mock_get_user, \
         patch("app.services.user_service.verify_password") as mock_verify:
        
        mock_get_user.return_value = None
        
        with pytest.raises(InvalidCredentials):
            await user_service.authenticate_user(mock_db_session, "phantom", TEST_PASSWORD)
            
        # Verify dummy hash usage (timing attack protection)
        mock_verify.assert_called()
        args = mock_verify.call_args[0]
        assert args[0] == TEST_PASSWORD
        assert args[1] != TEST_HASH # Should be dummy hash

# =============================================================================
# CRUD TESTS (Using UserRepository Mocks)
# =============================================================================

@pytest.mark.asyncio
async def test_get_user_by_id(mock_db_session, mock_repo):
    """Test get_user_by_id delegates to Repository."""
    # Setup
    mock_user = User(id=1, username="found")
    mock_repo.get_by_id.return_value = mock_user
    
    # Execute
    user = await user_service.get_user_by_id(mock_db_session, 1)
    
    # Assert
    assert user == mock_user
    mock_repo.get_by_id.assert_called_once_with(1)

@pytest.mark.asyncio
async def test_get_user_by_id_not_found(mock_db_session, mock_repo):
    """Test get_user_by_id raises ResourceNotFoundError if missing."""
    mock_repo.get_by_id.return_value = None
    
    with pytest.raises(ResourceNotFoundError):
        await user_service.get_user_by_id(mock_db_session, 999)

# =============================================================================
# CREATE USER TESTS (Admin)
# =============================================================================

@pytest.mark.asyncio
async def test_create_user_by_admin_simple(mock_db_session, mock_repo):
    """Test creating a simple admin user without unit assignment."""
    # Setup - Use MagicMock (no spec) to ensure model_dump returns dict
    user_in = MagicMock()
    user_in.username = "admin_created"
    user_in.password = "Pass"
    user_in.model_dump.return_value = {
        "username": "admin_created",
        "email": "admin@e.com",
        "full_name": "Created By Admin",
        "role": "user",
        "status": "active",
        "unit_id": None
    }
    
    with patch("app.services.user_service.get_password_hash", return_value="hashed_pass"), \
         patch("app.services.user_service._create_or_update_user_assignment", new_callable=AsyncMock) as mock_assign:
         
        # Execute
        user, callback = await user_service.create_user_by_admin(
            mock_db_session, 
            user_in,
            assigned_by_user_id=1
        )
        
        # Assert
        assert user.username == "admin_created"
        assert user.password_hash == "hashed_pass"
        mock_db_session.add.assert_called() 
        mock_db_session.flush.assert_awaited()
        
        # Verify assignment Helper was NOT called (unit_id is None)
        mock_assign.assert_not_called()

@pytest.mark.asyncio
async def test_create_user_by_admin_with_unit(mock_db_session, mock_repo):
    """Test creating user with unit triggers assignment logic."""
    # Setup - Use MagicMock
    user_in = MagicMock()
    user_in.username = "unit_user"
    user_in.password = "Pass"
    user_in.model_dump.return_value = {
        "username": "unit_user",
        "email": "unit@e.com",
        "full_name": "Unit User",
        "role": "officer",
        "status": "active",
        "unit_id": 10
    }
    
    with patch("app.services.user_service.get_password_hash"), \
         patch("app.services.user_service._create_or_update_user_assignment", new_callable=AsyncMock) as mock_assign:
         
        await user_service.create_user_by_admin(mock_db_session, user_in)
        
        # Verify assignment helper called
        mock_assign.assert_awaited_once()
        args = mock_assign.call_args[1]
        assert args["new_unit_id"] == 10
        assert args["new_role"] == "officer"

@pytest.mark.asyncio
async def test_update_user_logic(mock_db_session, mock_repo):
    """Test update user logic delegates to assignment helper on change."""
    # Setup existing user
    db_user = User(id=1, username="update_u", role="user", unit_id=None)
    
    # Mock Update Schema
    user_update = MagicMock()
    user_update.model_dump.return_value = {"role": "manager", "unit_id": 5}
    
    with patch("app.services.user_service._create_or_update_user_assignment", new_callable=AsyncMock) as mock_assign:
        
        # Execute
        updated_user, callback = await user_service.update_user(mock_db_session, db_user, user_update)
        
        # Assert
        # Transaction should have started
        mock_db_session.begin_nested.assert_called()
        
        # Assignment helper called due to changes
        mock_assign.assert_awaited_once()
        args = mock_assign.call_args[1]
        assert args["new_role"] == "manager"
        assert args["new_unit_id"] == 5

# =============================================================================
# BULK ACTION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_perform_bulk_action_delete(mock_db_session, mock_repo):
    """Test bulk delete delegates to various Repos."""
    user_ids = [2, 3]
    admin = User(id=1, role="admin")
    
    # Mock users found
    mock_u1 = User(id=2, username="u2")
    mock_u2 = User(id=3, username="u3")
    
    # Mock Repo Methods - FIX: return the users
    mock_repo.get_users_by_ids_for_delete.return_value = [mock_u1, mock_u2]
    mock_repo.count_consultations_by_officers = AsyncMock(return_value={})
    
    # Mock LeadRepository and SessionRepository patches
    with patch("app.repositories.LeadRepository") as MockLeadRepo, \
         patch("app.repositories.SessionRepository") as MockSessionRepo:
        
        mock_lead_repo = MockLeadRepo.return_value
        mock_session_repo = MockSessionRepo.return_value
        
        # FIX: Ensure unassign method is AsyncMock
        mock_lead_repo.unassign_leads_from_officers = AsyncMock(return_value=1)
        
        # Execute
        msg, callback = await user_service.perform_bulk_action(
            mock_db_session, "delete", user_ids, admin
        )
        
        # Assert
        assert "deleted 2 users" in msg
        mock_lead_repo.unassign_leads_from_officers.assert_awaited_with(user_ids)
        # Should verify users were deleted
        assert mock_db_session.delete.call_count == 2

@pytest.mark.asyncio
async def test_update_user_duplicate_email(mock_db_session, mock_repo):
    """Test update user fails if email exists for another user."""
    # Setup
    user = User(id=1, email="original@example.com", role="user", unit_id=None)
    update_data = MagicMock()
    update_data.model_dump.return_value = {"email": "conflict@example.com"}
    
    # Conflict user exists
    conflict_user = User(id=2, email="conflict@example.com")
    
    # Needs to patch get_user_by_email since it's used in update_user logic
    with patch("app.services.user_service.get_user_by_email", new_callable=AsyncMock) as mock_get_email:
        mock_get_email.return_value = conflict_user
        
        with pytest.raises(DuplicateResourceError):
            await user_service.update_user(mock_db_session, user, update_data)

@pytest.mark.asyncio
async def test_update_user_role_change_syncs_casbin(mock_db_session, mock_repo):
    """Test updating role triggers Casbin sync."""
    # Setup
    user = User(id=1, role="user", email="test@test.com", unit_id=None)
    update_data = MagicMock()
    update_data.model_dump.return_value = {"role": "officer"}
    
    mock_enforcer = AsyncMock()
    mock_enforcer.add_grouping_policy.return_value = True
    
    # Patch helper
    with patch("app.services.user_service._create_or_update_user_assignment", new_callable=AsyncMock) as mock_assign, \
         patch("app.services.user_service.get_user_by_email", new_callable=AsyncMock) as mock_get_email:
        
        mock_get_email.return_value = None # No conflict
        
        updated_user, callback = await user_service.update_user(
            mock_db_session, user, user_in=update_data, enforcer=mock_enforcer
        )
        
        # Verify Casbin removed old and added new
        # Need to check call args roughly
        mock_enforcer.remove_grouping_policy.assert_awaited()
        mock_enforcer.add_grouping_policy.assert_awaited()
        mock_enforcer.save_policy.assert_awaited()
        
@pytest.mark.asyncio
async def test_update_user_assignment_change_triggers_logic(mock_db_session, mock_repo):
    """Test changing unit_id triggers assignment helper."""
    # Setup
    user = User(id=1, unit_id=10, role="officer", email="test@test.com")
    update_data = MagicMock()
    update_data.model_dump.return_value = {"unit_id": 20} # Change unit
    
    with patch("app.services.user_service._create_or_update_user_assignment", new_callable=AsyncMock) as mock_assign, \
         patch("app.services.user_service.get_user_by_email", new_callable=AsyncMock):
        
        await user_service.update_user(mock_db_session, user, update_data)
        
        # Assert assignment helper was called
        mock_assign.assert_awaited_once()
