# tests/services/test_pipeline_service.py
# -*- coding: utf-8 -*-
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio
import redis.asyncio as redis  # Cần để mock lỗi
from sqlalchemy import func, select  # Import func và select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas  # Cần schemas cho CRUD tests
from app.config import settings
from app.models import ConsultationStatus  # Thêm Lead để test ràng buộc
from app.models import Lead, PipelineStage

# Import các thành phần cần test
from app.services import pipeline_service
from app.utils.exceptions import DuplicateResourceError, ResourceNotFoundError

# Import constants
try:
    from tests.fixtures.constants import TestPipelineData
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

# Cache keys và TTL từ service/settings
STAGES_KEY = pipeline_service.PIPELINE_STAGES_CACHE_KEY
STATUSES_KEY = pipeline_service.PIPELINE_STATUSES_CACHE_KEY
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
    session.scalar = AsyncMock()  # Thêm mock cho scalar
    # Config mặc định cho execute
    mock_execute_result = MagicMock()
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = []
    mock_scalars_result.first.return_value = None  # Thêm first()
    mock_scalars_result.one_or_none.return_value = None  # Thêm one_or_none()
    mock_execute_result.scalars.return_value = mock_scalars_result
    session.execute.return_value = mock_execute_result
    # Config mặc định cho scalar
    session.scalar.return_value = None
    # Config mặc định cho get
    session.get.return_value = None
    return session


# === Dữ liệu mẫu (dùng constants) ===
STAGE_A_MODEL = PipelineStage(**TestPipelineData.STAGE_A)
STAGE_B_MODEL = PipelineStage(**TestPipelineData.STAGE_B)
STATUS_A1_MODEL = ConsultationStatus(**TestPipelineData.STATUS_A1)
STATUS_B1_MODEL = ConsultationStatus(**TestPipelineData.STATUS_B1)

STAGE_LIST_MODELS = [STAGE_A_MODEL, STAGE_B_MODEL]
# Service sắp xếp stages theo order
STAGE_LIST_DICTS_SORTED = sorted(
    [TestPipelineData.STAGE_A, TestPipelineData.STAGE_B], key=lambda x: x["order"]
)
STATUS_LIST_MODELS = [STATUS_A1_MODEL, STATUS_B1_MODEL]
# Service không sắp xếp statuses, giữ nguyên thứ tự hoặc sắp xếp theo ID để dễ test
STATUS_LIST_DICTS_UNSORTED = [TestPipelineData.STATUS_A1, TestPipelineData.STATUS_B1]
STATUS_LIST_DICTS_SORTED_BY_ID = sorted(
    STATUS_LIST_DICTS_UNSORTED, key=lambda x: x["id"]
)


# === Tests cho get_all_pipeline_stages ===


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.safe_redis_get",
    new_callable=AsyncMock,
    return_value=None,
)
@patch("app.services.pipeline_service.safe_redis_set", new_callable=AsyncMock)
async def test_get_stages_cache_miss(mock_redis_set, mock_redis_get, mock_db_session):
    """Test get_all_pipeline_stages: Cache miss, đọc từ DB, ghi vào cache."""
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = (
        STAGE_LIST_MODELS
    )
    result = await pipeline_service.get_all_pipeline_stages(mock_db_session)
    assert result == STAGE_LIST_DICTS_SORTED
    mock_redis_get.assert_awaited_once_with(STAGES_KEY)
    mock_db_session.execute.assert_awaited_once()
    mock_redis_set.assert_awaited_once_with(
        STAGES_KEY, json.dumps(STAGE_LIST_DICTS_SORTED), ex=CACHE_TTL
    )


