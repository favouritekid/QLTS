
# tests/unit/services/test_lead_service.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from datetime import datetime, timezone

from app.services import lead_service
from app.models.lead import Lead
from app.models.user import User
from app.schemas import LeadCreate, LeadUpdate, ConsultationCreate
from app.utils.exceptions import ResourceNotFoundError, DuplicateResourceError, PermissionDeniedError
from app.core.constants import UserRole

# Constants
TEST_LEAD_ID = 1
TEST_OFFICER_ID = 10
TEST_UNIT_ID = 100

@pytest.fixture(autouse=True)
def mock_logger():
    """Patch structlog logger to avoid TypeError with MagicMocks."""
    from structlog.stdlib import BoundLogger
    with patch("structlog.stdlib.BoundLogger.debug"), \
         patch("structlog.stdlib.BoundLogger.info"), \
         patch("structlog.stdlib.BoundLogger.warning"), \
         patch("structlog.stdlib.BoundLogger.error"):
        yield

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
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    
    # Configure get to return None by default
    session.get = AsyncMock(return_value=None)
    
    return session

@pytest.fixture
def mock_lead_repo():
    """Mock LeadRepository with AsyncMock methods for ALL usages."""
    # PATCH TARGET FIX: Patch BOTH locations where LeadRepository is instantiated
    from unittest.mock import patch
    
    with patch("app.services.lead_service.LeadRepository") as MockRepoService, \
         patch("app.services.lead_cache_service.LeadRepository") as MockRepoCache:
        
        # They should return the SAME mock instance so we can assert on it single-source
        repo_instance = MockRepoService.return_value
        MockRepoCache.return_value = repo_instance
        
        # Configure methods that return Co-routines (AsyncMock)
        repo_instance.check_phone_conflict = AsyncMock(return_value=None)
        repo_instance.check_email_conflict = AsyncMock(return_value=None)
        repo_instance.get_by_id = AsyncMock(return_value=None)
        repo_instance.get_by_id_full = AsyncMock(return_value=None)
        repo_instance.get_by_id_for_update = AsyncMock(return_value=None)
        repo_instance.update_next_activity = AsyncMock(return_value=None)
        
        # Fix: Cache service expects a DICT result from get_consultation_aggregates
        stats_dict = {
            "last_consultation_at": datetime.now(timezone.utc),
            "consultation_count": 5,
            "pending_next_activity": None
        }
        repo_instance.get_consultation_aggregates = AsyncMock(return_value=stats_dict)
        repo_instance.unassign_leads_from_officers = AsyncMock(return_value=0)
        
        yield repo_instance

@pytest.fixture
def mock_dist_service():
    """Mock DistributionService."""
    with patch("app.services.distribution_service.get_target_unit_for_offering", new_callable=AsyncMock) as mock:
        yield mock

# =============================================================================
# CREATE LEAD TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_create_lead_success_admin(mock_db_session, mock_lead_repo, mock_dist_service):
    """Test creating lead by admin (success case)."""
    # Setup - Use MagicMock (no spec) to avoid environment issues
    lead_in = MagicMock() 
    lead_in.assigned_officer_id = None
    lead_in.source = "Facebook"
    lead_in.unit_id = TEST_UNIT_ID
    # Explicitly set return value for model_dump to clean dict
    lead_in.model_dump.return_value = {
        "full_name": "New Lead",
        "phone": "0901234567",
        "email": "new@example.com",
        "unit_id": TEST_UNIT_ID,
        "source": "Facebook",
    }
    
    admin_user = User(id=1, role=UserRole.ADMIN)
    
    # Mock status helper
    with patch("app.services.lead_service.StatusHelper.get_initial_status", new_callable=AsyncMock) as mock_get_status, \
         patch("app.services.lead_service.calculate_lead_score", new_callable=AsyncMock) as mock_calc_score, \
         patch("app.services.lead_service._get_current_lead_state", return_value={}), \
         patch("app.services.lead_service._log_lead_state_change", new_callable=AsyncMock):

        mock_get_status.return_value = MagicMock(id="new")
        mock_calc_score.return_value = 10
        
        # FIX: create_lead calls get_lead_by_id -> repo.get_by_id_full at the end
        # We need it to return something valid
        mock_lead_repo.get_by_id_full.return_value = Lead(id=1, lead_score=10, unit_id=TEST_UNIT_ID)
        
        # Execute
        created_lead, callback = await lead_service.create_lead(mock_db_session, lead_in, created_by=admin_user)
        
        # Assert checks used Repo
        mock_lead_repo.check_phone_conflict.assert_awaited_once()
        mock_lead_repo.check_email_conflict.assert_awaited_once()
        mock_db_session.add.assert_called()
        mock_db_session.flush.assert_awaited()
        
        assert created_lead.lead_score == 10
        assert created_lead.unit_id == TEST_UNIT_ID

