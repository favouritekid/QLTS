# tests/services/test_assignment_service.py
# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio  # <-- Sử dụng pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings

# Import các thành phần cần test
from app.services import assignment_service
from app.utils.exceptions import (
    ResourceNotFoundError,  # Mặc dù service không ném, nhưng để đó
)

# Import constants
try:
    from ..fixtures.constants import (
        NON_EXISTENT_ID,
        TestLeadData,
        TestOrgData,
        TestUsers,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")


# === Fixture cho session mock (Giữ nguyên) ===
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

    # Mock cho async with db.begin_nested():
    mock_nested_transaction = AsyncMock()
    mock_nested_transaction.__aenter__ = AsyncMock(return_value=None)
    mock_nested_transaction.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested.return_value = mock_nested_transaction

    # Mock cho db.flush() để gán ID
    async def mock_flush(objects=None):
        if objects:
            for obj in objects:
                if (
                    isinstance(obj, (models.Lead, models.AssignmentLog))
                    and obj.id is None
                ):
                    obj.id = 1  # Gán ID giả
        return None

    session.flush = AsyncMock(side_effect=mock_flush)

    # Cấu hình mặc định (sẽ bị ghi đè trong tests)
    mock_execute_result = MagicMock()
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = []
    mock_scalars_result.first.return_value = None
    mock_scalars_result.scalar_one_or_none.return_value = None
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_execute_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_execute_result
    session.scalar.return_value = None
    session.get.return_value = None
    return session


# === Fixture cho Mock Logger ===
@pytest_asyncio.fixture(autouse=True)  # <-- ĐỔI THÀNH pytest_asyncio.fixture
async def mock_log(mocker):  # <-- ĐỔI THÀNH async def
    """Mock logger trong service."""
    log_path = "app.services.assignment_service.log"

    # Tạo mock bên trong fixture (đã có event loop)
    mock_log_obj = MagicMock()
    mock_log_obj.info = AsyncMock(return_value=None)
    mock_log_obj.error = AsyncMock(return_value=None)
    mock_log_obj.warning = AsyncMock(return_value=None)
    mock_log_obj.debug = AsyncMock(return_value=None)

    # Patch vẫn dùng mocker (đồng bộ)
    try:
        mocker.patch(f"{log_path}.info", new=mock_log_obj.info)
        mocker.patch(f"{log_path}.error", new=mock_log_obj.error)
        mocker.patch(f"{log_path}.warning", new=mock_log_obj.warning)
        mocker.patch(f"{log_path}.debug", new=mock_log_obj.debug)
    except Exception as e:
        # Cảnh báo này có thể vẫn xuất hiện nếu patch thất bại, nhưng mock nên hoạt động
        print(f"WARNING: Structlog patching in test_assignment_service failed: {e}")

    return mock_log_obj  # Trả về mock


# === Dữ liệu mẫu cho Tests ===


@pytest.fixture
def lead_new():
    """Lead mới, chưa gán, thuộc unit 1."""
    return models.Lead(
        id=1,
        full_name="New Lead",
        email="new@example.com",
        phone="123456",
        source="website",
        unit_id=1,
        status="new",  # Trạng thái ban đầu
        assigned_officer_id=None,
        assigned_at=None,
    )


@pytest.fixture
def officer_1():
    """Officer 1, unit 1, capacity 10, rảnh."""
    return models.User(
        id=101,
        username="officer1",
        role="officer",
        status="active",
        availability_status="available",
        unit_id=1,
        max_capacity=10,
        last_assigned_at=None,  # Chưa được gán bao giờ
    )


@pytest.fixture
def officer_2():
    """Officer 2, unit 1, capacity 10, vừa được gán."""
    return models.User(
        id=102,
        username="officer2",
        role="officer",
        status="active",
        availability_status="available",
        unit_id=1,
        max_capacity=10,
        last_assigned_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Mới
    )


@pytest.fixture
def officer_3_other_unit():
    """Officer 3, unit 2, không liên quan."""
    return models.User(
        id=103,
        username="officer3",
        role="officer",
        status="active",
        availability_status="available",
        unit_id=2,  # Unit khác
        max_capacity=10,
        last_assigned_at=None,
    )


# === Bắt đầu Tests ===
@pytest.mark.asyncio
async def test_assign_success_picks_lower_workload(
    mock_db_session, mock_log, lead_new, officer_1, officer_2
):
    """
    Test Kịch bản thành công:
    - Lead 1 (unit 1)
    - Officer 1 (unit 1, capacity 10, workload 2)
    - Officer 2 (unit 1, capacity 10, workload 5)
    - Service phải chọn Officer 1.
    """

    # 1. Setup Mocks
    class MockWorkloadRow:
        def __init__(self, assigned_officer_id, workload):
            self.assigned_officer_id = assigned_officer_id
            self.workload = workload

    mock_lead_result = MagicMock()
    mock_lead_result.scalar_one_or_none.return_value = lead_new

    mock_officers_result = MagicMock()
    mock_officers_result.scalars.return_value.all.return_value = [officer_1, officer_2]

    mock_workload_result = [
        MockWorkloadRow(assigned_officer_id=101, workload=2),
        MockWorkloadRow(assigned_officer_id=102, workload=5),
    ]

    mock_db_session.execute.side_effect = [
        mock_lead_result,
        mock_officers_result,
        mock_workload_result,
    ]

    # 2. Action
    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # 3. Assert (Giữ nguyên assertions về model)
    assert lead_new.assigned_officer_id == officer_1.id
    assert lead_new.status == settings.DEFAULT_ASSIGNED_LEAD_STATUS
    assert lead_new.assigned_at is not None
    assert officer_1.last_assigned_at is not None
    assert mock_db_session.add.call_count == 3
    # ... (Giữ nguyên assertions về add) ...

    # SỬA LỖI 2: Cập nhật assertion log (kwargs phải khớp)
    mock_log.info.assert_any_await(
        "Selected officer for assignment",
        officer_id=officer_1.id,
        current_workload=2,
        max_capacity=officer_1.max_capacity,  # Thêm max_capacity
        lead_id=lead_new.id,  # Thêm lead_id
    )
    mock_log.info.assert_any_await(
        "Auto-assign task: Lead assigned successfully",
        lead_id=lead_new.id,
        officer_id=officer_1.id,
    )


@pytest.mark.asyncio
async def test_assign_success_fairness_tiebreaker(
    mock_db_session, mock_log, lead_new, officer_1, officer_2
):
    """
    Test Kịch bản thành công (Fairness):
    - Officer 1 (workload 2, last_assigned = 1 ngày trước)
    - Officer 2 (workload 2, last_assigned = 1 giờ trước)
    - Service phải chọn Officer 1.
    """

    officer_1.last_assigned_at = datetime.now(timezone.utc) - timedelta(days=1)

    # 1. Setup Mocks
    class MockWorkloadRow:
        def __init__(self, assigned_officer_id, workload):
            self.assigned_officer_id = assigned_officer_id
            self.workload = workload

    mock_lead_result = MagicMock()
    mock_lead_result.scalar_one_or_none.return_value = lead_new

    mock_officers_result = MagicMock()
    mock_officers_result.scalars.return_value.all.return_value = [officer_1, officer_2]

    mock_workload_result = [
        MockWorkloadRow(assigned_officer_id=101, workload=2),
        MockWorkloadRow(assigned_officer_id=102, workload=2),
    ]

    mock_db_session.execute.side_effect = [
        mock_lead_result,
        mock_officers_result,
        mock_workload_result,
    ]

    # 2. Action
    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # 3. Assert (Giữ nguyên assertions về model)
    assert lead_new.assigned_officer_id == officer_1.id
    assert lead_new.status == settings.DEFAULT_ASSIGNED_LEAD_STATUS
    # ... (Giữ nguyên assertions về add) ...

    # SỬA LỖI 2: Cập nhật assertion log (kwargs phải khớp)
    mock_log.info.assert_any_await(
        "Selected officer for assignment",
        officer_id=officer_1.id,
        current_workload=2,
        max_capacity=officer_1.max_capacity,  # Thêm max_capacity
        lead_id=lead_new.id,  # Thêm lead_id
    )


@pytest.mark.asyncio
async def test_assign_fail_no_officers_available(mock_db_session, mock_log, lead_new):
    """Test Kịch bản lỗi: Không tìm thấy officer nào (danh sách rỗng)."""

    # 1. Setup Mocks
    mock_lead_result = MagicMock()
    mock_lead_result.scalar_one_or_none.return_value = lead_new

    mock_officers_result = MagicMock()
    mock_officers_result.scalars.return_value.all.return_value = []  # Không có officer

    mock_db_session.execute.side_effect = [mock_lead_result, mock_officers_result]

    # 2. Action
    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # 3. Assert (Giữ nguyên assertions về model)
    assert lead_new.assigned_officer_id is None
    assert lead_new.status == settings.DEFAULT_UNASSIGNED_LEAD_STATUS
    assert mock_db_session.add.call_count == 1

    # SỬA LỖI 2: Cập nhật assertion log (kwargs phải khớp)
    mock_log.warning.assert_any_await(
        "Auto-assign task: No available officers found",
        lead_id=lead_new.id,
        unit_id=lead_new.unit_id,  # Giữ nguyên
    )


@pytest.mark.asyncio
async def test_assign_fail_all_officers_full_capacity(
    mock_db_session, mock_log, lead_new, officer_1, officer_2
):
    """Test Kịch bản lỗi: Các officer đều đã đầy workload."""

    # 1. Setup Mocks
    class MockWorkloadRow:
        def __init__(self, assigned_officer_id, workload):
            self.assigned_officer_id = assigned_officer_id
            self.workload = workload

    mock_lead_result = MagicMock()
    mock_lead_result.scalar_one_or_none.return_value = lead_new

    mock_officers_result = MagicMock()
    mock_officers_result.scalars.return_value.all.return_value = [officer_1, officer_2]

    mock_workload_result = [
        MockWorkloadRow(assigned_officer_id=101, workload=10),
        MockWorkloadRow(assigned_officer_id=102, workload=10),
    ]

    mock_db_session.execute.side_effect = [
        mock_lead_result,
        mock_officers_result,
        mock_workload_result,
    ]

    # 2. Action
    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # 3. Assert (Giữ nguyên assertions về model)
    assert lead_new.assigned_officer_id is None
    assert lead_new.status == settings.DEFAULT_UNASSIGNED_LEAD_STATUS
    assert mock_db_session.add.call_count == 1

    # SỬA LỖI 2: Cập nhật assertion log (kwargs phải khớp)
    mock_log.warning.assert_any_await(
        "Auto-assign task: All available officers are at full capacity",
        lead_id=lead_new.id,
        unit_id=lead_new.unit_id,  # Service log có unit_id
    )


@pytest.mark.asyncio
async def test_assign_skip_lead_not_found(mock_db_session, mock_log):
    """Test Kịch bản bỏ qua: Lead ID không tồn tại."""

    # 1. Setup Mocks
    mock_lead_result = MagicMock()
    mock_lead_result.scalar_one_or_none.return_value = None  # Không tìm thấy lead
    mock_db_session.execute.return_value = mock_lead_result

    # 2. Action
    await assignment_service.automatically_assign_lead(NON_EXISTENT_ID, mock_db_session)

    # 3. Assert
    mock_db_session.execute.assert_awaited_once()
    assert mock_db_session.add.call_count == 0
    # SỬA LỖI 2: Cập nhật assertion log
    mock_log.warning.assert_any_await(
        "Auto-assign task: Lead not found", lead_id=NON_EXISTENT_ID
    )


@pytest.mark.asyncio
async def test_assign_skip_lead_already_assigned(mock_db_session, mock_log, lead_new):
    """Test Kịch bản bỏ qua: Lead đã được gán (race condition)."""

    # 1. Setup Mocks
    lead_new.assigned_officer_id = 999
    mock_lead_result = MagicMock()
    mock_lead_result.scalar_one_or_none.return_value = lead_new
    mock_db_session.execute.return_value = mock_lead_result

    # 2. Action
    await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # 3. Assert
    mock_db_session.execute.assert_awaited_once()
    assert mock_db_session.add.call_count == 0
    # SỬA LỖI 2: Cập nhật assertion log
    mock_log.info.assert_any_await(
        "Auto-assign task: Lead already assigned", lead_id=lead_new.id
    )


@pytest.mark.asyncio
async def test_assign_db_error_rollback(mock_db_session, mock_log, lead_new, officer_1):
    """Test Kịch bản lỗi: DB Error xảy ra (ví dụ khi add)."""

    # 1. Setup Mocks
    mock_lead_result = MagicMock()
    mock_lead_result.scalar_one_or_none.return_value = lead_new

    mock_officers_result = MagicMock()
    mock_officers_result.scalars.return_value.all.return_value = [officer_1]

    mock_workload_result = []

    mock_db_session.execute.side_effect = [
        mock_lead_result,
        mock_officers_result,
        mock_workload_result,
    ]

    db_error = SQLAlchemyError("Simulated DB Error")
    mock_db_session.add.side_effect = db_error

    # 2. Action & Assert Exception
    with pytest.raises(SQLAlchemyError) as exc_info:
        await assignment_service.automatically_assign_lead(lead_new.id, mock_db_session)

    # 3. Assert
    assert exc_info.value == db_error
    # SỬA LỖI 2: Cập nhật assertion log (thêm exc_info=True)
    mock_log.error.assert_any_await(
        "Auto-assign task: Failed and rolled back",
        lead_id=lead_new.id,
        error=str(db_error),
        exc_info=True,  # Service đang log với exc_info=True
    )
