# tests/services/test_tuition_discount.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal
from datetime import date, timedelta

from app.models import TuitionDiscountPolicy, DiscountTypeEnum
from app.schemas.tuition_discount_policy import (
    TuitionDiscountPolicyCreate,
    TuitionDiscountPolicyUpdate,
    DiscountType
)
from app.services import tuition_discount_service as service
from app.utils.exceptions import BadRequest, DuplicateResourceError

# Constants for testing
POLICY_ID = 1
POLICY_CODE = "TEST2024"
USER_ID = 99


@pytest.fixture
def policy_model():
    """Fixture for TuitionDiscountPolicy model."""
    return TuitionDiscountPolicy(
        id=POLICY_ID,
        code=POLICY_CODE,
        name="Test Policy",
        discount_type="percentage",
        discount_value=Decimal("10.0"),
        is_active=True,
        is_stackable=True,
        priority=1
    )


@pytest.fixture
def mock_db_session():
    """Fixture for AsyncSession mock."""
    session = AsyncMock()
    return session


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_get_all_policies_success(mock_repo_class, mock_db_session, policy_model):
    """Test get_all_policies: Successful retrieval with count."""
    mock_repo = AsyncMock()
    mock_repo.get_filtered.return_value = (1, [policy_model])
    mock_repo_class.return_value = mock_repo
    
    policies, total = await service.get_all_policies(mock_db_session)
    
    assert total == 1
    assert len(policies) == 1
    assert policies[0].code == POLICY_CODE
    mock_repo.get_filtered.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_get_policy_by_id_success(mock_repo_class, mock_db_session, policy_model):
    """Test get_policy_by_id: Returns the correct policy."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = policy_model
    mock_repo_class.return_value = mock_repo
    
    result = await service.get_policy_by_id(mock_db_session, POLICY_ID)
    
    assert result == policy_model
    mock_repo.get_by_id.assert_awaited_once_with(POLICY_ID)


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_create_policy_success(mock_repo_class, mock_db_session, policy_model):
    """Test create_policy: Successfully creates a new policy."""
    create_data = TuitionDiscountPolicyCreate(
        code=POLICY_CODE,
        name="New Policy",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("15.0"),
        valid_from=date.today(),
        is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_code.return_value = None  # No duplicate
    mock_repo.create.return_value = policy_model
    mock_repo_class.return_value = mock_repo
    
    policy, post_commit = await service.create_policy(mock_db_session, create_data, USER_ID)
    
    assert policy == policy_model
    mock_repo.create.assert_awaited_once()
    assert post_commit is not None
    await post_commit()  # Verify callback runs without error


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_create_policy_duplicate_code(mock_repo_class, mock_db_session, policy_model):
    """Test create_policy: Raises ValueError on duplicate code."""
    create_data = TuitionDiscountPolicyCreate(
        code=POLICY_CODE,
        name="Duplicate Policy",
        discount_type=DiscountType.AMOUNT,
        discount_value=Decimal("1000000")
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_code.return_value = policy_model
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(DuplicateResourceError) as exc:
        await service.create_policy(mock_db_session, create_data)
    
    assert "already exists" in str(exc.value) or "đã tồn tại" in str(exc.value)


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_update_policy_success(mock_repo_class, mock_db_session, policy_model):
    """Test update_policy: Successfully updates existing policy."""
    update_data = TuitionDiscountPolicyUpdate(name="Updated Name")
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = policy_model
    mock_repo.update.return_value = policy_model
    mock_repo_class.return_value = mock_repo
    
    policy, post_commit = await service.update_policy(mock_db_session, POLICY_ID, update_data, USER_ID)
    
    assert policy == policy_model
    mock_repo.update.assert_awaited_once()
    await post_commit()


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_delete_policy_soft_success(mock_repo_class, mock_db_session, policy_model):
    """Test delete_policy: Successfully soft deletes a policy."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = policy_model
    mock_repo_class.return_value = mock_repo
    
    success, post_commit = await service.delete_policy(mock_db_session, POLICY_ID, hard_delete=False)
    
    assert success is True
    mock_repo.soft_delete.assert_awaited_once_with(policy_model)
    await post_commit()


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_calculate_discount_logic(mock_repo_class, mock_db_session):
    """Test calculation logic: percentage and stackable policies."""
    p1 = TuitionDiscountPolicy(
        id=1, code="P1", name="10% Off", 
        discount_type=DiscountTypeEnum.PERCENTAGE, discount_value=Decimal("10.0"),
        is_stackable=True, priority=10
    )
    p2 = TuitionDiscountPolicy(
        id=2, code="P2", name="1M Off", 
        discount_type=DiscountTypeEnum.AMOUNT, discount_value=Decimal("1000000.0"),
        is_stackable=True, priority=5
    )
    
    tuition = Decimal("10000000.0") # 10M
    policies = [p1, p2]
    
    total, applied = service.calculate_discount(tuition, policies)
    
    # 10% of 10M = 1M
    # + 1M fixed = 2M total
    assert total == Decimal("2000000.0")
    assert len(applied) == 2
    assert applied[0]["discount_amount"] == Decimal("1000000.0")
    assert applied[1]["discount_amount"] == Decimal("1000000.0")