@pytest.mark.asyncio
@patch("app.services.pipeline_service.safe_redis_get", new_callable=AsyncMock)
@patch("app.services.pipeline_service.safe_redis_set", new_callable=AsyncMock)
async def test_get_stages_cache_hit(mock_redis_set, mock_redis_get, mock_db_session):
    """Test get_all_pipeline_stages: Cache hit, trả về từ cache, không gọi DB/set."""
    cached_data = [{"id": "CACHED_S", "name": "Cached Stage", "order": 1}]
    mock_redis_get.return_value = json.dumps(cached_data)
    result = await pipeline_service.get_all_pipeline_stages(mock_db_session)
    assert result == cached_data
    mock_redis_get.assert_awaited_once_with(STAGES_KEY)
    mock_db_session.execute.assert_not_awaited()
    mock_redis_set.assert_not_awaited()


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.safe_redis_get",
    new_callable=AsyncMock,
    side_effect=redis.RedisError("Get failed"),
)
@patch("app.services.pipeline_service.safe_redis_set", new_callable=AsyncMock)
@patch("app.services.pipeline_service.log.error", new_callable=AsyncMock)  # Mock logger
async def test_get_stages_redis_get_error(
    mock_log_error, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_all_pipeline_stages: Lỗi khi đọc cache -> đọc từ DB, ghi cache."""
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = (
        STAGE_LIST_MODELS
    )
    result = await pipeline_service.get_all_pipeline_stages(mock_db_session)
    assert result == STAGE_LIST_DICTS_SORTED
    mock_redis_get.assert_awaited_once_with(STAGES_KEY)
    mock_db_session.execute.assert_awaited_once()
    mock_redis_set.assert_awaited_once_with(
        STAGES_KEY, json.dumps(STAGE_LIST_DICTS_SORTED), ex=CACHE_TTL
    )
    mock_log_error.assert_awaited_once()  # Kiểm tra log lỗi redis get


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.safe_redis_get",
    new_callable=AsyncMock,
    return_value=None,
)
@patch(
    "app.services.pipeline_service.safe_redis_set",
    new_callable=AsyncMock,
    side_effect=redis.RedisError("Set failed"),
)
@patch("app.services.pipeline_service.log.error", new_callable=AsyncMock)  # Mock logger
async def test_get_stages_redis_set_error(
    mock_log_error, mock_redis_set, mock_redis_get, mock_db_session
):
    """Test get_all_pipeline_stages: Cache miss, đọc DB ok, lỗi khi ghi cache."""
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = (
        STAGE_LIST_MODELS
    )
    result = await pipeline_service.get_all_pipeline_stages(mock_db_session)
    assert result == STAGE_LIST_DICTS_SORTED  # Vẫn trả về data từ DB
    mock_redis_get.assert_awaited_once_with(STAGES_KEY)
    mock_db_session.execute.assert_awaited_once()
    mock_redis_set.assert_awaited_once_with(
        STAGES_KEY, json.dumps(STAGE_LIST_DICTS_SORTED), ex=CACHE_TTL
    )
    mock_log_error.assert_awaited_once()  # Kiểm tra log lỗi redis set


# === Tests cho get_all_consultation_statuses ===


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.safe_redis_get",
    new_callable=AsyncMock,
    return_value=None,
)
@patch("app.services.pipeline_service.safe_redis_set", new_callable=AsyncMock)
async def test_get_statuses_cache_miss(mock_redis_set, mock_redis_get, mock_db_session):
    """Test get_all_consultation_statuses: Cache miss."""
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = (
        STATUS_LIST_MODELS
    )
    result = await pipeline_service.get_all_consultation_statuses(mock_db_session)
    result_sorted = sorted(result, key=lambda x: x["id"])
    assert result_sorted == STATUS_LIST_DICTS_SORTED_BY_ID
    mock_redis_get.assert_awaited_once_with(STATUSES_KEY)
    mock_db_session.execute.assert_awaited_once()
    mock_redis_set.assert_awaited_once_with(
        STATUSES_KEY, json.dumps(result), ex=CACHE_TTL
    )


@pytest.mark.asyncio
@patch("app.services.pipeline_service.safe_redis_get", new_callable=AsyncMock)
@patch("app.services.pipeline_service.safe_redis_set", new_callable=AsyncMock)
async def test_get_statuses_cache_hit(mock_redis_set, mock_redis_get, mock_db_session):
    """Test get_all_consultation_statuses: Cache hit."""
    cached_data = [
        {
            "id": "CACHED_T",
            "name": "Cached Status",
            "color_code": "#ccc",
            "stage_id": "S1",
        }
    ]
    mock_redis_get.return_value = json.dumps(cached_data)
    result = await pipeline_service.get_all_consultation_statuses(mock_db_session)
    assert result == cached_data
    mock_redis_get.assert_awaited_once_with(STATUSES_KEY)
    mock_db_session.execute.assert_not_awaited()
    mock_redis_set.assert_not_awaited()


# ... (Thêm test cases get error, set error cho statuses tương tự stages) ...

# === Tests cho invalidate_pipeline_cache ===


@pytest.mark.asyncio
@patch("app.services.pipeline_service.safe_redis_delete", new_callable=AsyncMock)
async def test_invalidate_pipeline_cache_success(mock_redis_delete):
    """Test invalidate_pipeline_cache: Gọi delete cho cả 2 keys."""
    await pipeline_service.invalidate_pipeline_cache()
    mock_redis_delete.assert_has_awaits(
        [call(STAGES_KEY), call(STATUSES_KEY)], any_order=True
    )
    assert mock_redis_delete.await_count == 2


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.safe_redis_delete",
    new_callable=AsyncMock,
    side_effect=redis.RedisError("Delete failed"),
)
@patch("app.services.pipeline_service.log.error", new_callable=AsyncMock)  # Mock logger
async def test_invalidate_pipeline_cache_redis_error(mock_log_error, mock_redis_delete):
    """Test invalidate_pipeline_cache: Lỗi Redis không làm raise exception."""
    await pipeline_service.invalidate_pipeline_cache()
    assert mock_redis_delete.await_count > 0
    mock_log_error.assert_awaited_once()


# === Tests cho CRUD Stages (Service Layer) ===


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.invalidate_pipeline_cache", new_callable=AsyncMock
)
async def test_create_pipeline_stage_success(mock_invalidate, mock_db_session):
    """Test create_pipeline_stage: Tạo thành công."""
    stage_data = {"id": "NEW_S", "name": "New Stage", "order": 5}
    stage_in = schemas.PipelineStageCreate(**stage_data)
    mock_db_session.get.return_value = None
    mock_db_session.scalar.return_value = None
    created_stage = await pipeline_service.create_pipeline_stage(
        mock_db_session, stage_in
    )
    mock_db_session.get.assert_awaited_once_with(PipelineStage, stage_data["id"])
    mock_db_session.scalar.assert_awaited_once()
    mock_db_session.add.assert_called_once()
    added_arg = mock_db_session.add.call_args[0][0]
    assert isinstance(added_arg, PipelineStage)
    assert added_arg.id == stage_data["id"]
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_arg)
    mock_invalidate.assert_awaited_once()
    assert created_stage == added_arg


@pytest.mark.asyncio
async def test_create_pipeline_stage_duplicate_id(mock_db_session):
    """Test create_pipeline_stage: Lỗi trùng ID."""
    stage_data = {"id": "EXISTING_ID", "name": "New Stage", "order": 5}
    stage_in = schemas.PipelineStageCreate(**stage_data)
    mock_db_session.get.return_value = PipelineStage(**stage_data)
    with pytest.raises(DuplicateResourceError) as exc_info:
        await pipeline_service.create_pipeline_stage(mock_db_session, stage_in)
    assert (
        exc_info.value.detail
        == f"Pipeline Stage ID '{stage_data['id']}' already exists."
    )
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_pipeline_stage_duplicate_order(mock_db_session):
    """Test create_pipeline_stage: Lỗi trùng Order."""
    stage_data = {"id": "NEW_ID", "name": "New Stage", "order": 10}
    stage_in = schemas.PipelineStageCreate(**stage_data)
    mock_db_session.get.return_value = None
    mock_db_session.scalar.return_value = PipelineStage(
        id="OTHER_ID", name="Other", order=10
    )
    with pytest.raises(DuplicateResourceError) as exc_info:
        await pipeline_service.create_pipeline_stage(mock_db_session, stage_in)
    assert (
        exc_info.value.detail
        == f"Pipeline Stage order '{stage_data['order']}' already exists."
    )
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_pipeline_stage_found(mock_db_session):
    """Test get_pipeline_stage: Tìm thấy."""
    mock_db_session.get.return_value = STAGE_A_MODEL
    stage = await pipeline_service.get_pipeline_stage(mock_db_session, STAGE_A_MODEL.id)
    mock_db_session.get.assert_awaited_once_with(PipelineStage, STAGE_A_MODEL.id)
    assert stage == STAGE_A_MODEL


@pytest.mark.asyncio
async def test_get_pipeline_stage_not_found(mock_db_session):
    """Test get_pipeline_stage: Không tìm thấy."""
    mock_db_session.get.return_value = None
    stage_id = "NOT_FOUND"
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await pipeline_service.get_pipeline_stage(mock_db_session, stage_id)
    assert exc_info.value.detail == f"Pipeline Stage '{stage_id}' not found."


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.invalidate_pipeline_cache", new_callable=AsyncMock
)
async def test_update_pipeline_stage_success(mock_invalidate, mock_db_session):
    """Test update_pipeline_stage: Cập nhật thành công."""
    stage_id = STAGE_B_MODEL.id
    update_data = {"name": "Updated Stage B", "order": 25}
    update_in = schemas.PipelineStageUpdate(**update_data)
    mock_db_session.get.return_value = STAGE_B_MODEL  # Trả về stage B gốc
    mock_db_session.scalar.return_value = None
    updated_stage = await pipeline_service.update_pipeline_stage(
        mock_db_session, stage_id, update_in
    )
    mock_db_session.get.assert_awaited_once_with(PipelineStage, stage_id)
    mock_db_session.scalar.assert_awaited_once()
    assert STAGE_B_MODEL.name == update_data["name"]
    assert STAGE_B_MODEL.order == update_data["order"]
    mock_db_session.add.assert_called_once_with(STAGE_B_MODEL)
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(STAGE_B_MODEL)
    mock_invalidate.assert_awaited_once()
    assert updated_stage == STAGE_B_MODEL


@pytest.mark.asyncio
async def test_update_pipeline_stage_duplicate_order(mock_db_session):
    """Test update_pipeline_stage: Lỗi trùng order."""
    stage_id = STAGE_B_MODEL.id
    update_data = {"order": STAGE_A_MODEL.order}
    update_in = schemas.PipelineStageUpdate(**update_data)
    mock_db_session.get.return_value = STAGE_B_MODEL
    mock_db_session.scalar.return_value = STAGE_A_MODEL
    with pytest.raises(DuplicateResourceError) as exc_info:
        await pipeline_service.update_pipeline_stage(
            mock_db_session, stage_id, update_in
        )
    assert (
        exc_info.value.detail
        == f"Pipeline Stage order '{STAGE_A_MODEL.order}' already in use."
    )
    mock_db_session.add.assert_not_called()
    mock_db_session.commit.assert_not_awaited()


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.invalidate_pipeline_cache", new_callable=AsyncMock
)  # Thêm mock invalidate
async def test_delete_pipeline_stage_success(
    mock_invalidate, mock_db_session
):  # Thêm mock_invalidate
    """Test delete_pipeline_stage: Xóa thành công."""
    stage_id = "STAGE_TO_DELETE"
    stage_to_delete = PipelineStage(id=stage_id, name="Delete Me", order=99)
    mock_db_session.get.return_value = stage_to_delete
    mock_db_session.scalar.return_value = 0  # Không có status nào dùng
    await pipeline_service.delete_pipeline_stage(mock_db_session, stage_id)
    mock_db_session.get.assert_awaited_once_with(PipelineStage, stage_id)
    mock_db_session.scalar.assert_awaited_once()
    mock_db_session.delete.assert_awaited_once_with(stage_to_delete)
    mock_db_session.commit.assert_awaited_once()
    mock_invalidate.assert_awaited_once()  # Kiểm tra invalidate cache


@pytest.mark.asyncio
async def test_delete_pipeline_stage_in_use(mock_db_session):
    """Test delete_pipeline_stage: Lỗi do đang được status sử dụng."""
    stage_id = STAGE_A_MODEL.id
    mock_db_session.get.return_value = STAGE_A_MODEL
    mock_db_session.scalar.return_value = 1  # Có 1 status đang dùng
    with pytest.raises(DuplicateResourceError) as exc_info:
        await pipeline_service.delete_pipeline_stage(mock_db_session, stage_id)
    assert f"Cannot delete stage '{stage_id}'" in exc_info.value.detail
    assert (
        "1 consultation statuses linked to it" in exc_info.value.detail
    )  # Sửa số lượng nếu cần
    mock_db_session.delete.assert_not_awaited()
    mock_db_session.commit.assert_not_awaited()


# === Tests cho CRUD Statuses (Service Layer) ===


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.invalidate_pipeline_cache", new_callable=AsyncMock
)
async def test_create_consultation_status_success(mock_invalidate, mock_db_session):
    """Test create_consultation_status: Tạo thành công."""
    status_data = {
        "id": "NEW_T",
        "name": "New Status",
        "color_code": "#123456",
        "stage_id": STAGE_A_MODEL.id,
    }
    status_in = schemas.ConsultationStatusCreate(**status_data)
    mock_db_session.get.side_effect = [None, STAGE_A_MODEL]
    created_status = await pipeline_service.create_consultation_status(
        mock_db_session, status_in
    )
    assert mock_db_session.get.await_count == 2
    mock_db_session.add.assert_called_once()
    added_arg = mock_db_session.add.call_args[0][0]
    assert isinstance(added_arg, ConsultationStatus)
    assert added_arg.id == status_data["id"]
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_arg)
    mock_invalidate.assert_awaited_once()
    assert created_status == added_arg


@pytest.mark.asyncio
async def test_create_consultation_status_duplicate_id(mock_db_session):
    """Test create_consultation_status: Lỗi trùng ID."""
    status_data = TestPipelineData.STATUS_A1
    status_in = schemas.ConsultationStatusCreate(**status_data)
    mock_db_session.get.return_value = STATUS_A1_MODEL
    with pytest.raises(DuplicateResourceError) as exc_info:
        await pipeline_service.create_consultation_status(mock_db_session, status_in)
    assert (
        exc_info.value.detail
        == f"Consultation Status ID '{status_data['id']}' already exists."
    )
    mock_db_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_consultation_status_stage_not_found(mock_db_session):
    """Test create_consultation_status: Lỗi Stage ID không tồn tại."""
    invalid_stage_id = "INVALID_STAGE"
    # --- FIX: Sửa color_code thành hợp lệ ---
    status_data = {
        "id": "NEW_T",
        "name": "New",
        "color_code": "#ffffff",
        "stage_id": invalid_stage_id,
    }
    status_in = schemas.ConsultationStatusCreate(**status_data)
    mock_db_session.get.side_effect = [None, None]
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await pipeline_service.create_consultation_status(mock_db_session, status_in)
    assert exc_info.value.detail == f"Pipeline Stage '{invalid_stage_id}' not found."
    mock_db_session.add.assert_not_called()


# ... (Thêm test cases cho get, update, delete ConsultationStatus tương tự stages) ...


@pytest.mark.asyncio
@patch(
    "app.services.pipeline_service.invalidate_pipeline_cache", new_callable=AsyncMock
)  # Thêm mock invalidate
async def test_delete_consultation_status_success(
    mock_invalidate, mock_db_session
):  # Thêm mock_invalidate
    """Test delete_consultation_status: Xóa thành công."""
    status_id = "STATUS_TO_DELETE"
    status_to_delete = ConsultationStatus(
        id=status_id, name="Delete Me", color_code="#eee", stage_id=STAGE_A_MODEL.id
    )
    mock_db_session.get.return_value = status_to_delete
    # Mock scalar (check lead count và consultation count) trả về 0
    mock_db_session.scalar.side_effect = [
        0,
        0,
    ]  # Lần 1 cho lead, lần 2 cho consultation

    await pipeline_service.delete_consultation_status(mock_db_session, status_id)

    mock_db_session.get.assert_awaited_once_with(ConsultationStatus, status_id)
    assert mock_db_session.scalar.await_count == 2  # Check cả lead và consultation
    mock_db_session.delete.assert_awaited_once_with(status_to_delete)
    mock_db_session.commit.assert_awaited_once()
    mock_invalidate.assert_awaited_once()  # Check invalidate


@pytest.mark.asyncio
async def test_delete_consultation_status_in_use_by_lead(mock_db_session):
    """Test delete_consultation_status: Lỗi do đang được Lead sử dụng."""
    status_id = STATUS_A1_MODEL.id
    mock_db_session.get.return_value = STATUS_A1_MODEL
    mock_db_session.scalar.return_value = 1  # Có 1 lead đang dùng
    with pytest.raises(DuplicateResourceError) as exc_info:
        await pipeline_service.delete_consultation_status(mock_db_session, status_id)
    assert f"Cannot delete status '{status_id}'" in exc_info.value.detail
    assert "currently used by 1 leads" in exc_info.value.detail
    mock_db_session.delete.assert_not_awaited()


# (Optional) Thêm test case kiểm tra ràng buộc Consultation (tương tự Lead)
@pytest.mark.asyncio
async def test_delete_consultation_status_in_use_by_consultation(mock_db_session):
    """Test delete_consultation_status: Lỗi do consultation record sử dụng."""
    status_id = STATUS_B1_MODEL.id
    mock_db_session.get.return_value = STATUS_B1_MODEL
    # Mock scalar: Lần 1 (lead) trả về 0, Lần 2 (consultation) trả về > 0
    mock_db_session.scalar.side_effect = [0, 5]

    with pytest.raises(DuplicateResourceError) as exc_info:
        await pipeline_service.delete_consultation_status(mock_db_session, status_id)

    assert f"Cannot delete status '{status_id}'" in exc_info.value.detail
    assert "linked to 5 consultation history records" in exc_info.value.detail
    mock_db_session.delete.assert_not_awaited()


# ===========================================================================
# TESTS FOR UNIVERSAL STATUS FEATURES
# ===========================================================================


@pytest.mark.asyncio
async def test_validate_status_transition_universal_status_always_allowed(
    mock_db_session,
):
    """Test validate_status_transition: Universal status luôn được phép."""
    # Setup: Lead ở sts06, chuyển sang sts01 (universal)
    from_status_id = "sts06"
    to_status_id = "sts01"

    # Mock universal status
    universal_status = ConsultationStatus(
        id="sts01",
        name="Không nghe máy",
        color_code="#FFA500",
        stage_id="stg01",
        outcome_type="neutral",
        is_final_status=False,
        is_universal=True,  # ✅ Universal
        updates_pipeline=False,
    )
    mock_db_session.get.return_value = universal_status

    # Action
    result = await pipeline_service.validate_status_transition(
        mock_db_session, from_status_id, to_status_id
    )

    # Assert: Should pass without querying allowed_transitions
    assert result is True
    mock_db_session.get.assert_awaited_once_with(ConsultationStatus, to_status_id)
    # execute KHÔNG được gọi (vì đã pass ở universal check)
    mock_db_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_status_transition_non_universal_without_rule_fails(
    mock_db_session,
):
    """Test validate_status_transition: Non-universal status không có rule → Fail."""
    # Setup: Lead ở sts06, chuyển sang sts11 (không có rule)
    from_status_id = "sts06"
    to_status_id = "sts11"

    # Mock non-universal status
    non_universal_status = ConsultationStatus(
        id="sts11",
        name="Đã nhập học",
        color_code="#28A745",
        stage_id="stg06",
        outcome_type="positive",
        is_final_status=True,
        is_universal=False,  # ❌ NOT universal
        updates_pipeline=True,
    )
    mock_db_session.get.return_value = non_universal_status

    # Mock không có transition rule
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

    # Action
    result = await pipeline_service.validate_status_transition(
        mock_db_session, from_status_id, to_status_id
    )

    # Assert: Should fail
    assert result is False
    mock_db_session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_status_transition_self_transition_allowed(mock_db_session):
    """Test validate_status_transition: Self-transition luôn được phép."""
    from_status_id = "sts06"
    to_status_id = "sts06"

    # Action
    result = await pipeline_service.validate_status_transition(
        mock_db_session, from_status_id, to_status_id
    )

    # Assert: Should pass immediately without DB query
    assert result is True
    mock_db_session.get.assert_not_awaited()
    mock_db_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_status_transition_new_lead_allowed(mock_db_session):
    """Test validate_status_transition: Lead mới (from=None) luôn được phép."""
    from_status_id = None
    to_status_id = "sts06"

    # Action
    result = await pipeline_service.validate_status_transition(
        mock_db_session, from_status_id, to_status_id
    )

    # Assert: Should pass immediately
    assert result is True
    mock_db_session.get.assert_not_awaited()
    mock_db_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_allowed_next_statuses_includes_universal(mock_db_session):
    """Test get_allowed_next_statuses: Luôn bao gồm universal statuses."""
    # Setup: Lead ở sts06, có rule: sts06 → sts07
    current_status_id = "sts06"

    # Mock current status
    current_status = ConsultationStatus(
        id="sts06",
        name="Quan tâm",
        color_code="#007BFF",
        stage_id="stg02",
        outcome_type="positive",
        is_final_status=False,
        is_universal=False,
        updates_pipeline=True,
    )

    # Mock allowed status (từ transition rule)
    allowed_status = ConsultationStatus(
        id="sts07",
        name="Không quan tâm",
        color_code="#DC3545",
        stage_id="stg02",
        outcome_type="negative",
        is_final_status=True,
        is_universal=False,
        updates_pipeline=True,
    )

    # Mock universal statuses
    universal_status_1 = ConsultationStatus(
        id="sts01",
        name="Không nghe máy",
        color_code="#FFA500",
        stage_id="stg01",
        outcome_type="neutral",
        is_final_status=False,
        is_universal=True,
        updates_pipeline=False,
    )
    universal_status_2 = ConsultationStatus(
        id="sts02",
        name="Thuê bao",
        color_code="#6C757D",
        stage_id="stg01",
        outcome_type="neutral",
        is_final_status=False,
        is_universal=True,
        updates_pipeline=False,
    )

    # Mock DB queries
    # First execute: Query allowed transitions → [sts07]
    mock_result_1 = MagicMock()
    mock_result_1.scalars.return_value.all.return_value = [allowed_status]

    # Second execute: Query universal statuses → [sts01, sts02]
    mock_result_2 = MagicMock()
    mock_result_2.scalars.return_value.all.return_value = [
        universal_status_1,
        universal_status_2,
    ]

    mock_db_session.execute.side_effect = [mock_result_1, mock_result_2]
    mock_db_session.get.return_value = current_status

    # Action
    result = await pipeline_service.get_allowed_next_statuses(
        mock_db_session, current_status_id
    )

    # Assert: Should include universal + allowed
    result_ids = [s.id for s in result]

    # Current status (sts06) không được thêm vì đã có trong allowed (giả sử)
    # Universal statuses
    assert "sts01" in result_ids  # Không nghe máy
    assert "sts02" in result_ids  # Thuê bao

    # Allowed status
    assert "sts07" in result_ids  # Không quan tâm

    # Total count
    assert len(result) >= 3


@pytest.mark.asyncio
async def test_get_allowed_next_statuses_ordering(mock_db_session):
    """Test get_allowed_next_statuses: Thứ tự hiển thị đúng."""
    # Setup similar to previous test
    current_status_id = "sts06"

    current_status = ConsultationStatus(
        id="sts06",
        name="Quan tâm",
        color_code="#007BFF",
        stage_id="stg02",
        outcome_type="positive",
        is_final_status=False,
        is_universal=False,
        updates_pipeline=True,
    )

    allowed_status = ConsultationStatus(
        id="sts07",
        name="Không quan tâm",
        color_code="#DC3545",
        stage_id="stg02",
        outcome_type="negative",
        is_final_status=True,
        is_universal=False,
        updates_pipeline=True,
    )

    universal_status_1 = ConsultationStatus(
        id="sts01",
        name="Không nghe máy",
        color_code="#FFA500",
        stage_id="stg01",
        outcome_type="neutral",
        is_final_status=False,
        is_universal=True,
        updates_pipeline=False,
    )

    mock_result_1 = MagicMock()
    mock_result_1.scalars.return_value.all.return_value = [allowed_status]

    mock_result_2 = MagicMock()
    mock_result_2.scalars.return_value.all.return_value = [universal_status_1]

    mock_db_session.execute.side_effect = [mock_result_1, mock_result_2]
    mock_db_session.get.return_value = current_status

    # Action
    result = await pipeline_service.get_allowed_next_statuses(
        mock_db_session, current_status_id
    )

    # Assert: Check ordering
    # Expected: Universal first (sts01) → Allowed (sts07)
    result_ids = [s.id for s in result]

    # Universal should come before allowed
    idx_universal = result_ids.index("sts01")
    idx_allowed = result_ids.index("sts07")
    assert idx_universal < idx_allowed, "Universal status should come before allowed"


@pytest.mark.asyncio
@patch("app.services.pipeline_service.invalidate_pipeline_cache", new_callable=AsyncMock)
async def test_create_consultation_status_universal_with_legacy_warning(
    mock_invalidate, mock_db_session
):
    """Test create_consultation_status: Warning khi universal + legacy_status."""
    # Setup: Tạo universal status với legacy_status override
    status_in = schemas.ConsultationStatusCreate(
        id="sts99",
        name="Test Universal",
        color_code="#FFCC00",
        stage_id="stg01",
        outcome_type="neutral",
        is_final_status=False,
        is_universal=True,  # ✅ Universal
        updates_pipeline=False,
        legacy_status="contacted",  # ⚠️ Có legacy_status
    )

    # Mock stage exists
    mock_stage = MagicMock()
    mock_db_session.get.side_effect = [
        None,  # Check existing ID → không tồn tại
        mock_stage,  # Get stage → tồn tại
    ]
    mock_db_session.scalar.return_value = None  # Check name duplicate → không trùng

    # Mock refresh to return created status
    created_status = ConsultationStatus(**status_in.model_dump(mode='python'))
    mock_db_session.refresh.side_effect = lambda obj: setattr(
        obj, "id", created_status.id
    )

    # Action (should log warning but not raise error)
    with patch("app.services.pipeline_service.log") as mock_log:
        result = await pipeline_service.create_consultation_status(
            mock_db_session, status_in
        )

        # Assert: Warning was logged
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args[1]
        assert "universal status with legacy_status" in call_args.get("", "").lower() or \
               call_args.get("status_id") == "sts99"

    # Assert: Status was created successfully (no error raised)
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_awaited_once()