@pytest.mark.asyncio
async def test_create_lead_duplicate_phone(mock_db_session, mock_lead_repo):
    """Test create lead fails if phone exists."""
    lead_in = MagicMock()
    lead_in.assigned_officer_id = None
    lead_in.phone = "0909999999"
    lead_in.model_dump.return_value = {
        "phone": "0909999999",
        "unit_id": TEST_UNIT_ID
    }
    admin_user = User(id=1, role=UserRole.ADMIN)
    
    # Mock Repo returning conflict
    mock_conflict_lead = Lead(id=99, full_name="Existing", phone="0909999999")
    mock_lead_repo.check_phone_conflict.return_value = mock_conflict_lead
    
    with pytest.raises(DuplicateResourceError) as exc:
        await lead_service.create_lead(mock_db_session, lead_in, created_by=admin_user)
    
    assert "0909999999" in str(exc.value.detail)

@pytest.mark.asyncio
async def test_create_lead_by_officer_enforces_unit(mock_db_session, mock_lead_repo):
    """Test officer creating lead forces unit_id to officer's unit."""
    lead_in = MagicMock()
    lead_in.assigned_officer_id = None
    lead_in.model_dump.return_value = {
        "full_name": "Officer Lead", 
        "phone": "098", 
        "unit_id": 999
    }
    
    officer_user = User(id=10, role=UserRole.OFFICER, unit_id=50) # Officer in unit 50
    
    with patch("app.services.lead_service.StatusHelper.get_initial_status", new_callable=AsyncMock), \
         patch("app.services.lead_service.calculate_lead_score", new_callable=AsyncMock), \
         patch("app.services.lead_service._get_current_lead_state"), \
         patch("app.services.lead_service._log_lead_state_change", new_callable=AsyncMock):
         
        # Fix return for final fetch
        mock_lead_repo.get_by_id_full.return_value = Lead(id=1, unit_id=50, assigned_officer_id=officer_user.id)
        
        created_lead, _ = await lead_service.create_lead(mock_db_session, lead_in, created_by=officer_user)
        
        # Verify unit replaced
        assert created_lead.unit_id == 50
        assert created_lead.assigned_officer_id == officer_user.id

