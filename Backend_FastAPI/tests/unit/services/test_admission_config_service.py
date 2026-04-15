import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch
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


# =============================================================================
# REGRESSION TEST — PR11
# =============================================================================

@pytest.mark.asyncio
async def test_preview_scoring_uses_criteria_policy_version():
    """
    Regression guard for PR11: /scoring/preview must stamp the snapshot
    with the policy_version carried by the AdmissionCriteria row, not
    the hardcoded "2025.1" string the handler used to pass.
    """
    from app.routers.admission_config import preview_scoring
    from app.schemas.admission_config import ScoringPreviewRequest

    # Arrange: repo returns a criteria with a distinctive policy_version
    expected_version = "TEST-PR11.regression"
    mock_criteria = Mock(
        code="TEST_CRIT",
        policy_version=expected_version,
        is_active=True,
        visibility_scope="global",
    )
    mock_repo = Mock()
    mock_repo.get_criteria_by_code = AsyncMock(return_value=mock_criteria)
    mock_repo.get_subject_group_by_code = AsyncMock(return_value=None)

    mock_user = Mock(role="admin", id=1)

    # Stub out the scoring service internals we don't exercise here
    mock_resolution = Mock(allowed_subjects=["math", "phys"])
    mock_result = Mock(
        status=Mock(value="valid"),
        passed=True,
        final_score=Decimal("8.5"),
        selected_subjects=["math", "phys"],
        subject_scores={"math": Decimal("9"), "phys": Decimal("8")},
        input_subject_count=2,
        used_subject_count=2,
        ignored_subjects=[],
        criteria_code="TEST_CRIT",
        selection_mode="fixed",
        scoring_method="sum",
        required_count=2,
        min_score_threshold=None,
        min_subject_score_threshold=None,
        failure_reasons=[],
        disqualification_codes=[],
    )

    request = ScoringPreviewRequest(
        criteria_code="TEST_CRIT",
        subject_scores={"math": 9.0, "phys": 8.0},
    )

    with patch(
        "app.routers.admission_config.verify_criteria_visibility",
    ) as mock_visibility, patch(
        "app.routers.admission_config.AdmissionScoringService.resolve_allowed_subjects",
        return_value=mock_resolution,
    ), patch(
        "app.routers.admission_config.AdmissionScoringService.calculate_score",
        return_value=mock_result,
    ), patch(
        "app.routers.admission_config.AdmissionScoringService.generate_snapshot",
    ) as mock_snapshot:
        mock_visibility.return_value = None
        mock_snapshot.return_value = {"__policy_version__": expected_version}

        # Act
        await preview_scoring(
            request=request,
            repo=mock_repo,
            current_user=mock_user,
        )

    # Assert: the handler passed criteria.policy_version to the snapshot builder
    mock_snapshot.assert_called_once()
    kwargs = mock_snapshot.call_args.kwargs
    assert kwargs["policy_version"] == expected_version, (
        f"Expected policy_version to come from criteria "
        f"({expected_version!r}); got {kwargs.get('policy_version')!r}. "
        "Handler must read from criteria, not hardcode."
    )
