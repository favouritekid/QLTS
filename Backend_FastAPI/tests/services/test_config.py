# tests/services/test_config.py
# -*- coding: utf-8 -*-
"""
✅ PATTERN A COMPLIANT - Config Service Tests

Tests now mock at Repository layer instead of raw DB session,
matching the refactored config_service.py that uses Repositories.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings
from app.models import OfficerAssignmentConfig, OrganizationUnit, SkillRequirementRule
from app.services import config_service
from app.utils.exceptions import BadRequest, DuplicateResourceError, ResourceNotFoundError

# Import constants
try:
    from tests.fixtures.constants import TestConfigData, TestOrgData
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

# Cache TTL từ settings
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS


# === Fixture cho session mock ===
@pytest.fixture
def mock_db_session():
    """Tạo một mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    return session


# === Dữ liệu mẫu ===
UNIT_ID = TestOrgData.UNIT_1["id"]
ASSIGNMENT_PARAMS = TestConfigData.ASSIGNMENT_PARAMS
ASSIGNMENT_CACHE_KEY = f"config:assignment:{UNIT_ID}"
ASSIGNMENT_CONFIG_MODEL = OfficerAssignmentConfig(
    id=1, unit_id=UNIT_ID, params=ASSIGNMENT_PARAMS
)
UNIT_MODEL = OrganizationUnit(**TestOrgData.UNIT_1)
SKILL_RULE_MODEL_1 = SkillRequirementRule(id=1, **TestConfigData.SKILL_RULE_1)
SKILL_RULE_CREATE_SCHEMA = schemas.SkillRuleCreate(**TestConfigData.SKILL_RULE_1)


# === Tests cho get_assignment_config ===


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_cache_miss(
    mock_repo_class, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Cache miss, đọc DB via Repository, ghi cache."""
    # Setup repository mock
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = ASSIGNMENT_CONFIG_MODEL
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert result == ASSIGNMENT_PARAMS
    mock_redis_get.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    mock_repo.get_by_unit_id.assert_awaited_once_with(UNIT_ID)
    mock_redis_set.assert_awaited_once_with(
        ASSIGNMENT_CACHE_KEY, json.dumps(ASSIGNMENT_PARAMS), ex=CACHE_TTL
    )


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
async def test_get_assignment_config_cache_hit(
    mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Cache hit."""
    cached_data = {"strategy": "cached", "value": 99}
    mock_redis_get.return_value = json.dumps(cached_data)
    
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert result == cached_data
    mock_redis_get.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    mock_redis_set.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_db_not_found(
    mock_repo_class, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Không tìm thấy config trong DB (404)."""
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert exc_info.value.detail == f"Assignment config for unit {UNIT_ID} not found."
    mock_repo.get_by_unit_id.assert_awaited_once_with(UNIT_ID)


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, side_effect=redis.RedisError("Get failed"))
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_redis_get_error(
    mock_repo_class, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Lỗi Redis GET, đọc từ DB (fail-open)."""
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = ASSIGNMENT_CONFIG_MODEL
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert result == ASSIGNMENT_PARAMS
    mock_repo.get_by_unit_id.assert_awaited_once_with(UNIT_ID)
    mock_redis_set.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock, side_effect=redis.RedisError("Set failed"))
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_redis_set_error(
    mock_repo_class, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Lỗi Redis SET, vẫn trả về data DB."""
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = ASSIGNMENT_CONFIG_MODEL
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert result == ASSIGNMENT_PARAMS
    mock_repo.get_by_unit_id.assert_awaited_once_with(UNIT_ID)


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_empty_params(
    mock_repo_class, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Raises ResourceNotFoundError if params is empty/None."""
    config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params=None)
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = config
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert "not found or has no params" in exc_info.value.detail.lower()


# === Tests cho update_assignment_config ===


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock, return_value=1)
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_update_config_create_success(
    mock_repo_class, mock_org_repo_class, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: Tạo mới thành công."""
    new_params = {"strategy": "new", "limit": 10}
    new_config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params=new_params)
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id_for_update.return_value = None  # Config chưa có
    mock_repo.create.return_value = new_config
    mock_repo_class.return_value = mock_repo
    
    mock_org_repo = AsyncMock()
    mock_org_repo.get_by_id.return_value = UNIT_MODEL
    mock_org_repo_class.return_value = mock_org_repo
    
    result_model, post_commit = await config_service.update_assignment_config(
        mock_db_session, UNIT_ID, new_params
    )
    
    # Execute post-commit
    await post_commit()
    
    mock_repo.get_by_unit_id_for_update.assert_awaited_once_with(UNIT_ID)
    mock_org_repo.get_by_id.assert_awaited_once_with(UNIT_ID)
    mock_repo.create.assert_awaited_once()
    mock_redis_delete.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    assert result_model == new_config


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock, return_value=1)
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_update_config_update_success(
    mock_repo_class, mock_org_repo_class, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: Cập nhật thành công."""
    updated_params = {"strategy": "updated", "value": 5}
    existing_config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params={"old": 1})
    updated_config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params=updated_params)
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id_for_update.return_value = existing_config
    mock_repo.update.return_value = updated_config
    mock_repo_class.return_value = mock_repo
    
    mock_org_repo = AsyncMock()
    mock_org_repo.get_by_id.return_value = UNIT_MODEL
    mock_org_repo_class.return_value = mock_org_repo
    
    result_model, post_commit = await config_service.update_assignment_config(
        mock_db_session, UNIT_ID, updated_params
    )
    
    # Execute post-commit
    await post_commit()
    
    mock_repo.get_by_unit_id_for_update.assert_awaited_once_with(UNIT_ID)
    mock_repo.update.assert_awaited_once()
    mock_redis_delete.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    assert result_model == updated_config


