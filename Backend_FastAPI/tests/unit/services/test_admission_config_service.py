import pytest
from unittest.mock import AsyncMock, Mock
from app.services.admission_config_service import AdmissionConfigService
from app.utils.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.schemas.admission_config import SubjectCreate, SubjectGroupCreate, AdmissionMethodCreate

@pytest.mark.asyncio
async def test_create_subject_success():
    db = AsyncMock()
    service = AdmissionConfigService(db)
    service.repo.get_subject_by_code = AsyncMock(return_value=None)
    service.repo.create_subject = AsyncMock(return_value=Mock(id=1, code="SUB1"))
    
    data = SubjectCreate(code="SUB1", name_vi="Subject 1")
    user = Mock()
    
    subject, callback = await service.create_subject(data, user)
    
    assert subject.id == 1
    assert subject.code == "SUB1"
    service.repo.create_subject.assert_called_once()
    assert callback.__name__ == "_noop_callback"

@pytest.mark.asyncio
async def test_create_subject_duplicate():
    db = AsyncMock()
    service = AdmissionConfigService(db)
    service.repo.get_subject_by_code = AsyncMock(return_value=Mock())
    
    data = SubjectCreate(code="SUB1", name_vi="Subject 1")
    user = Mock()
    
    with pytest.raises(DuplicateResourceError):
        await service.create_subject(data, user)

@pytest.mark.asyncio
async def test_delete_subject_not_found():
    db = AsyncMock()
    service = AdmissionConfigService(db)
    service.repo.check_subject_usage = AsyncMock(return_value=False)
    service.repo.delete_subject = AsyncMock(return_value=False)

    user = Mock()
    
    with pytest.raises(ResourceNotFoundError):
        await service.delete_subject(999, user)

@pytest.mark.asyncio
async def test_create_subject_group_success():
    db = AsyncMock()
    service = AdmissionConfigService(db)
    service.repo.get_subject_group_by_code = AsyncMock(return_value=None)
    mock_group = Mock(id=1, code="GRP1")
    service.repo.create_subject_group = AsyncMock(return_value=mock_group)
    service.repo.update_subject_group_mappings = AsyncMock(return_value=mock_group)

    data = SubjectGroupCreate(code="GRP1", name="Group 1", subject_ids=[1, 2])
    user = Mock()

    group, callback = await service.create_subject_group(data, user)

    assert group == mock_group
    service.repo.create_subject_group.assert_called_once()
    service.repo.update_subject_group_mappings.assert_called_once()

@pytest.mark.asyncio
async def test_create_method_success():
    db = AsyncMock()
    service = AdmissionConfigService(db)
    service.repo.get_method_by_code = AsyncMock(return_value=None)
    mock_method = Mock(id=1, code="METH1")
    service.repo.create_method = AsyncMock(return_value=mock_method)
    
    data = AdmissionMethodCreate(code="METH1", name="Method 1")
    user = Mock()
    
    method, callback = await service.create_method(data, user)
    
    assert method == mock_method
    service.repo.create_method.assert_called_once()