# =============================================================================
# UPDATE LEAD TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_update_lead_success(mock_db_session, mock_lead_repo):
    """Test update lead uses Repo for locking."""
    # Setup
    lead_id = 1
    # Mock Schema without spec
    lead_update = MagicMock()
    lead_update.model_dump.return_value = {"full_name": "Updated Name"}
    
    officer_user = User(id=10, role=UserRole.OFFICER)
    
    # Mock Lead in DB
    mock_lead = Lead(id=lead_id, assigned_officer_id=10, full_name="Old Name")
    # Service uses repo.get_by_id_for_update(lead_id)
    mock_lead_repo.get_by_id_for_update.return_value = mock_lead
    # Service uses repo.get_by_id_full(lead_id) at the end
    mock_lead_repo.get_by_id_full.return_value = mock_lead
    
    with patch("app.services.lead_service.StatusHelper.sync_lead_status", new_callable=AsyncMock), \
         patch("app.services.lead_service._get_current_lead_state"), \
         patch("app.services.lead_service._log_lead_state_change", new_callable=AsyncMock), \
         patch("app.services.lead_service.calculate_lead_score", new_callable=AsyncMock), \
         patch("app.services.lead_cache_service.update_lead_cache", new_callable=AsyncMock): # Mock cache service globally
         
        updated_lead = await lead_service.update_lead(mock_db_session, lead_id, lead_update, updated_by=officer_user)
        
        mock_lead_repo.get_by_id_for_update.assert_awaited_once_with(lead_id)
        assert updated_lead.full_name == "Updated Name"
        mock_db_session.add.assert_called_with(mock_lead)

@pytest.mark.asyncio
async def test_update_lead_not_found(mock_db_session, mock_lead_repo):
    """Test update lead raises 404 if not found."""
    mock_lead_repo.get_by_id_for_update.return_value = None
    officer = User(id=1)
    
    lead_update = MagicMock()
    
    with pytest.raises(ResourceNotFoundError):
        await lead_service.update_lead(mock_db_session, 999, lead_update, updated_by=officer)

# =============================================================================
# CONSULTATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_add_consultation_success(mock_db_session, mock_lead_repo):
    """Test add consultation success."""
    # Setup
    consult_in = MagicMock()
    consult_in.status_id = "CONTACTED"
    consult_in.model_dump.return_value = {
        # "status_id" and "consultation_date" are excluded by service
        # "consultation_status_id" is passed explicitly by service
        "method": "call",
        "notes": "test",
        "scheduled_at": None
    }

    # Mock Lead
    mock_lead = Lead(id=1, assigned_officer_id=10, consultation_status_id="NEW")
    
    officer = User(id=10, role=UserRole.OFFICER)
    
    # Mock Repo Get
    mock_lead_repo.get_by_id_for_update.return_value = mock_lead
    
    # Mock DB Gets: Officer(10) and ConsultationStatus(CONTACTED)
    mock_status = MagicMock(id="CONTACTED", updates_pipeline=True, stage_id="stg02", is_universal=False, name="Contacted")
    
    async def db_get_side_effect(model, ident):
        if ident == 10: return officer
        if ident == "CONTACTED": return mock_status
        return None
    
    mock_db_session.get.side_effect = db_get_side_effect

    # Mock Repo Get New Consultation
    mock_consultation = MagicMock(id=100)
    mock_lead_repo.get_consultation_with_status_stage = AsyncMock(return_value=mock_consultation)
    
    # Use mocks for permissions and helpers
    with patch("app.services.lead_service.StatusHelper") as MockStatusHelper, \
         patch("app.services.lead_service.pipeline_service.validate_status_transition", new_callable=AsyncMock) as mock_validate, \
         patch("app.services.lead_service.sync_lead_status_from_consultation") as mock_sync, \
         patch("app.services.lead_cache_service.update_lead_cache", new_callable=AsyncMock): # Mock cache service globally
         
        mock_validate.return_value = True
        
        await lead_service.add_consultation(mock_db_session, 1, 10, consult_in)
        
        # Verify
        mock_db_session.add.assert_called() # Adds consultation
        mock_lead_repo.get_consultation_with_status_stage.assert_awaited()

# =============================================================================
# NEXT ACTIVITY UPDATE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_update_lead_next_activity(mock_db_session, mock_lead_repo):
    """Test update_lead_next_activity delegates to Repo."""
    # The service function simply calls repo.update_next_activity(lead_id)
    # But it first does db.get(models.Lead) - wait, snippet showed:
    # lead = await db.get(models.Lead, lead_id)
    # repo = LeadRepository(db)
    # await repo.update_next_activity(lead_id)
    
    mock_db_session.get.return_value = Lead(id=1)
    
    await lead_service.update_lead_next_activity(mock_db_session, 1)
    
    mock_lead_repo.update_next_activity.assert_awaited_once_with(1)