@pytest.mark.asyncio
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_update_config_unit_not_found(mock_repo_class, mock_org_repo_class, mock_db_session):
    """Test update_assignment_config: Unit ID không tồn tại (404)."""
    mock_repo = AsyncMock()
    mock_repo_class.return_value = mock_repo
    
    mock_org_repo = AsyncMock()
    mock_org_repo.get_by_id.return_value = None  # Unit không có
    mock_org_repo_class.return_value = mock_org_repo
    
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.update_assignment_config(
            mock_db_session, UNIT_ID, {"a": 1}
        )
    
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock)
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_update_config_db_commit_error(
    mock_repo_class, mock_org_repo_class, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: Lỗi khi flush DB."""
    from sqlalchemy.exc import SQLAlchemyError
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id_for_update.return_value = None
    mock_repo.create.side_effect = SQLAlchemyError("Create failed")
    mock_repo_class.return_value = mock_repo
    
    mock_org_repo = AsyncMock()
    mock_org_repo.get_by_id.return_value = UNIT_MODEL
    mock_org_repo_class.return_value = mock_org_repo
    
    with pytest.raises(SQLAlchemyError):
        await config_service.update_assignment_config(
            mock_db_session, UNIT_ID, {"a": 1}
        )
    
    mock_redis_delete.assert_not_awaited()  # Không xóa cache nếu commit lỗi


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock, side_effect=redis.RedisError("Delete failed"))
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_update_config_redis_delete_error(
    mock_repo_class, mock_org_repo_class, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: DB thành công, lỗi khi xóa cache."""
    new_config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params={"a": 1})
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id_for_update.return_value = None
    mock_repo.create.return_value = new_config
    mock_repo_class.return_value = mock_repo
    
    mock_org_repo = AsyncMock()
    mock_org_repo.get_by_id.return_value = UNIT_MODEL
    mock_org_repo_class.return_value = mock_org_repo
    
    result_model, post_commit = await config_service.update_assignment_config(
        mock_db_session, UNIT_ID, {"a": 1}
    )
    
    # Execute post-commit (should handle Redis error gracefully)
    await post_commit()
    
    assert result_model is not None


# === Tests cho Skill Rules ===


@pytest.mark.asyncio
@patch("app.services.config_service.SkillRuleRepository")
async def test_get_all_skill_rules_success(mock_repo_class, mock_db_session):
    """Test get_all_skill_rules: Trả về danh sách rule via Repository."""
    mock_rules = [
        SKILL_RULE_MODEL_1,
        SkillRequirementRule(
            id=2, lead_attribute="loc", attribute_value="hcm", required_skill="SalesHCM"
        ),
    ]
    mock_repo = AsyncMock()
    mock_repo.get_all_rules.return_value = mock_rules
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_all_skill_rules(mock_db_session)
    
    mock_repo.get_all_rules.assert_awaited_once()
    assert result == mock_rules


@pytest.mark.asyncio
@patch("app.services.config_service.SkillRuleRepository")
async def test_create_skill_rule_success(mock_repo_class, mock_db_session):
    """Test create_skill_rule: Tạo thành công."""
    mock_repo = AsyncMock()
    mock_repo.create.return_value = SKILL_RULE_MODEL_1
    mock_repo_class.return_value = mock_repo
    
    result_rule, post_commit = await config_service.create_skill_rule(
        mock_db_session, SKILL_RULE_CREATE_SCHEMA
    )
    
    await post_commit()
    
    mock_repo.create.assert_awaited_once()
    assert result_rule == SKILL_RULE_MODEL_1


@pytest.mark.asyncio
@patch("app.services.config_service.SkillRuleRepository")
async def test_delete_skill_rule_success(mock_repo_class, mock_db_session):
    """Test delete_skill_rule: Xóa thành công."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = SKILL_RULE_MODEL_1
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_skill_rule(mock_db_session, 1)
    
    await post_commit()
    
    mock_repo.get_by_id.assert_awaited_once_with(1)
    mock_repo.delete.assert_awaited_once_with(SKILL_RULE_MODEL_1)


@pytest.mark.asyncio
@patch("app.services.config_service.SkillRuleRepository")
async def test_delete_skill_rule_not_found(mock_repo_class, mock_db_session):
    """Test delete_skill_rule: Rule không tồn tại (404)."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None  # Không tìm thấy rule
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.delete_skill_rule(mock_db_session, 999)
    
    assert "not found" in exc_info.value.detail.lower()


# =============================================================================
# DEGREE LEVEL TESTS
# =============================================================================

from app.models import ConfigDegreeLevel
from app.utils.exceptions import BadRequest


@pytest.fixture
def degree_level_model():
    """Sample ConfigDegreeLevel model."""
    return ConfigDegreeLevel(
        id=1, code="dai_hoc", name="Đại học", display_order=1, is_active=True
    )


