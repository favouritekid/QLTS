# tests/services/test_config_service.py
# -*- coding: utf-8 -*-
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio
import redis.asyncio as redis
from sqlalchemy.exc import SQLAlchemyError  # Cần để mock lỗi DB
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.config import settings
from app.models import OfficerAssignmentConfig, OrganizationUnit, SkillRequirementRule

# Import các thành phần cần test
from app.services import config_service
from app.utils.exceptions import ResourceNotFoundError

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
    session.scalar = AsyncMock()
    session.rollback = AsyncMock()
    # Config mặc định cho execute
    mock_execute_result = MagicMock()
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = []
    mock_execute_result.scalars.return_value = mock_scalars_result
    session.execute.return_value = mock_execute_result
    # Config mặc định cho scalar
    session.scalar.return_value = None
    # Config mặc định cho get
    session.get.return_value = None
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
@patch(
    "app.services.config_service.safe_redis_get",
    new_callable=AsyncMock,
    return_value=None,
)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
@patch(
    "app.services.config_service.log.debug", new_callable=AsyncMock
)  # Mock logger debug
async def test_get_assignment_config_cache_miss(
    mock_log_debug, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Cache miss, đọc DB, ghi cache."""
    mock_db_session.scalar.return_value = ASSIGNMENT_CONFIG_MODEL
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    assert result == ASSIGNMENT_PARAMS
    mock_redis_get.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    mock_db_session.scalar.assert_awaited_once()
    mock_redis_set.assert_awaited_once_with(
        ASSIGNMENT_CACHE_KEY, json.dumps(ASSIGNMENT_PARAMS), ex=CACHE_TTL
    )
    assert mock_log_debug.await_count >= 3


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_get", new_callable=AsyncMock)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
@patch("app.services.config_service.log.debug", new_callable=AsyncMock)
async def test_get_assignment_config_cache_hit(
    mock_log_debug, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Cache hit."""
    cached_data = {"strategy": "cached", "value": 99}
    mock_redis_get.return_value = json.dumps(cached_data)
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    assert result == cached_data
    mock_redis_get.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    mock_db_session.scalar.assert_not_awaited()
    mock_redis_set.assert_not_awaited()
    mock_log_debug.assert_any_await("Cache hit for assignment config", unit_id=UNIT_ID)


@pytest.mark.asyncio
@patch(
    "app.services.config_service.safe_redis_get",
    new_callable=AsyncMock,
    return_value=None,
)
async def test_get_assignment_config_db_not_found(mock_redis_get, mock_db_session):
    """Test get_assignment_config: Không tìm thấy config trong DB (404)."""
    mock_db_session.scalar.return_value = None
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    assert exc_info.value.detail == f"Assignment config for unit {UNIT_ID} not found."
    mock_redis_get.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    mock_db_session.scalar.assert_awaited_once()


@pytest.mark.asyncio
@patch(
    "app.services.config_service.safe_redis_get",
    new_callable=AsyncMock,
    side_effect=redis.RedisError("Get failed"),
)
@patch("app.services.config_service.safe_redis_set", new_callable=AsyncMock)
@patch(
    "app.services.config_service.log.error", new_callable=AsyncMock
)  # Mock logger error
async def test_get_assignment_config_redis_get_error(
    mock_log_error, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Lỗi Redis GET, đọc từ DB (fail-open)."""
    mock_db_session.scalar.return_value = ASSIGNMENT_CONFIG_MODEL
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    assert result == ASSIGNMENT_PARAMS
    mock_redis_get.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    mock_db_session.scalar.assert_awaited_once()
    mock_redis_set.assert_awaited_once_with(
        ASSIGNMENT_CACHE_KEY, json.dumps(ASSIGNMENT_PARAMS), ex=CACHE_TTL
    )
    mock_log_error.assert_awaited_once()


@pytest.mark.asyncio
@patch(
    "app.services.config_service.safe_redis_get",
    new_callable=AsyncMock,
    return_value=None,
)
@patch(
    "app.services.config_service.safe_redis_set",
    new_callable=AsyncMock,
    side_effect=redis.RedisError("Set failed"),
)
@patch(
    "app.services.config_service.log.error", new_callable=AsyncMock
)  # Mock logger error
async def test_get_assignment_config_redis_set_error(
    mock_log_error, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_assignment_config: Lỗi Redis SET, vẫn trả về data DB."""
    mock_db_session.scalar.return_value = ASSIGNMENT_CONFIG_MODEL
    result = await config_service.get_assignment_config(mock_db_session, UNIT_ID)
    assert result == ASSIGNMENT_PARAMS
    mock_redis_get.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    mock_db_session.scalar.assert_awaited_once()
    mock_redis_set.assert_awaited_once_with(
        ASSIGNMENT_CACHE_KEY, json.dumps(ASSIGNMENT_PARAMS), ex=CACHE_TTL
    )
    mock_log_error.assert_awaited_once()


# === Tests cho update_assignment_config ===


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock)
@patch(
    "app.services.config_service.log.info", new_callable=AsyncMock
)  # Mock logger info
async def test_update_config_create_success(
    mock_log_info, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: Tạo mới thành công."""
    new_params = {"strategy": "new", "limit": 10}
    mock_db_session.scalar.return_value = None  # Config chưa có
    mock_db_session.get.return_value = UNIT_MODEL  # Unit có
    # --- FIX: Set return_value for safe_redis_delete ---
    mock_redis_delete.return_value = 1  # Giả lập xóa thành công 1 key

    result_model = await config_service.update_assignment_config(
        mock_db_session, UNIT_ID, new_params
    )
    mock_db_session.scalar.assert_awaited_once()
    mock_db_session.get.assert_awaited_once_with(OrganizationUnit, UNIT_ID)
    mock_db_session.add.assert_called_once()
    added_arg = mock_db_session.add.call_args[0][0]
    assert isinstance(added_arg, OfficerAssignmentConfig)
    assert added_arg.unit_id == UNIT_ID
    assert added_arg.params == new_params
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(
        added_arg, attribute_names=["params"]
    )
    mock_redis_delete.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    assert result_model == added_arg
    mock_log_info.assert_any_await("Creating new assignment config", unit_id=UNIT_ID)
    # --- Assert log message invalidate cache ---
    mock_log_info.assert_any_await(
        "Invalidated assignment config cache", unit_id=UNIT_ID
    )


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock)
@patch("app.services.config_service.log.info", new_callable=AsyncMock)
async def test_update_config_update_success(
    mock_log_info, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: Cập nhật thành công."""
    updated_params = {"strategy": "updated", "value": 5}
    existing_config = OfficerAssignmentConfig(id=1, unit_id=UNIT_ID, params={"old": 1})
    mock_db_session.scalar.return_value = existing_config  # Config cũ
    # --- FIX: Set return_value for safe_redis_delete ---
    mock_redis_delete.return_value = 1  # Giả lập xóa thành công 1 key

    result_model = await config_service.update_assignment_config(
        mock_db_session, UNIT_ID, updated_params
    )
    mock_db_session.scalar.assert_awaited_once()
    mock_db_session.get.assert_not_awaited()
    mock_db_session.add.assert_called_once_with(existing_config)
    assert existing_config.params == updated_params
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(
        existing_config, attribute_names=["params"]
    )
    mock_redis_delete.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    assert result_model == existing_config
    mock_log_info.assert_any_await(
        "Updating existing assignment config", unit_id=UNIT_ID
    )
    # --- Assert log message invalidate cache ---
    mock_log_info.assert_any_await(
        "Invalidated assignment config cache", unit_id=UNIT_ID
    )


@pytest.mark.asyncio
@patch(
    "app.services.config_service.log.error", new_callable=AsyncMock
)  # Mock logger error
async def test_update_config_unit_not_found(mock_log_error, mock_db_session):
    """Test update_assignment_config: Unit ID không tồn tại (404)."""
    mock_db_session.scalar.return_value = None  # Config chưa có
    mock_db_session.get.return_value = None  # Unit cũng không có
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.update_assignment_config(
            mock_db_session, UNIT_ID, {"a": 1}
        )
    assert exc_info.value.detail == f"Organization Unit with id {UNIT_ID} not found."
    mock_db_session.rollback.assert_awaited_once()
    mock_log_error.assert_awaited_once()  # Kiểm tra log lỗi


@pytest.mark.asyncio
@patch("app.services.config_service.safe_redis_delete", new_callable=AsyncMock)
@patch("app.services.config_service.log.error", new_callable=AsyncMock)
async def test_update_config_db_commit_error(
    mock_log_error, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: Lỗi khi commit DB."""
    mock_db_session.scalar.return_value = None
    mock_db_session.get.return_value = UNIT_MODEL
    mock_db_session.commit.side_effect = SQLAlchemyError("Commit failed")
    with pytest.raises(SQLAlchemyError):  # Mong đợi lỗi gốc được raise lại
        await config_service.update_assignment_config(
            mock_db_session, UNIT_ID, {"a": 1}
        )
    mock_db_session.rollback.assert_awaited_once()
    mock_redis_delete.assert_not_awaited()  # Không xóa cache nếu commit lỗi
    mock_log_error.assert_awaited_once()


@pytest.mark.asyncio
@patch(
    "app.services.config_service.safe_redis_delete",
    new_callable=AsyncMock,
    side_effect=redis.RedisError("Delete failed"),
)
@patch(
    "app.services.config_service.log.error", new_callable=AsyncMock
)  # Mock logger error
async def test_update_config_redis_delete_error(
    mock_log_error, mock_redis_delete, mock_db_session
):
    """Test update_assignment_config: DB thành công, lỗi khi xóa cache."""
    mock_db_session.scalar.return_value = None
    mock_db_session.get.return_value = UNIT_MODEL
    result_model = await config_service.update_assignment_config(
        mock_db_session, UNIT_ID, {"a": 1}
    )
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once()
    mock_redis_delete.assert_awaited_once_with(ASSIGNMENT_CACHE_KEY)
    assert result_model is not None
    assert mock_log_error.await_count >= 1  # Kiểm tra log lỗi redis delete


# === Tests cho Skill Rules ===


@pytest.mark.asyncio
async def test_get_all_skill_rules_success(mock_db_session):
    """Test get_all_skill_rules: Trả về danh sách rule."""
    mock_rules = [
        SKILL_RULE_MODEL_1,
        SkillRequirementRule(
            id=2, lead_attribute="loc", attribute_value="hcm", required_skill="SalesHCM"
        ),
    ]
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = (
        mock_rules
    )
    result = await config_service.get_all_skill_rules(mock_db_session)
    mock_db_session.execute.assert_awaited_once()
    assert result == mock_rules


@pytest.mark.asyncio
async def test_create_skill_rule_success(mock_db_session):
    """Test create_skill_rule: Tạo thành công."""
    result_rule = await config_service.create_skill_rule(
        mock_db_session, SKILL_RULE_CREATE_SCHEMA
    )
    mock_db_session.add.assert_called_once()
    added_arg = mock_db_session.add.call_args[0][0]
    assert isinstance(added_arg, SkillRequirementRule)
    assert added_arg.lead_attribute == SKILL_RULE_CREATE_SCHEMA.lead_attribute
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_arg)
    assert result_rule == added_arg


@pytest.mark.asyncio
async def test_delete_skill_rule_success(mock_db_session):
    """Test delete_skill_rule: Xóa thành công."""
    rule_id_to_delete = SKILL_RULE_MODEL_1.id
    mock_db_session.get.return_value = SKILL_RULE_MODEL_1  # Tìm thấy rule
    await config_service.delete_skill_rule(mock_db_session, rule_id_to_delete)
    mock_db_session.get.assert_awaited_once_with(
        SkillRequirementRule, rule_id_to_delete
    )
    mock_db_session.delete.assert_awaited_once_with(SKILL_RULE_MODEL_1)
    mock_db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_skill_rule_not_found(mock_db_session):
    """Test delete_skill_rule: Rule không tồn tại (404)."""
    rule_id_to_delete = 999
    mock_db_session.get.return_value = None  # Không tìm thấy rule
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await config_service.delete_skill_rule(mock_db_session, rule_id_to_delete)
    assert exc_info.value.detail == f"Skill rule with id {rule_id_to_delete} not found."
    mock_db_session.delete.assert_not_awaited()
    mock_db_session.commit.assert_not_awaited()