@pytest.mark.asyncio
@patch("app.services.tuition_discount_service.TuitionDiscountRepository")
async def test_calculate_discount_non_stackable(mock_repo_class, mock_db_session):
    """Test calculation logic: stops at first non-stackable policy."""
    p1 = TuitionDiscountPolicy(
        id=1, code="P1", name="10% Off", 
        discount_type=DiscountTypeEnum.PERCENTAGE, discount_value=Decimal("10.0"),
        is_stackable=False, priority=10
    )
    p2 = TuitionDiscountPolicy(
        id=2, code="P2", name="1M Off", 
        discount_type=DiscountTypeEnum.AMOUNT, discount_value=Decimal("1000000.0"),
        is_stackable=True, priority=5
    )
    
    tuition = Decimal("10000000.0")
    policies = [p1, p2]
    
    total, applied = service.calculate_discount(tuition, policies)
    
    assert total == Decimal("1000000.0")
    assert len(applied) == 1 # Only P1 applied


@pytest.mark.asyncio
async def test_get_applicable_policies_gpa_filtering(mock_db_session):
    """Test get_applicable_policies: GPA filtering works correctly."""
    p1 = TuitionDiscountPolicy(
        id=1, code="GPA8", name="GPA 8+", 
        target_criteria={"min_gpa": 8.0}
    )
    
    # Mock repo
    mock_repo = AsyncMock()
    mock_repo.get_active_within_validity.return_value = [p1]
    
    with patch("app.services.tuition_discount_service._get_repo", return_value=mock_repo):
        # Student GPA 7.5 -> Should not match
        results = await service.get_applicable_policies(mock_db_session, student_gpa=7.5)
        assert len(results) == 0
        
        # Student GPA 8.5 -> Should match
        results = await service.get_applicable_policies(mock_db_session, student_gpa=8.5)
        assert len(results) == 1
        assert results[0].code == "GPA8"


@pytest.mark.asyncio
async def test_create_policy_invalid_json(mock_db_session):
    """Test create_policy: Raises BadRequest on invalid JSON structure."""
    create_data = TuitionDiscountPolicyCreate(
        code="INVALID_JSON",
        name="Invalid JSON Policy",
        discount_type=DiscountType.PERCENTAGE,
        discount_value=Decimal("10.0"),
        applicable_scope={"major_program_ids": "not a list"} # Should be List[int]
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_code.return_value = None
    
    with patch("app.services.tuition_discount_service._get_repo", return_value=mock_repo):
        with pytest.raises(BadRequest) as exc:
            await service.create_policy(mock_db_session, create_data)
        assert "không hợp lệ" in str(exc.value) or "invalid" in str(exc.value).lower()
