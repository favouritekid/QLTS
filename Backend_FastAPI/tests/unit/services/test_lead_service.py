# tests/services/test_lead_service.py
# -*- coding: utf-8 -*-
import asyncio  # Cần cho việc tạo loop trong fixture
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.config import settings

# Import necessary components from the app
from app.services import lead_service
from app.utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

# Import constants and fixtures if needed (adjust paths as necessary)
try:
    from ..fixtures.constants import (
        NON_EXISTENT_ID,
        TestLeadData,
        TestOrgData,
        TestPipelineData,
        TestUsers,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")


# --- DỮ LIỆU MOCK (Giữ nguyên) ---
mock_admin_user = models.User(id=99, username="testadmin", role="admin")
mock_manager_user = models.User(id=98, username="testmanager", role="manager")
mock_officer_user = models.User(id=1, username="testofficer", role="officer")
mock_other_officer = models.User(id=2, username="otherofficer", role="officer")

mock_initial_status = models.ConsultationStatus(
    id=settings.DEFAULT_INITIAL_LEAD_STATUS_ID,
    name="Initial",
    color_code="#AAAAAA",
    stage_id="STAGE_A",
)
mock_assigned_status = models.ConsultationStatus(
    id=settings.DEFAULT_ASSIGNED_LEAD_STATUS,
    name="Assigned",
    color_code="#BBBBBB",
    stage_id="STAGE_A",
)
mock_lost_status = models.ConsultationStatus(
    id=settings.DEFAULT_LOST_LEAD_STATUS_ID,
    name="Lost",
    color_code="#FF0000",
    stage_id="STAGE_LOST",
)
mock_consult_status = models.ConsultationStatus(
    id="TTHV001", name="Consulting", color_code="#0000FF", stage_id="STAGE_A"
)
mock_lead_data = TestLeadData.LEAD_CREATE_PAYLOAD


# --- FIXTURES LEAD (Giữ nguyên) ---
@pytest.fixture
def base_lead_unassigned():
    """Tạo đối tượng Lead cơ sở (chưa gán) độc lập cho mỗi test."""
    return models.Lead(
        id=None,  # Bắt đầu với ID=None để flush có thể gán
        full_name=mock_lead_data["full_name"],
        email=mock_lead_data["email"],
        phone=mock_lead_data["phone"],
        source=mock_lead_data["source"],
        unit_id=mock_lead_data["unit_id"],
        major_id=mock_lead_data.get("major_id"),
        status=None,
        consultation_status_id=None,
        pipeline_stage_id=None,
        assigned_officer_id=None,
    )


@pytest.fixture
def base_lead_assigned():
    """Tạo đối tượng Lead đã gán độc lập cho mỗi test."""
    base_lead_1_data = {
        k: v
        for k, v in TestLeadData.LEAD_1.items()
        if k
        not in [
            "status",
            "consultation_status_id",
            "pipeline_stage_id",
            "assigned_officer_id",
        ]
    }
    return models.Lead(
        id=2,  # ID đã có
        **base_lead_1_data,
        status=mock_assigned_status.id,
        consultation_status_id=mock_assigned_status.id,
        pipeline_stage_id=mock_assigned_status.stage_id,
        assigned_officer_id=mock_officer_user.id,
    )


# ---------------------------------------------------------------------


# === Fixture for mock DB session (ĐÃ SỬA LỖI 3) ===
@pytest.fixture
def mock_db_session():
    """Creates a mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock()
    session.scalar = AsyncMock()
    session.rollback = AsyncMock()

    # SỬA LỖI 3: Thêm mock cho flush
    # Hàm này là async và cần gán ID cho đối tượng
    async def mock_flush(objects=None):
        if objects:
            for obj in objects:
                if isinstance(obj, models.Lead) and obj.id is None:
                    obj.id = 1  # Gán ID giả (ví dụ: 1)
        return None

    session.flush = AsyncMock(side_effect=mock_flush)
    # --- Kết thúc sửa lỗi 3 ---

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


# === Mocks for External Dependencies (ĐÃ SỬA LỖI 1) ===
@pytest.fixture(autouse=True)
def mock_external_deps(mocker):
    log_path = "app.services.lead_service.log"

    mock_log_obj = MagicMock()
    mock_log_obj.info = AsyncMock(return_value=None)
    mock_log_obj.error = AsyncMock(return_value=None)
    mock_log_obj.warning = AsyncMock(return_value=None)
    mock_log_obj.debug = AsyncMock(return_value=None)  # Thêm debug

    try:
        mocker.patch(f"{log_path}.info", new=mock_log_obj.info)
        mocker.patch(f"{log_path}.error", new=mock_log_obj.error)
        mocker.patch(f"{log_path}.warning", new=mock_log_obj.warning)
        mocker.patch(f"{log_path}.debug", new=mock_log_obj.debug)  # Thêm debug
    except Exception as e:
        print(f"WARNING: Structlog patching failed: {e}")

    # === SỬA LỖI 1: Thay đổi patch target ===
    # Patch vào vị trí gốc của task (nơi nó được định nghĩa)
    mock_celery = mocker.patch(
        "app.celery_utils.process_automatic_lead_assignment_task.delay",
        return_value=None,
    )

    mock_get_lead_by_id = mocker.patch(
        "app.services.lead_service.get_lead_by_id", new_callable=AsyncMock
    )

    return {
        "celery_delay": mock_celery,
        "get_lead_by_id": mock_get_lead_by_id,
        "log": mock_log_obj,  # Trả về mock log để kiểm tra
    }


# === Tests for create_lead (ĐÃ SỬA LỖI 3) ===


@pytest.mark.asyncio
async def test_create_lead_success(
    mock_db_session, mock_external_deps, base_lead_unassigned
):
    """Test POST /leads - Tạo thành công, kiểm tra status mặc định và side effect."""
    lead_in = schemas.LeadCreate(**mock_lead_data)

    # Mock DB calls
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = (
        None  # Không tìm thấy duplicate
    )
    mock_db_session.get.return_value = mock_initial_status  # Tìm thấy status mặc định

    # Mock get_lead_by_id (được gọi ở cuối)
    # Gán ID mà mock_flush sẽ gán (ID = 1)
    created_lead_obj = base_lead_unassigned
    created_lead_obj.id = 1
    mock_external_deps["get_lead_by_id"].return_value = created_lead_obj

    created_lead = await lead_service.create_lead(mock_db_session, lead_in)

    # Assertions
    mock_db_session.add.assert_called()
    added_lead = mock_db_session.add.call_args_list[0].args[0]  # [0] là Lead
    added_history = mock_db_session.add.call_args_list[1].args[0]  # [1] là History

    assert isinstance(added_lead, models.Lead)
    assert added_lead.status == mock_initial_status.id

    # SỬA LỖI 3: Kiểm tra flush và call_count
    mock_db_session.flush.assert_awaited_once_with(
        [added_lead]
    )  # Kiểm tra flush đã được gọi với Lead
    assert mock_db_session.add.call_count == 2  # Giờ nên là 2 (Lead + History)

    assert isinstance(added_history, models.LeadStatusHistory)
    assert added_history.lead_id == 1  # ID đã được gán bởi mock_flush

    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_lead)  # Refresh Lead
    mock_external_deps["celery_delay"].assert_called_once_with(1)  # Gọi Celery với ID

    assert created_lead == created_lead_obj
    mock_external_deps["log"].error.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_lead_duplicate_email_unit(
    mock_db_session, mock_external_deps, base_lead_unassigned
):
    """Test POST /leads - Lỗi 409 khi trùng email trong cùng unit. (FIXED: Lỗi logic mock)"""
    lead_in = schemas.LeadCreate(**mock_lead_data)

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = base_lead_unassigned
    mock_db_session.execute.return_value = mock_execute_result

    with pytest.raises(DuplicateResourceError) as exc_info:
        await lead_service.create_lead(mock_db_session, lead_in)

    assert exc_info.value.detail == "Lead with this email already exists in the unit."
    mock_db_session.rollback.assert_awaited_once()


# === Tests for update_lead ===


@pytest.mark.asyncio
async def test_update_lead_success(
    mock_db_session, mock_external_deps, base_lead_unassigned
):
    """Test PUT /leads/{id} - Cập nhật thành công, kiểm tra status update."""
    lead_id = base_lead_unassigned.id
    current_lead = base_lead_unassigned
    update_data = {
        "full_name": "Updated Lead Name",
        "consultation_status_id": mock_consult_status.id,
    }
    lead_update_schema = schemas.LeadUpdate(**update_data)

    mock_find_lead_result = MagicMock()
    mock_find_lead_result.scalar_one_or_none.return_value = current_lead
    mock_db_session.execute.return_value = mock_find_lead_result
    mock_db_session.get.return_value = mock_consult_status
    mock_external_deps["get_lead_by_id"].return_value = current_lead

    updated_lead = await lead_service.update_lead(
        mock_db_session, lead_id, lead_update_schema, mock_admin_user
    )

    assert current_lead.full_name == update_data["full_name"]
    assert current_lead.status == mock_consult_status.id

    # FIX: Tổng số lần gọi db.add là 2 (Lead + History)
    assert mock_db_session.add.call_count == 2
    assert updated_lead == current_lead


@pytest.mark.asyncio
async def test_update_lead_duplicate_email(
    mock_db_session, mock_external_deps, base_lead_unassigned
):
    """Test PUT /leads/{id} - Lỗi 409 khi cập nhật email trùng với user khác."""
    lead_id = base_lead_unassigned.id
    lead_to_update = base_lead_unassigned
    existing_other_lead = models.Lead(
        id=99, email="existing@example.com", unit_id=lead_to_update.unit_id
    )
    lead_update_schema = schemas.LeadUpdate(email="existing@example.com")

    mock_find_lead_result = MagicMock()
    mock_find_lead_result.scalar_one_or_none.return_value = lead_to_update
    mock_duplicate_check_result = MagicMock()
    mock_duplicate_check_result.scalar_one_or_none.return_value = existing_other_lead

    mock_db_session.execute.side_effect = [
        mock_find_lead_result,
        mock_duplicate_check_result,
    ]

    with pytest.raises(DuplicateResourceError) as exc_info:
        await lead_service.update_lead(
            mock_db_session, lead_id, lead_update_schema, mock_admin_user
        )

    assert (
        exc_info.value.detail
        == "Another lead with this email already exists in the unit."
    )


# === Tests for add_consultation ===


@pytest.mark.asyncio
async def test_add_consultation_success(
    mock_db_session, mock_external_deps, base_lead_assigned
):
    """Test POST /leads/{id}/consultations - Thêm consultation thành công. (FIXED call_count)"""
    lead_id = base_lead_assigned.id
    officer_id = mock_officer_user.id
    consult_data = {
        "method": "call",
        "notes": "Good call",
        "outcome": "follow-up",
        "status_id": mock_consult_status.id,
    }
    consult_in = schemas.ConsultationCreate(**consult_data)

    mock_external_deps["get_lead_by_id"].return_value = base_lead_assigned
    mock_db_session.get.side_effect = [mock_officer_user, mock_consult_status]

    # SỬA LỖI 3: Cấu hình mock_flush để gán ID cho consultation
    async def mock_flush(objects=None):
        if objects:
            for obj in objects:
                if isinstance(obj, models.Consultation) and obj.id is None:
                    obj.id = 10  # Gán ID giả cho consultation
        return None

    mock_db_session.flush = AsyncMock(side_effect=mock_flush)
    # ---

    new_consultation = await lead_service.add_consultation(
        mock_db_session, lead_id, officer_id, consult_in
    )

    assert base_lead_assigned.consultation_status_id == mock_consult_status.id

    # FIX: Tổng số lần gọi db.add là 3 (Consultation + Lead + History)
    assert mock_db_session.add.call_count == 3

    assert new_consultation is not None  # Đảm bảo trả về đối tượng


@pytest.mark.asyncio
async def test_add_consultation_permission_denied(
    mock_db_session, mock_external_deps, base_lead_assigned
):
    """Test POST /consultations - Lỗi 403 khi officer không được gán."""
    lead_id = base_lead_assigned.id
    officer_id = mock_other_officer.id
    consult_in = schemas.ConsultationCreate(
        method="call", notes="test", status_id=mock_consult_status.id
    )

    mock_external_deps["get_lead_by_id"].return_value = base_lead_assigned
    # SỬA LỖI 2: Cấu hình db.get trả về officer MÀ KHÔNG GÂY LỖI
    mock_db_session.get.side_effect = [mock_other_officer, mock_consult_status]

    with pytest.raises(PermissionDeniedError) as exc_info:
        await lead_service.add_consultation(
            mock_db_session, lead_id, officer_id, consult_in
        )

    assert exc_info.value.detail == "You are not assigned to this lead."
    # Đảm bảo get_lead_by_id được gọi
    mock_external_deps["get_lead_by_id"].assert_awaited_once_with(
        mock_db_session, lead_id
    )
    # Đảm bảo db.get được gọi để lấy officer
    mock_db_session.get.assert_awaited_once_with(models.User, officer_id)


# === Tests for assign_lead_manually ===


@pytest.mark.asyncio
async def test_assign_lead_manually_success(
    mock_db_session, mock_external_deps, base_lead_unassigned
):
    """Test manual assignment - Gán lead thành công. (FIXED call_count)"""
    mock_lead = base_lead_unassigned
    lead_id = mock_lead.id
    officer_id = mock_officer_user.id
    assigner_user = mock_manager_user

    mock_external_deps["get_lead_by_id"].return_value = mock_lead
    mock_db_session.get.return_value = mock_officer_user

    updated_lead = await lead_service.assign_lead_manually(
        mock_db_session, lead_id, officer_id, assigner_user
    )

    assert mock_lead.assigned_officer_id == officer_id
    assert mock_lead.status == mock_assigned_status.id

    # FIX: Tổng số lần gọi db.add là 4 (Lead + Officer + Log + History)
    assert mock_db_session.add.call_count == 4

    assert updated_lead == mock_lead


# === Tests for process_officer_action (Reassign/Reject) ===


@pytest.mark.asyncio
async def test_process_officer_action_reassign_success(
    mock_db_session, mock_external_deps, base_lead_assigned
):
    """Test officer action: reassign - Kiểm tra Celery task được gọi."""
    mock_assigned_lead = base_lead_assigned
    lead_id = mock_assigned_lead.id
    officer_user = mock_officer_user
    action = "reassign"
    reason = "Officer requested reassignment"

    mock_external_deps["get_lead_by_id"].return_value = mock_assigned_lead

    # SỬA LỖI 2: Cấu hình mock_db_session.execute
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_assigned_lead
    mock_db_session.execute.return_value = mock_execute_result

    updated_lead = await lead_service.process_officer_action(
        mock_db_session, lead_id, officer_user, action, reason
    )

    assert mock_assigned_lead.assigned_officer_id is None
    # Sửa assertion: Kiểm tra mock_celery đã được trả về từ fixture
    assert mock_external_deps["celery_delay"] is not None
    mock_external_deps["celery_delay"].assert_called_once_with(lead_id)

    assert updated_lead == mock_assigned_lead


@pytest.mark.asyncio
async def test_process_officer_action_reject_success(
    mock_db_session, mock_external_deps, base_lead_assigned
):
    """Test officer action: reject - Kiểm tra status chuyển sang LOST."""
    mock_assigned_lead = base_lead_assigned
    lead_id = mock_assigned_lead.id
    officer_user = mock_officer_user
    action = "reject"

    mock_external_deps["get_lead_by_id"].return_value = mock_assigned_lead
    mock_db_session.get.return_value = mock_lost_status  # Lost status found

    # SỬA LỖI 2: Cấu hình mock_db_session.execute
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_assigned_lead
    mock_db_session.execute.return_value = mock_execute_result

    updated_lead = await lead_service.process_officer_action(
        mock_db_session, lead_id, officer_user, action, "Reason"
    )

    assert mock_assigned_lead.status == mock_lost_status.id
    # Sửa assertion: Kiểm tra return value
    assert updated_lead == mock_assigned_lead


@pytest.mark.asyncio
async def test_process_officer_action_permission_denied(
    mock_db_session, mock_external_deps, base_lead_assigned
):
    """Test officer action - Lỗi 403 khi officer không được gán."""
    lead_id = base_lead_assigned.id
    officer_user = mock_other_officer  # Officer khác có ID = 2

    mock_external_deps["get_lead_by_id"].return_value = base_lead_assigned

    # SỬA LỖI 2: Cấu hình mock_db_session.execute
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = base_lead_assigned
    mock_db_session.execute.return_value = mock_execute_result

    with pytest.raises(PermissionDeniedError) as exc_info:
        await lead_service.process_officer_action(
            mock_db_session, lead_id, officer_user, "reassign", "Test"
        )

    assert exc_info.value.detail == "You are not assigned to this lead."
    # Đảm bảo đã gọi execute để lấy lead
    mock_db_session.execute.assert_awaited_once()


# === Tests for delete_consultation (ĐÃ SỬA LỖI 2) ===
@pytest.mark.asyncio
async def test_delete_consultation_permission_denied_officer(
    mock_db_session, mock_external_deps, base_lead_assigned
):
    """Test DELETE /consultation - Lỗi 403 cho Officer."""
    lead_id = base_lead_assigned.id
    consult_id = 10
    mock_consultation = models.Consultation(
        id=consult_id, lead_id=lead_id, officer_id=mock_officer_user.id
    )

    mock_external_deps["get_lead_by_id"].return_value = base_lead_assigned
    mock_db_session.get.return_value = mock_consultation

    # SỬA LỖI 2: Cấu hình mock_db_session.execute (cho get_lead bên trong delete_consultation)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = base_lead_assigned
    mock_db_session.execute.return_value = mock_execute_result

    with pytest.raises(PermissionDeniedError) as exc_info:
        await lead_service.delete_consultation(
            mock_db_session, lead_id, consult_id, mock_officer_user
        )

    assert exc_info.value.detail == "Only admins can delete consultations."
    # Đảm bảo đã gọi execute để lấy lead
    mock_db_session.execute.assert_awaited_once()


# === Tests for revert_last_status (ĐÃ SỬA LỖI 2) ===
@pytest.mark.asyncio
async def test_revert_last_status_success(
    mock_db_session, mock_external_deps, base_lead_assigned
):
    """Test revert status thành công, kiểm tra Model state được hoàn tác."""
    mock_assigned_lead = base_lead_assigned
    lead_id = mock_assigned_lead.id

    mock_external_deps["get_lead_by_id"].return_value = mock_assigned_lead

    old_state = {
        "status": "TTHV000",
        "consultation_status_id": "TTHV000",
        "pipeline_stage_id": "STAGE_A",
        "assigned_officer_id": None,
    }
    new_state = {
        "status": mock_assigned_lead.status,
        "consultation_status_id": mock_assigned_lead.consultation_status_id,
        "pipeline_stage_id": mock_assigned_lead.pipeline_stage_id,
        "assigned_officer_id": mock_assigned_lead.assigned_officer_id,
    }
    mock_last_history = models.LeadStatusHistory(
        id=1,
        lead_id=lead_id,
        old_status=old_state["status"],
        new_status=new_state["status"],
        old_consultation_status_id=old_state["consultation_status_id"],
        new_consultation_status_id=new_state["consultation_status_id"],
        old_pipeline_stage_id=old_state["pipeline_stage_id"],
        new_pipeline_stage_id=new_state["pipeline_stage_id"],
        old_assigned_officer_id=old_state["assigned_officer_id"],
        new_assigned_officer_id=new_state["assigned_officer_id"],
        changed_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    mock_db_session.scalar.return_value = (
        mock_last_history  # Mock cho query tìm history
    )

    # SỬA LỖI 2: Cấu hình mock_db_session.execute (cho get_lead bên trong revert_last_status)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_assigned_lead
    mock_db_session.execute.return_value = mock_execute_result

    reverted_lead = await lead_service.revert_last_status(
        mock_db_session, lead_id, mock_admin_user, "Test revert"
    )

    # Kiểm tra trạng thái của model đã bị thay đổi
    assert mock_assigned_lead.assigned_officer_id == old_state["assigned_officer_id"]
    assert mock_assigned_lead.status == old_state["status"]

    # Sửa assertion: Kiểm tra return value
    assert reverted_lead == mock_assigned_lead