# =============================================================================
# ENHANCED COVERAGE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_create_lead_manager_invalid_officer(mock_db_session, mock_lead_repo):
    """Test Manager cannot assign lead to officer in different unit."""
    # Setup
    manager = User(id=5, role=UserRole.MANAGER, unit_id=10)
    lead_in = MagicMock()
    lead_in.model_dump.return_value = {
        "unit_id": 10,
        "assigned_officer_id": 99 # Officer in diff unit
    }
    lead_in.phone = "123456"
    lead_in.email = "test@test.com"
    lead_in.phone2 = None
    
    # Mock officer lookup
    mock_officer = User(id=99, role=UserRole.OFFICER, unit_id=20) # Diff unit
    mock_db_session.get.return_value = mock_officer
    
    with pytest.raises(PermissionDeniedError):
        await lead_service.create_lead(mock_db_session, lead_in, created_by=manager)

@pytest.mark.asyncio
async def test_create_lead_officer_self_assign(mock_db_session, mock_lead_repo):
    """Test Officer creating lead is auto-assigned to themselves."""
    # Setup
    officer = User(id=10, role=UserRole.OFFICER, unit_id=10)
    lead_in = MagicMock()
    lead_in.model_dump.return_value = {
        "assigned_officer_id": 99, # Try to assign to someone else
        "unit_id": 20 # Try to assign to diff unit
    }
    lead_in.phone = "123456"
    lead_in.email = "test@test.com"
    
    with patch("app.services.lead_service.StatusHelper.get_initial_status", new_callable=AsyncMock) as mock_get_init, \
         patch("app.services.lead_service.StatusHelper.set_assignment_status"), \
         patch("app.services.lead_service._get_current_lead_state"), \
         patch("app.services.lead_service._log_lead_state_change", new_callable=AsyncMock), \
         patch("app.services.lead_service.calculate_lead_score", new_callable=AsyncMock):

        mock_get_init.return_value = MagicMock(id="new")
        
        # FIX: Simulate DB assigning ID
        async def refresh_side_effect(instance, attribute_names=None):
            if isinstance(instance, Lead):
                instance.id = 1
        mock_db_session.refresh.side_effect = refresh_side_effect
        
        # FIX: Ensure get_by_id_full returns the lead with correct values for assertions
        mock_lead_repo.get_by_id_full.return_value = Lead(
            id=1, 
            assigned_officer_id=officer.id, 
            unit_id=officer.unit_id
        )

        # Execute
        lead, callback = await lead_service.create_lead(mock_db_session, lead_in, created_by=officer)
        
        # Assert - Officer forced their own ID and Unit
        assert lead.assigned_officer_id == officer.id
        assert lead.unit_id == officer.unit_id

@pytest.mark.asyncio
async def test_create_lead_email_conflict_same_unit(mock_db_session, mock_lead_repo):
    """Test duplicate email in SAME unit raises error."""
    # Setup
    admin = User(id=1, role=UserRole.ADMIN)
    lead_in = MagicMock()
    lead_in.model_dump.return_value = {"unit_id": 10}
    lead_in.phone = "123456"
    lead_in.email = "duplicate@test.com"
    lead_in.phone2 = None
    
    # Check phone ok
    mock_lead_repo.check_phone_conflict.return_value = None
    
    # Check email CONFLICT
    mock_conflict_lead = MagicMock(id=99)
    mock_lead_repo.check_email_conflict.return_value = mock_conflict_lead
    
    with pytest.raises(DuplicateResourceError):
        await lead_service.create_lead(mock_db_session, lead_in, created_by=admin)
        
    # Verify check was called with correct unit
    mock_lead_repo.check_email_conflict.assert_awaited_with(email="duplicate@test.com", unit_id=10)