@pytest.fixture
def degree_level_create_schema():
    """Sample ConfigDegreeLevelCreate schema."""
    return schemas.ConfigDegreeLevelCreate(
        code="thac_si", name="Thạc sĩ", display_order=2, is_active=True
    )


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_get_degree_levels_success(mock_repo_class, mock_db_session, degree_level_model):
    """Test get_degree_levels: Returns list of active degree levels."""
    mock_levels = [degree_level_model]
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = mock_levels
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_degree_levels(mock_db_session, active_only=True)
    
    mock_repo.get_all_active.assert_awaited_once_with(True)
    assert result == mock_levels


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_get_degree_levels_empty(mock_repo_class, mock_db_session):
    """Test get_degree_levels: Returns empty list when no levels exist."""
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = []
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_degree_levels(mock_db_session)
    
    assert result == []


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_get_degree_levels_include_inactive(mock_repo_class, mock_db_session, degree_level_model):
    """Test get_degree_levels: Returns all levels including inactive when active_only=False."""
    inactive_level = ConfigDegreeLevel(
        id=2, code="cao_dang", name="Cao đẳng", display_order=0, is_active=False
    )
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = [degree_level_model, inactive_level]
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_degree_levels(mock_db_session, active_only=False)
    
    mock_repo.get_all_active.assert_awaited_once_with(False)
    assert len(result) == 2


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_get_degree_level_by_id_success(mock_repo_class, mock_db_session, degree_level_model):
    """Test get_degree_level_by_id: Returns level when found."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_degree_level_by_id(mock_db_session, 1)
    
    mock_repo.get_by_id.assert_awaited_once_with(1)
    assert result == degree_level_model


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_get_degree_level_by_id_not_found(mock_repo_class, mock_db_session):
    """Test get_degree_level_by_id: Raises ResourceNotFoundError when not found."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.get_degree_level_by_id(mock_db_session, 999)
    
    assert "999" in exc_info.value.detail


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_create_degree_level_success(mock_repo_class, mock_db_session, degree_level_create_schema):
    """Test create_degree_level: Creates successfully with unique code and name."""
    new_level = ConfigDegreeLevel(
        id=2, code=degree_level_create_schema.code, name=degree_level_create_schema.name,
        display_order=degree_level_create_schema.display_order, is_active=True
    )
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = False
    mock_repo.create.return_value = new_level
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.create_degree_level(mock_db_session, degree_level_create_schema)
    
    await post_commit()
    
    mock_repo.check_code_exists.assert_awaited_once_with(degree_level_create_schema.code)
    mock_repo.check_name_exists.assert_awaited_once_with(degree_level_create_schema.name)
    mock_repo.create.assert_awaited_once()
    assert result.code == degree_level_create_schema.code


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_create_degree_level_duplicate_code(mock_repo_class, mock_db_session, degree_level_create_schema):
    """Test create_degree_level: Raises BadRequest when code already exists."""
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = True  # Code exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.create_degree_level(mock_db_session, degree_level_create_schema)
    
    assert "code" in exc_info.value.detail.lower()
    mock_repo.create.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_create_degree_level_duplicate_name(mock_repo_class, mock_db_session, degree_level_create_schema):
    """Test create_degree_level: Raises BadRequest when name already exists."""
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = True  # Name exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.create_degree_level(mock_db_session, degree_level_create_schema)
    
    assert "name" in exc_info.value.detail.lower()
    mock_repo.create.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_update_degree_level_success(mock_repo_class, mock_db_session, degree_level_model):
    """Test update_degree_level: Updates successfully."""
    update_schema = schemas.ConfigDegreeLevelUpdate(name="Đại học (Updated)")
    updated_level = ConfigDegreeLevel(
        id=1, code="dai_hoc", name="Đại học (Updated)", display_order=1, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.check_name_exists.return_value = False
    mock_repo.update.return_value = updated_level
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.update_degree_level(mock_db_session, 1, update_schema)
    
    await post_commit()
    
    assert result.name == "Đại học (Updated)"


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_update_degree_level_not_found(mock_repo_class, mock_db_session):
    """Test update_degree_level: Raises ResourceNotFoundError when level not found."""
    update_schema = schemas.ConfigDegreeLevelUpdate(name="New Name")
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.update_degree_level(mock_db_session, 999, update_schema)


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_update_degree_level_duplicate_code(mock_repo_class, mock_db_session, degree_level_model):
    """Test update_degree_level: Raises BadRequest when updating to existing code."""
    update_schema = schemas.ConfigDegreeLevelUpdate(code="existing_code")
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.check_code_exists.return_value = True  # New code already exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.update_degree_level(mock_db_session, 1, update_schema)
    
    assert "code" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_delete_degree_level_soft_delete_success(mock_repo_class, mock_db_session, degree_level_model):
    """Test delete_degree_level: Soft deletes (sets is_active=False)."""
    soft_deleted = ConfigDegreeLevel(
        id=1, code="dai_hoc", name="Đại học", display_order=1, is_active=False
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.is_used_by_programs.return_value = False
    mock_repo.soft_delete.return_value = soft_deleted
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_degree_level(mock_db_session, 1, soft_delete=True)
    
    await post_commit()
    
    mock_repo.soft_delete.assert_awaited_once()
    mock_repo.delete.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_delete_degree_level_hard_delete_success(mock_repo_class, mock_db_session, degree_level_model):
    """Test delete_degree_level: Hard deletes (removes record)."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.is_used_by_programs.return_value = False
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_degree_level(mock_db_session, 1, soft_delete=False)
    
    await post_commit()
    
    mock_repo.delete.assert_awaited_once()
    mock_repo.soft_delete.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_delete_degree_level_in_use(mock_repo_class, mock_db_session, degree_level_model):
    """Test delete_degree_level: Raises BadRequest when level is in use."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.is_used_by_programs.return_value = True  # In use
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.delete_degree_level(mock_db_session, 1)
    
    assert "being used" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_delete_degree_level_not_found(mock_repo_class, mock_db_session):
    """Test delete_degree_level: Raises ResourceNotFoundError when not found."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.delete_degree_level(mock_db_session, 999)


# =============================================================================
# OFFERING TYPE TESTS
# =============================================================================

from app.models import ConfigOfferingType


@pytest.fixture
def offering_type_model():
    """Sample ConfigOfferingType model."""
    return ConfigOfferingType(
        id=1, code="chinh_quy", name="Chính quy", display_order=1, is_active=True
    )


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_get_offering_types_success(mock_repo_class, mock_db_session, offering_type_model):
    """Test get_offering_types: Returns list of active offering types."""
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = [offering_type_model]
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_offering_types(mock_db_session)
    
    assert len(result) == 1
    assert result[0].code == "chinh_quy"


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_get_offering_type_by_id_not_found(mock_repo_class, mock_db_session):
    """Test get_offering_type_by_id: Raises ResourceNotFoundError when not found."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.get_offering_type_by_id(mock_db_session, 999)


# =============================================================================
# DOCUMENT TYPE TESTS
# =============================================================================

from app.models import ConfigDocumentType


@pytest.fixture
def document_type_model():
    """Sample ConfigDocumentType model."""
    return ConfigDocumentType(
        id=1, code="cmnd", name="CMND/CCCD", display_order=1, is_active=True
    )


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_get_document_types_success(mock_repo_class, mock_db_session, document_type_model):
    """Test get_document_types: Returns list of active document types."""
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = [document_type_model]
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_document_types(mock_db_session)
    
    assert len(result) == 1
    assert result[0].code == "cmnd"


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_get_document_type_by_id_not_found(mock_repo_class, mock_db_session):
    """Test get_document_type_by_id: Raises ResourceNotFoundError when not found."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.get_document_type_by_id(mock_db_session, 999)


# =============================================================================
# OFFERING TYPE CRUD TESTS
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_create_offering_type_success(mock_repo_class, mock_db_session, offering_type_model):
    """Test create_offering_type: Creates successfully with unique code and name."""
    create_schema = schemas.ConfigOfferingTypeCreate(
        code="lien_thong", name="Liên thông", display_order=2, is_active=True
    )
    
    new_type = ConfigOfferingType(
        id=2, code="lien_thong", name="Liên thông", display_order=2, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = False
    mock_repo.create.return_value = new_type
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.create_offering_type(mock_db_session, create_schema)
    
    await post_commit()
    
    mock_repo.create.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_create_offering_type_duplicate_code(mock_repo_class, mock_db_session):
    """Test create_offering_type: Raises BadRequest when code already exists."""
    create_schema = schemas.ConfigOfferingTypeCreate(
        code="chinh_quy", name="New Name", display_order=1, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = True  # Code exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.create_offering_type(mock_db_session, create_schema)
    
    assert "code" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_update_offering_type_cascade_name_change(mock_repo_class, mock_db_session, offering_type_model):
    """Test update_offering_type: Cascades name changes to ProgramOfferings."""
    update_schema = schemas.ConfigOfferingTypeUpdate(name="Chính quy (Updated)")
    
    # Mock program offering for cascade
    from app.models import ProgramOffering
    mock_offering = MagicMock(spec=ProgramOffering)
    mock_offering.offering_type = "Chính quy"
    
    # Mock updated offering type
    updated_type = ConfigOfferingType(
        id=1, code="chinh_quy", name="Chính quy (Updated)", display_order=1, is_active=True
    )
    
    # Mock repository
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = offering_type_model
    mock_repo.check_name_exists.return_value = False  # No duplicate name
    mock_repo.get_offerings_by_type_name.return_value = [mock_offering]
    mock_repo.update.return_value = updated_type
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.update_offering_type(mock_db_session, 1, update_schema)
    
    await post_commit()
    
    # Verify repository methods were called
    mock_repo.check_name_exists.assert_awaited_once()
    mock_repo.get_offerings_by_type_name.assert_awaited_once_with("Chính quy")
    mock_repo.update.assert_awaited_once()
    
    # Verify the cascade happened
    assert mock_offering.offering_type == "Chính quy (Updated)"


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_delete_offering_type_in_use(mock_repo_class, mock_db_session, offering_type_model):
    """Test delete_offering_type: Raises BadRequest when type is in use by ProgramOfferings."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = offering_type_model
    mock_repo.is_used_by_offerings.return_value = True  # In use
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.delete_offering_type(mock_db_session, 1)
    
    assert "being used" in exc_info.value.detail.lower()
    mock_repo.is_used_by_offerings.assert_awaited_once_with("Chính quy")


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_delete_offering_type_soft_delete_success(mock_repo_class, mock_db_session, offering_type_model):
    """Test delete_offering_type: Soft deletes (sets is_active=False)."""
    soft_deleted = ConfigOfferingType(
        id=1, code="chinh_quy", name="Chính quy", display_order=1, is_active=False
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = offering_type_model
    mock_repo.is_used_by_offerings.return_value = False  # Not in use
    mock_repo.soft_delete.return_value = soft_deleted
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_offering_type(mock_db_session, 1, soft_delete=True)
    
    await post_commit()
    
    mock_repo.soft_delete.assert_awaited_once()
    mock_repo.delete.assert_not_awaited()


# =============================================================================
# DOCUMENT TYPE CRUD TESTS
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_create_document_type_success(mock_repo_class, mock_db_session, document_type_model):
    """Test create_document_type: Creates successfully."""
    create_schema = schemas.ConfigDocumentTypeCreate(
        code="hoc_ba", name="Học bạ", display_order=2, is_active=True
    )
    
    new_type = ConfigDocumentType(
        id=2, code="hoc_ba", name="Học bạ", display_order=2, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = False
    mock_repo.create.return_value = new_type
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.create_document_type(mock_db_session, create_schema)
    
    await post_commit()
    
    mock_repo.create.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_create_document_type_duplicate_code(mock_repo_class, mock_db_session):
    """Test create_document_type: Raises error when code exists."""
    create_schema = schemas.ConfigDocumentTypeCreate(
        code="cmnd", name="New Name", display_order=1, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = True  # Code exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises((BadRequest, DuplicateResourceError)):
        await config_service.create_document_type(mock_db_session, create_schema)


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_create_document_type_duplicate_name(mock_repo_class, mock_db_session):
    """Test create_document_type: Raises error when name exists."""
    create_schema = schemas.ConfigDocumentTypeCreate(
        code="new_code", name="CMND", display_order=1, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = True  # Name exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(DuplicateResourceError):
        await config_service.create_document_type(mock_db_session, create_schema)


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_update_document_type_success(mock_repo_class, mock_db_session, document_type_model):
    """Test update_document_type: Updates successfully."""
    update_schema = schemas.ConfigDocumentTypeUpdate(name="Updated Name")
    
    updated_type = ConfigDocumentType(
        id=1, code="cmnd", name="Updated Name", display_order=1, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = document_type_model
    mock_repo.check_name_exists.return_value = False
    mock_repo.update.return_value = updated_type
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.update_document_type(mock_db_session, 1, update_schema)
    
    await post_commit()
    
    mock_repo.update.assert_awaited_once()
    assert result.name == "Updated Name"


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_update_document_type_not_found(mock_repo_class, mock_db_session):
    """Test update_document_type: Raises ResourceNotFoundError."""
    update_schema = schemas.ConfigDocumentTypeUpdate(name="Updated")
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.update_document_type(mock_db_session, 999, update_schema)


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_update_document_type_duplicate_code(mock_repo_class, mock_db_session, document_type_model):
    """Test update_document_type: Raises BadRequest when code exists."""
    update_schema = schemas.ConfigDocumentTypeUpdate(code="existing_code")
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = document_type_model
    mock_repo.check_code_exists.return_value = True  # Code already exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest):
        await config_service.update_document_type(mock_db_session, 1, update_schema)


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_delete_document_type_soft_delete_success(mock_repo_class, mock_db_session, document_type_model):
    """Test delete_document_type: Soft deletes successfully."""
    soft_deleted = ConfigDocumentType(
        id=1, code="cmnd", name="CMND", display_order=1, is_active=False
    )
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = document_type_model
    mock_repo.soft_delete.return_value = soft_deleted
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_document_type(mock_db_session, 1, soft_delete=True)
    
    await post_commit()
    
    mock_repo.soft_delete.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_delete_document_type_hard_delete_success(mock_repo_class, mock_db_session, document_type_model):
    """Test delete_document_type: Hard deletes successfully."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = document_type_model
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_document_type(mock_db_session, 1, soft_delete=False)
    
    await post_commit()
    
    mock_repo.delete.assert_awaited_once_with(document_type_model)


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_delete_document_type_not_found(mock_repo_class, mock_db_session):
    """Test delete_document_type: Raises ResourceNotFoundError."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.delete_document_type(mock_db_session, 999)


# =============================================================================
# DISTRIBUTION RULES - MISSING TESTS
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_get_all_distribution_rules_success(mock_repo_class, mock_db_session, distribution_rule_model):
    """Test get_all_distribution_rules: Returns all rules via Repository."""
    mock_repo = AsyncMock()
    mock_repo.get_all_with_relations.return_value = [distribution_rule_model]
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_all_distribution_rules(mock_db_session)
    
    assert len(result) == 1
    mock_repo.get_all_with_relations.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_get_all_distribution_rules_empty(mock_repo_class, mock_db_session):
    """Test get_all_distribution_rules: Returns empty list via Repository."""
    mock_repo = AsyncMock()
    mock_repo.get_all_with_relations.return_value = []
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_all_distribution_rules(mock_db_session)
    
    assert result == []


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_get_distribution_rule_by_id_success(mock_repo_class, mock_db_session, distribution_rule_model):
    """Test get_distribution_rule_by_id: Returns rule via Repository."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = distribution_rule_model
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_distribution_rule_by_id(mock_db_session, 1)
    
    assert result == distribution_rule_model
    mock_repo.get_by_id.assert_awaited_once_with(1)


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_get_distribution_rule_by_id_not_found(mock_repo_class, mock_db_session):
    """Test get_distribution_rule_by_id: Raises ResourceNotFoundError."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.get_distribution_rule_by_id(mock_db_session, 999)


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_update_distribution_rule_success(mock_repo_class, mock_db_session, distribution_rule_model):
    """Test update_distribution_rule: Updates successfully via Repository."""
    update_schema = schemas.DistributionRuleUpdate(priority=2, percentage=30.0)
    
    mock_repo = AsyncMock()
    mock_repo.update_and_fetch.return_value = distribution_rule_model
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.update_distribution_rule(mock_db_session, 1, update_schema)
    
    await post_commit()
    
    mock_repo.update_and_fetch.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_update_distribution_rule_not_found(mock_repo_class, mock_db_session):
    """Test update_distribution_rule: Raises ResourceNotFoundError."""
    update_schema = schemas.DistributionRuleUpdate(priority=2)
    
    mock_repo = AsyncMock()
    mock_repo.update_and_fetch.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.update_distribution_rule(mock_db_session, 999, update_schema)


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_update_distribution_rule_duplicate(mock_repo_class, mock_db_session):
    """Test update_distribution_rule: Raises BadRequest if update creates a duplicate."""
    from app.models import OfferingDistributionConfig
    
    # 1. Database Rule (Real object with explicit values for comparison)
    db_rule = OfferingDistributionConfig()
    db_rule.id = 1
    db_rule.offering_id = 10
    db_rule.unit_id = 20
    db_rule.is_active = False
    db_rule.weight = 100
    db_rule.priority = 1
    
    update_schema = schemas.DistributionRuleUpdate(unit_id=30) # 30 != 20
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = db_rule
    mock_repo.check_duplicate = AsyncMock(return_value=True)
    
    # 2. Fallback Object (Full data to pass Pydantic if logic fails)
    # This prevents ValidationError from masking the "DID NOT RAISE" error
    mock_result = MagicMock(spec=OfferingDistributionConfig)
    mock_result.id = 1
    mock_result.offering_id = 10
    mock_result.unit_id = 30
    mock_result.weight = 100
    mock_result.priority = 1
    mock_result.is_active = False
    mock_result.unit = MagicMock()
    mock_result.unit.name = "Fallback Unit"
    mock_result.offering = MagicMock()
    mock_result.offering.offering_type = "Fallback Type"
    mock_result.offering.program = MagicMock()
    mock_result.offering.program.name = "Fallback Program"
    
    mock_repo.update_and_fetch.return_value = mock_result
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.update_distribution_rule(mock_db_session, 1, update_schema)
    
    assert "already exists" in exc_info.value.detail.lower()
    mock_repo.check_duplicate.assert_awaited_once_with(10, 30, exclude_id=1)


# =============================================================================
# ADDITIONAL EDGE CASES - MEDIUM PRIORITY
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_create_offering_type_duplicate_name(mock_repo_class, mock_db_session):
    """Test create_offering_type: Raises BadRequest when name exists."""
    create_schema = schemas.ConfigOfferingTypeCreate(
        code="new_code", name="Chính quy", display_order=1, is_active=True
    )
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = True  # Name exists
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.create_offering_type(mock_db_session, create_schema)
    
    assert "name" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_update_offering_type_not_found(mock_repo_class, mock_db_session):
    """Test update_offering_type: Raises ResourceNotFoundError."""
    update_schema = schemas.ConfigOfferingTypeUpdate(name="Updated")
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.update_offering_type(mock_db_session, 999, update_schema)


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_delete_offering_type_not_found(mock_repo_class, mock_db_session):
    """Test delete_offering_type: Raises ResourceNotFoundError."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.delete_offering_type(mock_db_session, 999)


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_get_offering_types_empty(mock_repo_class, mock_db_session):
    """Test get_offering_types: Returns empty list when no types."""
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = []
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_offering_types(mock_db_session)
    
    assert result == []


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_get_document_types_empty(mock_repo_class, mock_db_session):
    """Test get_document_types: Returns empty list when no types."""
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = []
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_document_types(mock_db_session)
    
    assert result == []


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

from app.utils.exceptions import DuplicateResourceError


@pytest.mark.asyncio
@patch("app.services.config_service.SkillRuleRepository")
async def test_get_all_skill_rules_empty(mock_repo_class, mock_db_session):
    """Test get_all_skill_rules: Returns empty list when no rules exist."""
    mock_repo = AsyncMock()
    mock_repo.get_all_rules.return_value = []
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_all_skill_rules(mock_db_session)
    
    assert result == []


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_empty_params(mock_repo_class, mock_redis_get, mock_db_session):
    """Test get_assignment_config: Handles config with empty/None params."""
    config_with_empty_params = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params=None)
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = config_with_empty_params
    mock_repo_class.return_value = mock_repo
    
    # This should handle None params gracefully or raise appropriate error
    try:
        result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
        # If it returns, params should be None or empty
        assert result is None or result == {}
    except ResourceNotFoundError:
        # This is also acceptable - config exists but has no usable params
        pass


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_with_special_chars_in_params(mock_repo_class, mock_redis_set, mock_redis_get, mock_db_session):
    """Test get_assignment_config: Handles params with special characters (JSON safety)."""
    special_params = {
        "strategy": "round_robin",
        "description": "Cấu hình có ký tự đặc biệt: <script>alert('xss')</script>",
        "unicode": "日本語テスト",
        "symbols": "!@#$%^&*()[]{}|\\:\";<>?,./~`"
    }
    config_with_special = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params=special_params)
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = config_with_special
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert result == special_params
    # Verify JSON serialization worked correctly
    mock_redis_set.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_update_degree_level_no_changes(mock_repo_class, mock_db_session, degree_level_model):
    """Test update_degree_level: Handles empty update (no changes)."""
    update_schema = schemas.ConfigDegreeLevelUpdate()  # Empty update
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.update.return_value = degree_level_model
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.update_degree_level(mock_db_session, 1, update_schema)
    
    await post_commit()
    
    # Should succeed even with no changes
    assert result == degree_level_model


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_create_degree_level_with_max_display_order(mock_repo_class, mock_db_session):
    """Test create_degree_level: Handles large display_order value (edge case)."""
    create_schema = schemas.ConfigDegreeLevelCreate(
        code="test", name="Test Level", display_order=999999, is_active=True
    )
    new_level = ConfigDegreeLevel(id=1, code="test", name="Test Level", display_order=999999, is_active=True)
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = False
    mock_repo.create.return_value = new_level
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.create_degree_level(mock_db_session, create_schema)
    
    await post_commit()
    
    assert result.display_order == 999999


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock, return_value=1)
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_update_assignment_config_with_large_params(mock_repo_class, mock_org_repo_class, mock_redis_delete, mock_db_session):
    """Test update_assignment_config: Handles large params object (performance edge case)."""
    # Create large params with many keys
    large_params = {f"key_{i}": f"value_{i}" for i in range(100)}
    large_params["nested"] = {f"nested_key_{j}": [1, 2, 3, 4, 5] for j in range(10)}
    
    new_config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params=large_params)
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id_for_update.return_value = None
    mock_repo.create.return_value = new_config
    mock_repo_class.return_value = mock_repo
    
    mock_org_repo = AsyncMock()
    mock_org_repo.get_by_id.return_value = UNIT_MODEL
    mock_org_repo_class.return_value = mock_org_repo
    
    result, post_commit = await config_service.update_assignment_config(mock_db_session, UNIT_ID, large_params)
    
    await post_commit()
    
    mock_repo.create.assert_awaited_once()


# =============================================================================
# DISTRIBUTION RULES TESTS
# =============================================================================

from app.models import OfferingDistributionConfig, ProgramOffering, MajorProgram


@pytest.fixture
def distribution_rule_model():
    """Sample OfferingDistributionConfig model with relationships."""
    rule = MagicMock(spec=OfferingDistributionConfig)
    rule.id = 1
    rule.offering_id = 10
    rule.unit_id = 20
    rule.priority = 1
    rule.percentage = 50.0
    rule.is_active = True
    
    # Mock relationships
    rule.offering = MagicMock(spec=ProgramOffering)
    rule.offering.id = 10
    rule.offering.offering_type = "Chính quy"
    rule.offering.program = MagicMock(spec=MajorProgram)
    rule.offering.program.name = "Công nghệ thông tin"
    
    rule.unit = MagicMock(spec=OrganizationUnit)
    rule.unit.id = 20
    rule.unit.name = "Phòng Tuyển sinh"
    
    return rule


@pytest.mark.asyncio
async def test_get_distribution_rules_by_units_empty_list(mock_db_session):
    """Test get_distribution_rules_by_units: Returns empty list when unit_ids is empty (IDOR protection)."""
    result = await config_service.get_distribution_rules_by_units(mock_db_session, [])
    
    assert result == []
    mock_db_session.execute.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_get_distribution_rules_by_units_filters_correctly(mock_repo_class, mock_db_session, distribution_rule_model):
    """Test get_distribution_rules_by_units: Only returns rules for specified units via Repo."""
    mock_repo = AsyncMock()
    mock_repo.get_by_units_with_relations.return_value = [distribution_rule_model]
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_distribution_rules_by_units(mock_db_session, [20, 30])
    
    mock_repo.get_by_units_with_relations.assert_awaited_once_with([20, 30])
    assert len(result) == 1


@pytest.mark.asyncio
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.DistributionRuleRepository")
async def test_create_distribution_rule_invalid_offering(mock_repo_class, mock_org_repo_class, mock_db_session):
    """Test create_distribution_rule: Raises BadRequest when offering doesn't exist."""
    create_schema = schemas.DistributionRuleCreate(
        offering_id=999, unit_id=20, priority=1, percentage=50.0, is_active=True
    )
    mock_org_repo = AsyncMock()
    mock_org_repo.get_offering_by_id_full.return_value = None
    mock_org_repo_class.return_value = mock_org_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.create_distribution_rule(mock_db_session, create_schema)
    
    assert "offering" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.DistributionRuleRepository")
async def test_create_distribution_rule_invalid_unit(mock_repo_class, mock_org_repo_class, mock_db_session):
    """Test create_distribution_rule: Raises BadRequest when unit doesn't exist."""
    create_schema = schemas.DistributionRuleCreate(
        offering_id=10, unit_id=999, priority=1, percentage=50.0, is_active=True
    )
    
    mock_offering = MagicMock(spec=ProgramOffering)
    mock_org_repo = AsyncMock()
    mock_org_repo.get_offering_by_id_full.return_value = mock_offering
    mock_org_repo.get_by_id.return_value = None  # Unit not found
    mock_org_repo_class.return_value = mock_org_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.create_distribution_rule(mock_db_session, create_schema)
    
    assert "unit" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.DistributionRuleRepository")
async def test_create_distribution_rule_duplicate(mock_repo_class, mock_org_repo_class, mock_db_session):
    """Test create_distribution_rule: Raises BadRequest when rule already exists."""
    create_schema = schemas.DistributionRuleCreate(
        offering_id=10, unit_id=20, priority=1, percentage=50.0, is_active=True
    )
    
    mock_org_repo = AsyncMock()
    mock_org_repo.get_offering_by_id_full.return_value = MagicMock()
    mock_org_repo.get_by_id.return_value = MagicMock()
    mock_org_repo_class.return_value = mock_org_repo
    
    mock_repo = AsyncMock()
    mock_repo.check_duplicate.return_value = True  # Duplicate
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.create_distribution_rule(mock_db_session, create_schema)
    
    assert "already exists" in exc_info.value.detail.lower()


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_delete_distribution_rule_active_blocked(mock_repo_class, mock_db_session, distribution_rule_model):
    """Test delete_distribution_rule: Raises BadRequest when trying to delete active rule."""
    distribution_rule_model.is_active = True
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = distribution_rule_model
    mock_repo_class.return_value = mock_repo
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.delete_distribution_rule(mock_db_session, 1)
    
    assert "active" in exc_info.value.detail.lower()
    mock_db_session.delete.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_delete_distribution_rule_inactive_success(mock_repo_class, mock_db_session, distribution_rule_model):
    """Test delete_distribution_rule: Successfully deletes inactive rule."""
    distribution_rule_model.is_active = False
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = distribution_rule_model
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_distribution_rule(mock_db_session, 1)
    
    await post_commit()
    
    mock_db_session.delete.assert_awaited_once_with(distribution_rule_model)


# =============================================================================
# INPUT VALIDATION EDGE CASES
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_create_degree_level_with_unicode_code(mock_repo_class, mock_db_session):
    """Test create_degree_level: Handles unicode characters in code."""
    create_schema = schemas.ConfigDegreeLevelCreate(
        code="đại_học", name="Đại học", display_order=1, is_active=True
    )
    new_level = ConfigDegreeLevel(id=1, code="đại_học", name="Đại học", display_order=1, is_active=True)
    
    mock_repo = AsyncMock()
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = False
    mock_repo.create.return_value = new_level
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.create_degree_level(mock_db_session, create_schema)
    
    await post_commit()
    
    assert result.code == "đại_học"


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_update_degree_level_same_code_no_duplicate_error(mock_repo_class, mock_db_session, degree_level_model):
    """Test update_degree_level: Doesn't raise duplicate error when code unchanged."""
    update_schema = schemas.ConfigDegreeLevelUpdate(code="dai_hoc")  # Same as existing
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.update.return_value = degree_level_model
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.update_degree_level(mock_db_session, 1, update_schema)
    
    await post_commit()
    
    # Should not call check_code_exists since code is unchanged
    mock_repo.check_code_exists.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock, return_value=None)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_with_nested_json_params(mock_repo_class, mock_redis_set, mock_redis_get, mock_db_session):
    """Test get_assignment_config: Handles deeply nested JSON params."""
    nested_params = {
        "level1": {
            "level2": {
                "level3": {
                    "level4": {
                        "value": "deep"
                    }
                }
            }
        },
        "array": [{"item": 1}, {"item": 2}, {"item": 3}]
    }
    config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params=nested_params)
    
    mock_repo = AsyncMock()
    mock_repo.get_by_unit_id.return_value = config
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    
    assert result["level1"]["level2"]["level3"]["level4"]["value"] == "deep"
    assert len(result["array"]) == 3


# =============================================================================
# SOFT DELETE / REACTIVATION EDGE CASES
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_delete_offering_type_hard_delete_success(mock_repo_class, mock_db_session, offering_type_model):
    """Test delete_offering_type: Hard delete (removes record completely)."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = offering_type_model
    mock_repo.is_used_by_offerings.return_value = False  # Not in use
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_offering_type(mock_db_session, 1, soft_delete=False)
    
    await post_commit()
    
    mock_repo.delete.assert_awaited_once_with(offering_type_model)
    mock_repo.soft_delete.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_get_degree_levels_returns_ordered_by_display_order(mock_repo_class, mock_db_session):
    """Test get_degree_levels: Returns levels ordered by display_order."""
    level1 = ConfigDegreeLevel(id=1, code="cao_dang", name="Cao đẳng", display_order=0, is_active=True)
    level2 = ConfigDegreeLevel(id=2, code="dai_hoc", name="Đại học", display_order=1, is_active=True)
    level3 = ConfigDegreeLevel(id=3, code="thac_si", name="Thạc sĩ", display_order=2, is_active=True)
    
    mock_repo = AsyncMock()
    mock_repo.get_all_active.return_value = [level1, level2, level3]
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_degree_levels(mock_db_session)
    
    assert len(result) == 3
    assert result[0].display_order == 0
    assert result[1].display_order == 1
    assert result[2].display_order == 2


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_update_offering_type_cascades_name_change(mock_repo_class, mock_db_session):
    """Test update_offering_type: Cascades name change to ProgramOffering."""
    from app.models import ConfigOfferingType, ProgramOffering
    db_type = ConfigOfferingType(id=1, code="old_code", name="Old Name")
    
    update_schema = schemas.ConfigOfferingTypeUpdate(name="New Name")
    
    # Mock ProgramOffering model
    mock_offering = MagicMock(spec=ProgramOffering)
    mock_offering.offering_type = "Old Name"
    # Ensure program relationship is mocked too
    mock_offering.program = MagicMock()
    mock_offering.program.name = "Test Program"
    
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = db_type
    mock_repo.check_code_exists.return_value = False
    mock_repo.check_name_exists.return_value = False
    mock_repo.get_offerings_by_type_name.return_value = [mock_offering]
    mock_repo.update.return_value = db_type
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.update_offering_type(mock_db_session, 1, update_schema)
    
    await post_commit()
    
    # Verify cascade update happened in service
    assert mock_offering.offering_type == "New Name"
    mock_repo.get_offerings_by_type_name.assert_awaited_once_with("Old Name")


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_get_distribution_rules_by_units_idor_protection(mock_repo_class, mock_db_session):
    """Test get_distribution_rules_by_units: Correctly returns results for authorized units only."""
    allowed_units = [20]
    
    mock_repo = AsyncMock()
    mock_repo.get_by_units_with_relations.return_value = []
    mock_repo_class.return_value = mock_repo
    
    result = await config_service.get_distribution_rules_by_units(mock_db_session, allowed_units)
    
    mock_repo.get_by_units_with_relations.assert_awaited_once_with(allowed_units)
    assert result == []


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_delete_degree_level_hard_delete_logic(mock_repo_class, mock_db_session, degree_level_model):
    """Test delete_degree_level: Hard delete calls repo.delete() correctly."""
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = degree_level_model
    mock_repo.is_used_by_programs.return_value = False
    mock_repo_class.return_value = mock_repo
    
    result, post_commit = await config_service.delete_degree_level(mock_db_session, 1, soft_delete=False)
    
    await post_commit()
    
    mock_repo.delete.assert_awaited_once_with(degree_level_model)
    mock_repo.soft_delete.assert_not_awaited()


# =============================================================================
# FORENSIC AUDIT & SECURITY TESTS (IDOR, Validation, Edge Cases)
# =============================================================================


@pytest.mark.asyncio
@patch("app.services.config_service.OrganizationRepository")
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_update_assignment_config_invalid_params_type(mock_repo_class, mock_org_repo_class, mock_db_session):
    """Test update_assignment_config: Raises BadRequest if params is not a dict."""
    mock_org_repo = AsyncMock()
    mock_org_repo.get_by_id.return_value = MagicMock()
    mock_org_repo_class.return_value = mock_org_repo
    
    # Try with a string instead of a dict
    invalid_params = "not a dict"
    
    with pytest.raises(BadRequest) as exc_info:
        await config_service.update_assignment_config(mock_db_session, UNIT_ID, invalid_params)
    
    assert "must be a JSON object" in str(exc_info.value.detail)


@pytest.mark.asyncio
@patch("app.services.config_service.DistributionRuleRepository")
async def test_get_distribution_rules_by_units_security_filtering(mock_repo_class, mock_db_session):
    """
    Test get_distribution_rules_by_units: 
    Verifies that rules are filtered strictly by allowed unit_ids (IDOR protection).
    """
    # Rules for unit 1 and 2
    rule1 = OfferingDistributionConfig(id=1, offering_id=1, unit_id=1, weight=1, priority=1, is_active=True)
    
    # Relationships for _build_distribution_rule_response
    rule1.offering = MagicMock()
    rule1.offering.offering_type = "Full-time"
    rule1.offering.program = MagicMock()
    rule1.offering.program.name = "Program 1"
    rule1.unit = MagicMock()
    rule1.unit.name = "Unit 1"

    mock_repo = AsyncMock()
    # Mock return value to filter by unit_ids [1]
    mock_repo.get_by_units_with_relations.return_value = [rule1]
    mock_repo_class.return_value = mock_repo
    
    # Manager of Unit 1
    allowed_units = [1]
    result = await config_service.get_distribution_rules_by_units(mock_db_session, allowed_units)
    
    assert len(result) == 1
    assert result[0].unit_id == 1
    mock_repo.get_by_units_with_relations.assert_awaited_once_with([1])


@pytest.mark.asyncio
@patch("app.services.config_service.OfferingTypeRepository")
async def test_update_offering_type_cascade_integrity(mock_repo_class, mock_db_session, offering_type_model):
    """
    Test update_offering_type: 
    Ensures that name change cascades to ProgramOfferings and is handled in a transaction.
    """
    mock_repo = AsyncMock()
    offering_type_model.name = "Old Name"
    mock_repo.get_by_id.return_value = offering_type_model
    mock_repo.check_name_exists.return_value = False
    mock_repo.check_code_exists.return_value = False
    
    # Mock dependent offerings
    mock_offering = MagicMock()
    mock_offering.offering_type = "Old Name"
    mock_repo.get_offerings_by_type_name.return_value = [mock_offering]
    
    update_schema = schemas.ConfigOfferingTypeUpdate(name="New Name")
    mock_repo.update.return_value = offering_type_model
    mock_repo_class.return_value = mock_repo
    
    await config_service.update_offering_type(mock_db_session, 1, update_schema)
    
    # Verify cascade update
    assert mock_offering.offering_type == "New Name"
    mock_repo.get_offerings_by_type_name.assert_awaited_once_with("Old Name")


@pytest.mark.asyncio
@patch("app.services.config_service.DegreeLevelRepository")
async def test_update_degree_level_cascade_integrity(mock_repo_class, mock_db_session):
    """Test forensic polish: Ensure degree level update cascades to Program."""
    mock_repo = AsyncMock()
    level_model = models.ConfigDegreeLevel(id=1, code="DL1", name="Old Degree")
    mock_repo.get_by_id.return_value = level_model
    mock_repo.check_name_exists.return_value = False
    mock_repo.check_code_exists.return_value = False
    
    # Mock dependent programs
    mock_program = MagicMock()
    mock_program.degree_level = "Old Degree"
    mock_repo.get_programs_by_degree_name.return_value = [mock_program]
    
    update_schema = schemas.ConfigDegreeLevelUpdate(name="New Degree")
    mock_repo.update.return_value = level_model
    mock_repo_class.return_value = mock_repo
    
    await config_service.update_degree_level(mock_db_session, 1, update_schema)
    
    # Verify cascade update
    assert mock_program.degree_level == "New Degree"
    mock_repo.get_programs_by_degree_name.assert_awaited_once_with("Old Degree")


@pytest.mark.asyncio
async def test_update_assignment_config_validation_robustness(mock_db_session):
    """Test forensic polish: Ensure assignment config rejects negative values."""
    invalid_params = {"max_leads": -5, "weight": 1.5}
    
    # We need to mock OrganizationRepository too because it's checked before validation
    with patch("app.services.config_service.OrganizationRepository") as mock_org_repo_class:
        mock_org_repo = AsyncMock()
        mock_org_repo.get_by_id.return_value = MagicMock() # Unit exists
        mock_org_repo_class.return_value = mock_org_repo
        
        with pytest.raises(BadRequest) as exc:
            await config_service.update_assignment_config(mock_db_session, 1, invalid_params)
        assert "cannot be negative" in str(exc.value)


@pytest.mark.asyncio
@patch("app.services.config_service.AssignmentConfigRepository")
async def test_get_assignment_config_not_found_security(mock_config_repo_class, mock_db_session):
    """Test security: Ensure non-existent units throw correct error."""
    mock_config_repo = AsyncMock()
    mock_config_repo.get_by_unit_id.return_value = None
    mock_config_repo_class.return_value = mock_config_repo
    
    with pytest.raises(ResourceNotFoundError):
        await config_service.get_assignment_config(mock_db_session, 999)


@pytest.mark.asyncio
@patch("app.services.config_service.DocumentTypeRepository")
async def test_update_document_type_no_offering_cascade(mock_repo_class, mock_db_session):
    """``update_document_type`` đổi code KHÔNG cascade ``ProgramOffering.
    admission_rules`` — cascade cũ ĐÃ BỎ chủ đích (config_service:871; documents
    giờ qua relational DocumentGroup). Guard giữ removal: nếu ai đó tái thêm
    cascade (fetch offerings để rewrite mandatory_docs) → test này đỏ.
    """
    mock_repo = AsyncMock()
    doc_model = models.ConfigDocumentType(id=1, code="old_doc", name="Old Doc")
    mock_repo.get_by_id.return_value = doc_model
    mock_repo.check_name_exists.return_value = False
    mock_repo.check_code_exists.return_value = False

    update_schema = schemas.ConfigDocumentTypeUpdate(code="new_doc")
    updated_doc_model = models.ConfigDocumentType(id=1, code="new_doc", name="Old Doc")
    mock_repo.update.return_value = updated_doc_model
    mock_repo_class.return_value = mock_repo

    result, _callback = await config_service.update_document_type(
        mock_db_session, 1, update_schema
    )

    # Doc type code được cập nhật.
    assert result.code == "new_doc"
    # KHÔNG fetch offerings để cascade (cascade đã bỏ).
    mock_repo.get_all_offerings_with_admission_rules.assert_not_awaited()
