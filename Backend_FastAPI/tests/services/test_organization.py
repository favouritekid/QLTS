# tests/services/test_organization.py
# -*- coding: utf-8 -*-
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.services import organization_service
from app.utils.exceptions import DuplicateResourceError, ResourceNotFoundError, ForbiddenError, BadRequest

# === Fixtures ===

@pytest.fixture
def mock_db_session():
    """Create a mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session

@pytest.fixture
def mock_user():
    """Create a mock Admin User."""
    return models.User(id=1, username="testadmin", role="Admin")

@pytest.fixture
def mock_unit():
    """Sample Organization Unit."""
    return models.OrganizationUnit(id=10, name="Test Unit", type="Khoa", is_active=True)

@pytest.fixture
def mock_program(mock_unit):
    """Sample Major Program (Level 1)."""
    return models.MajorProgram(
        id=100, 
        name="Computer Science", 
        code="CS", 
        degree_level="Đại học",
        unit_id=mock_unit.id,
        is_active=True
    )

@pytest.fixture
def mock_offering(mock_program):
    """Sample Program Offering (Level 2)."""
    return models.ProgramOffering(
        id=1000,
        program_id=mock_program.id,
        offering_type="Chính quy",
        is_active=True
    )

@pytest.fixture
def mock_academic_info(mock_offering):
    """Sample Offering Academic Info (Level 3)."""
    return models.OfferingAcademicInfo(
        id=5000,
        offering_id=mock_offering.id,
        academic_year=2024,
        is_deleted=False
    )

# === Helper to mock IDOR check Success ===
@pytest.fixture(autouse=True)
def mock_idor_success(mocker):
    """Default to allowing access in tests unless overridden."""
    # This mocks deps.get_organizational_unit_for_user which _check_unit_access calls.
    # It returns a unit ID (10) that matches our mock_unit.id.
    return mocker.patch(
        "app.core.deps.get_organizational_unit_for_user",
        new_callable=AsyncMock,
        return_value=10 
    )

# =============================================================================
# TESTS: ORGANIZATION UNIT
# =============================================================================

@pytest.mark.asyncio
async def test_create_organization_unit_success(mock_db_session, mock_user, mocker):
    """Test creating unit with proper IDOR check and repository usage."""
    unit_in = schemas.OrganizationUnitCreate(name="New Unit", type="Khoa", parent_id=None)
    
    # Mock Repository
    mock_repo = mocker.patch("app.services.organization_service.OrganizationRepository", autospec=True)
    mock_repo.return_value.check_duplicate_name = AsyncMock(return_value=None)
    mock_repo.return_value.get_by_id = AsyncMock(return_value=None)
    
    # Mock internal get for return result
    mocker.patch("app.services.organization_service.get_organization_unit_by_id", 
                 new_callable=AsyncMock, 
                 return_value=models.OrganizationUnit(id=11, **unit_in.model_dump()))

    result, post_commit = await organization_service.create_organization_unit(
        mock_db_session, unit_in, current_user=mock_user
    )

    assert result.name == "New Unit"
    mock_db_session.add.assert_called_once()
    mock_db_session.flush.assert_called_once()
    assert callable(post_commit)

@pytest.mark.asyncio
async def test_update_organization_unit_idor_fail(mock_db_session, mock_user, mock_unit, mocker):
    """Test IDOR protection: User belonging to Unit A cannot update Unit B."""
    update_in = schemas.OrganizationUnitUpdate(name="Unique Hacked Name")
    
    # Mock IDOR check to fail
    mocker.patch(
        "app.core.deps.get_organizational_unit_for_user",
        new_callable=AsyncMock,
        side_effect=ForbiddenError("Access denied")
    )
    
    # Mock internal get
    mocker.patch("app.services.organization_service.get_organization_unit_by_id", 
                 new_callable=AsyncMock, 
                 return_value=mock_unit)

    with pytest.raises(ForbiddenError):
        await organization_service.update_organization_unit(
            mock_db_session, mock_unit.id, update_in, current_user=mock_user
        )

# =============================================================================
# TESTS: MAJOR PROGRAM (LEVEL 1)
# =============================================================================

@pytest.mark.asyncio
async def test_create_major_program_success(mock_db_session, mock_user, mock_unit, mocker):
    """Test Major Program creation with unit access check."""
    program_in = schemas.MajorProgramCreate(
        name="Software Engineering", 
        code="SE", 
        degree_level="Đại học",
        unit_id=mock_unit.id
    )
    
    # Mock Repository
    mock_repo = mocker.patch("app.services.organization_service.OrganizationRepository", autospec=True)
    mock_repo.return_value.check_duplicate_program_code = AsyncMock(return_value=None)
    mock_repo.return_value.get_by_id = AsyncMock(return_value=mock_unit)
    
    # Mock internal get
    mocker.patch("app.services.organization_service.get_major_program_by_id", 
                 new_callable=AsyncMock, 
                 return_value=models.MajorProgram(id=101, **program_in.model_dump()))

    result, post_commit = await organization_service.create_major_program(
        mock_db_session, program_in, current_user=mock_user
    )

    assert result.code == "SE"
    assert callable(post_commit)

# =============================================================================
# TESTS: PROGRAM OFFERING (LEVEL 2) & CASCADE DELETE
# =============================================================================

@pytest.mark.asyncio
async def test_delete_program_offering_cascade(mock_db_session, mock_user, mock_offering, mock_program, mocker):
    """Test cascading soft-delete from Offering to Academic Info."""
    
    # Mock service internals to provide context for IDOR check
    mocker.patch("app.services.organization_service.get_program_offering_by_id", 
                 new_callable=AsyncMock, 
                 return_value=mock_offering)
    mocker.patch("app.services.organization_service.get_major_program_by_id", 
                 new_callable=AsyncMock, 
                 return_value=mock_program)

    # Mock the bulk update (cascade)
    mock_execute = mocker.patch.object(mock_db_session, "execute", new_callable=AsyncMock)

    _, post_commit = await organization_service.delete_program_offering(
        mock_db_session, mock_offering.id, current_user=mock_user
    )

    # Verify soft delete of offering
    assert mock_offering.is_active is False
    
    # Verify cascade update call was made
    assert mock_execute.call_count >= 1
    stmt = mock_execute.call_args_list[0].args[0]
    sql_str = str(stmt).lower()
    assert "offering_academic_info" in sql_str
    assert "is_deleted" in sql_str

# =============================================================================
# TESTS: OFFERING ACADEMIC INFO (LEVEL 3)
# =============================================================================

@pytest.mark.asyncio
async def test_update_academic_info_immutable_history(mock_db_session, mock_user, mock_academic_info, mock_offering, mock_program, mocker):
    """Test that historical financial data (past years) cannot be updated."""
    
    # Mock info from a past year
    mock_academic_info.academic_year = datetime.now().year - 1
    mock_academic_info.tuition_fee_per_year = 1000.0
    
    update_in = schemas.OfferingAcademicInfoUpdate(tuition_fee_per_year=1200.0)
    
    # Mock context for IDOR check
    mocker.patch("app.services.organization_service.get_academic_info_by_id", new_callable=AsyncMock, return_value=mock_academic_info)
    mocker.patch("app.services.organization_service.get_program_offering_by_id", new_callable=AsyncMock, return_value=mock_offering)
    mocker.patch("app.services.organization_service.get_major_program_by_id", new_callable=AsyncMock, return_value=mock_program)

    with pytest.raises(BadRequest) as exc:
        await organization_service.update_academic_info(
            mock_db_session, mock_academic_info.id, update_in, current_user=mock_user
        )
    
    assert "Không thể thay đổi học phí" in str(exc.value.detail)

@pytest.mark.asyncio
async def test_restore_academic_info_success(mock_db_session, mock_user, mock_academic_info, mock_offering, mock_program, mocker):
    """Test restoring a soft-deleted academic info record."""
    
    mock_academic_info.is_deleted = True
    
    # Mock context
    mocker.patch("app.services.organization_service.get_academic_info_by_id", new_callable=AsyncMock, return_value=mock_academic_info)
    mocker.patch("app.services.organization_service.get_program_offering_by_id", new_callable=AsyncMock, return_value=mock_offering)
    mocker.patch("app.services.organization_service.get_major_program_by_id", new_callable=AsyncMock, return_value=mock_program)

    # Mock Repository for the IDOR check internally
    mock_repo = mocker.patch("app.services.organization_service.OrganizationRepository", autospec=True)
    mock_repo.return_value.get_academic_info_by_id = AsyncMock(return_value=mock_academic_info)

    result, post_commit = await organization_service.restore_academic_info(
        mock_db_session, mock_academic_info.id, current_user=mock_user
    )

    assert result.is_deleted is False
    assert result.updated_at is not None
    mock_db_session.flush.assert_called_once()
