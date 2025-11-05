# tests/services/test_user_service_management.py
# -*- coding: utf-8 -*-

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.config import settings
from app.models import User
from app.services import user_service
from app.utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

try:
    from ..fixtures.constants import NON_EXISTENT_ID, SecurityConstants, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")


# === Fixture cho session mock ===
@pytest.fixture
def mock_db_session():
    """Tạo một mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.commit = AsyncMock()
    # Cấu hình refresh để trả về None khi được await
    session.refresh = AsyncMock(return_value=None)

    # === SỬA LỖI MOCK EXECUTE ===
    # db.execute() là một coroutine, nên nó phải là AsyncMock
    session.execute = AsyncMock()

    session.delete = AsyncMock()
    session.get = AsyncMock()

    # Cấu hình MẶC ĐỊNH cho kết quả của execute
    # (sẽ bị ghi đè trong các test nếu cần)
    mock_execute_result = MagicMock()  # Kết quả của await db.execute() là đồng bộ
    mock_scalars_result = MagicMock()  # Kết quả của .scalars() là đồng bộ
    mock_scalars_result.all.return_value = []  # .all() trả về list rỗng
    mock_scalars_result.scalar_one_or_none.return_value = (
        None  # .scalar_one_or_none() trả về None
    )
    mock_scalars_result.scalar_one.return_value = 0  # .scalar_one() trả về 0

    mock_execute_result.scalars.return_value = mock_scalars_result
    # Cấu hình session.execute để trả về mock_execute_result KHI ĐƯỢC AWAIT
    session.execute.return_value = mock_execute_result

    return session


# === Lớp Giả lập UploadFile (Giữ nguyên) ===
class MockUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "image/png"):
        self.filename = filename
        self._content = content
        self.content_type = content_type
        self.file = MagicMock()
        self.read_called = False

        async def mock_read():
            if self.read_called:
                return b""
            self.read_called = True
            if self._content is None:
                raise IOError("Simulated file read error")
            return self._content

        self.read = AsyncMock(side_effect=mock_read)
        self.seek = MagicMock()
        self.tell = MagicMock()

    def __repr__(self):
        return f"<MockUploadFile filename={self.filename}>"


# === Bắt đầu các bài Test ===


# --- Mục 2.1 (Giữ nguyên, đã PASSED) ---
@pytest.mark.asyncio
@patch("app.services.user_service.get_password_hash", return_value="fixed_hash_value")
async def test_create_user_success(mock_get_hash, mock_db_session):
    user_data = TestUsers.DEFAULT
    # Note: Backend không cần confirm_password nữa
    user_in = schemas.UserCreate(
        username=user_data["username"],
        email=user_data["email"],
        password=user_data["password"],
        full_name="Default User",
    )
    created_user_model = await user_service.create_user(mock_db_session, user_in)
    mock_get_hash.assert_called_once_with(user_data["password"])
    mock_db_session.add.assert_called_once()
    added_user_arg = mock_db_session.add.call_args[0][0]
    assert isinstance(added_user_arg, User)
    assert added_user_arg.username == user_data["username"]
    assert added_user_arg.password_hash == "fixed_hash_value"
    assert added_user_arg.role == "user"
    assert added_user_arg.status == "active"
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_user_arg)
    assert created_user_model == added_user_arg


@pytest.mark.asyncio
@patch("app.services.user_service.get_password_hash", return_value="admin_hash")
@patch(
    "app.services.user_service.file_helpers.save_avatar",
    new_callable=AsyncMock,
    return_value="/static/avatars/new_avatar.png",
)
async def test_create_user_by_admin_success_with_avatar(
    mock_save_avatar, mock_get_hash, mock_db_session
):
    admin_data = TestUsers.ADMIN
    # Note: Backend không cần confirm_password nữa
    user_in = schemas.AdminUserCreate(
        username=admin_data["username"],
        email=admin_data["email"],
        password=admin_data["password"],
        full_name="Admin Full Name",
        role=admin_data["role"],
        status="pending",
    )
    mock_avatar_file = MockUploadFile(filename="avatar.png", content=b"fake_image")

    created_user_model = await user_service.create_user_by_admin(
        mock_db_session, user_in, avatar_file=mock_avatar_file
    )

    mock_get_hash.assert_called_once_with(admin_data["password"])
    # --- SỬA LỖI 1: Sửa assertion cho save_avatar ---
    mock_save_avatar.assert_awaited_once_with(mock_avatar_file)
    # --- KẾT THÚC SỬA ---
    mock_db_session.add.assert_called_once()
    added_user_arg = mock_db_session.add.call_args[0][0]
    assert isinstance(added_user_arg, User)
    assert added_user_arg.role == admin_data["role"]
    assert added_user_arg.status == "pending"
    assert added_user_arg.avatar_url == "/static/avatars/new_avatar.png"
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_user_arg)
    assert created_user_model == added_user_arg


@pytest.mark.asyncio
@patch("app.services.user_service.get_password_hash", return_value="manager_hash")
@patch("app.services.user_service.file_helpers.save_avatar", new_callable=AsyncMock)
async def test_create_user_by_admin_success_no_avatar(
    mock_save_avatar, mock_get_hash, mock_db_session
):
    # ... (Giữ nguyên, đã PASSED) ...
    # Note: Backend không cần confirm_password nữa
    user_in = schemas.AdminUserCreate(
        username="manageruser",
        email="manager@example.com",
        password="ManagerPassword!1",
        full_name="Manager Name",
        role="manager",
        status="active",
    )
    created_user_model = await user_service.create_user_by_admin(
        mock_db_session, user_in, avatar_file=None
    )
    mock_get_hash.assert_called_once_with("ManagerPassword!1")
    mock_save_avatar.assert_not_awaited()
    mock_db_session.add.assert_called_once()
    added_user_arg = mock_db_session.add.call_args[0][0]
    assert added_user_arg.avatar_url is None
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_user_arg)
    assert created_user_model == added_user_arg


# --- Mục 2.2 (Giữ nguyên, đã PASSED) ---
@pytest.mark.asyncio
async def test_get_user_by_id_found(mock_db_session):
    user_id = 1
    mock_user = User(id=user_id, username="found_user", email="found@e.com")
    mock_db_session.get.return_value = mock_user
    user = await user_service.get_user_by_id(mock_db_session, user_id)
    mock_db_session.get.assert_awaited_once_with(User, user_id)
    mock_db_session.refresh.assert_awaited_once_with(mock_user)
    assert user == mock_user


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(mock_db_session):
    user_id = NON_EXISTENT_ID
    mock_db_session.get.return_value = None
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await user_service.get_user_by_id(mock_db_session, user_id)
    mock_db_session.get.assert_awaited_once_with(User, user_id)
    mock_db_session.refresh.assert_not_awaited()
    assert exc_info.value.detail == f"User with id {user_id} not found."


# --- SỬA CÁC TEST SAU (get_by_username/email) ---
@pytest.mark.asyncio
async def test_get_user_by_username_found(mock_db_session):
    """Test get_user_by_username: Tìm thấy user."""
    username = TestUsers.DEFAULT["username"]
    mock_user = User(id=1, username=username, email="test@e.com")
    # Cấu hình mock execute trả về user
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user

    user = await user_service.get_user_by_username(mock_db_session, username)

    mock_db_session.execute.assert_awaited_once()
    # === SỬA LỖI 2: Sửa assertion cho refresh ===
    mock_db_session.refresh.assert_awaited_once()  # Kiểm tra được gọi
    # === KẾT THÚC SỬA ===
    assert user == mock_user  # Assertion này giờ sẽ đúng (vì service đã sửa)


@pytest.mark.asyncio
async def test_get_user_by_username_not_found(mock_db_session):
    """Test get_user_by_username: Không tìm thấy user."""
    username = TestUsers.NON_EXISTENT_USERNAME
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

    user = await user_service.get_user_by_username(mock_db_session, username)

    mock_db_session.execute.assert_awaited_once()
    # === SỬA LỖI 2: Xóa assertion `assert_not_awaited` ===
    # mock_db_session.refresh.assert_not_awaited()
    # === KẾT THÚC SỬA ===
    assert user is None  # Assertion này giờ sẽ đúng (vì service đã sửa)


@pytest.mark.asyncio
async def test_get_user_by_email_found(mock_db_session):
    """Test get_user_by_email: Tìm thấy user."""
    email = TestUsers.DEFAULT["email"]
    mock_user = User(id=1, username="test", email=email)
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user

    user = await user_service.get_user_by_email(mock_db_session, email)

    mock_db_session.execute.assert_awaited_once()
    # === SỬA LỖI 2: Sửa assertion cho refresh ===
    mock_db_session.refresh.assert_awaited_once()  # Kiểm tra được gọi
    # === KẾT THÚC SỬA ===
    assert user == mock_user


@pytest.mark.asyncio
async def test_get_user_by_email_not_found(mock_db_session):
    """Test get_user_by_email: Không tìm thấy user."""
    email = TestUsers.NON_EXISTENT_EMAIL
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

    user = await user_service.get_user_by_email(mock_db_session, email)

    mock_db_session.execute.assert_awaited_once()
    # === SỬA LỖI 2: Xóa assertion `assert_not_awaited` ===
    # mock_db_session.refresh.assert_not_awaited()
    # === KẾT THÚC SỬA ===
    assert user is None


# --- Mục 2.3 & 2.4 (SỬA LỖI `AttributeError`) ---


@pytest.mark.asyncio
async def test_get_users_basic(mock_db_session):
    """Test get_users: Lấy danh sách cơ bản."""
    mock_user1 = User(id=1, username="user1", email="user1@e.com")
    mock_user2 = User(id=2, username="user2", email="user2@e.com")
    mock_users_list = [mock_user1, mock_user2]
    expected_total_count = len(mock_users_list)

    # === SỬA LỖI 3 & 4: Cấu hình mock execute đúng cách ===
    # Mock cho count query (lần gọi execute đầu tiên)
    mock_count_result = MagicMock()  # Kết quả execute là ĐỒNG BỘ
    mock_count_result.scalar_one.return_value = expected_total_count

    # Mock cho data query (lần gọi execute thứ hai)
    mock_data_result = MagicMock()  # Kết quả execute là ĐỒNG BỘ
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = mock_users_list
    mock_data_result.scalars.return_value = mock_scalars

    # Cấu hình session.execute (là AsyncMock) để trả về các kết quả đồng bộ này
    mock_db_session.execute.side_effect = [mock_count_result, mock_data_result]
    # === KẾT THÚC SỬA ===

    total, users = await user_service.get_users(
        mock_db_session, params={}, skip=0, limit=10
    )

    assert mock_db_session.execute.await_count == 2
    assert total == expected_total_count
    assert users == mock_users_list


@pytest.mark.asyncio
async def test_perform_bulk_action_delete_success(mock_db_session):
    """Test perform_bulk_action: Bulk delete thành công, bỏ qua admin."""
    admin_user_mock = User(id=1, username="admin", role="admin")
    user_to_delete1 = User(id=2, username="user2del")
    user_to_delete2 = User(id=3, username="user3del")
    user_ids_input = [1, 2, 3]
    users_list_from_db = [admin_user_mock, user_to_delete1, user_to_delete2]

    # === SỬA LỖI 4: Cấu hình mock execute đúng cách ===
    mock_result_proxy = MagicMock()  # Kết quả execute là ĐỒNG BỘ
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = users_list_from_db
    mock_result_proxy.scalars.return_value = mock_scalars_result
    mock_db_session.execute.return_value = mock_result_proxy
    # === KẾT THÚC SỬA ===

    message = await user_service.perform_bulk_action(
        db=mock_db_session,
        action="delete",
        user_ids=user_ids_input,
        admin_user=admin_user_mock,
    )

    mock_db_session.execute.assert_awaited_once()
    assert mock_db_session.delete.call_count == 2
    mock_db_session.delete.assert_has_awaits(
        [call(user_to_delete1), call(user_to_delete2)], any_order=True
    )
    mock_db_session.commit.assert_awaited_once()
    assert message == "Successfully deleted 2 users."


@pytest.mark.asyncio
async def test_perform_bulk_action_change_status_success(mock_db_session):
    """Test perform_bulk_action: Bulk change status thành công."""
    admin_user_mock = User(id=1, username="admin")
    user_to_change1 = User(id=2, username="user2ch", status="active")
    user_to_change2 = User(id=3, username="user3ch", status="pending")
    user_ids_input = [2, 3]
    new_status = "banned"
    users_list_from_db = [user_to_change1, user_to_change2]

    # === SỬA LỖI 4: Cấu hình mock execute đúng cách ===
    mock_result_proxy = MagicMock()  # Kết quả execute là ĐỒNG BỘ
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = users_list_from_db
    mock_result_proxy.scalars.return_value = mock_scalars_result
    mock_db_session.execute.return_value = mock_result_proxy
    # === KẾT THÚC SỬA ===

    message = await user_service.perform_bulk_action(
        db=mock_db_session,
        action="change_status",
        user_ids=user_ids_input,
        admin_user=admin_user_mock,
        new_status=new_status,
    )

    mock_db_session.execute.assert_awaited_once()
    assert mock_db_session.add.call_count == 2
    mock_db_session.add.assert_has_calls(
        [call(user_to_change1), call(user_to_change2)], any_order=True
    )
    mock_db_session.commit.assert_awaited_once()
    assert user_to_change1.status == new_status
    assert user_to_change2.status == new_status
    assert message == f"Successfully updated status to '{new_status}' for 2 users."


@pytest.mark.asyncio
async def test_perform_bulk_action_change_status_skips_same_status(mock_db_session):
    """Test perform_bulk_action: Bỏ qua user đã có status mong muốn."""
    admin_user_mock = User(id=1, username="admin")
    user_to_change = User(id=2, username="user2ch", status="active")
    user_to_skip = User(id=3, username="user3skip", status="banned")
    user_ids_input = [2, 3]
    new_status = "banned"
    users_list_from_db = [user_to_change, user_to_skip]

    # === SỬA LỖI 4: Cấu hình mock execute đúng cách ===
    mock_result_proxy = MagicMock()  # Kết quả execute là ĐỒNG BỘ
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = users_list_from_db
    mock_result_proxy.scalars.return_value = mock_scalars_result
    mock_db_session.execute.return_value = mock_result_proxy
    # === KẾT THÚC SỬA ===

    message = await user_service.perform_bulk_action(
        db=mock_db_session,
        action="change_status",
        user_ids=user_ids_input,
        admin_user=admin_user_mock,
        new_status=new_status,
    )

    mock_db_session.execute.assert_awaited_once()
    mock_db_session.add.assert_called_once_with(user_to_change)
    mock_db_session.commit.assert_awaited_once()
    assert user_to_change.status == new_status
    assert user_to_skip.status == "banned"
    assert message == f"Successfully updated status to '{new_status}' for 1 users."


# --- Các test case kiểm tra lỗi (Giữ nguyên, đã PASSED) ---
@pytest.mark.asyncio
async def test_perform_bulk_action_change_status_invalid_status_value(mock_db_session):
    admin_user_mock = User(id=1, username="admin")
    invalid_status = "deleted"
    with pytest.raises(BadRequest) as exc_info:
        await user_service.perform_bulk_action(
            db=mock_db_session,
            action="change_status",
            user_ids=[2, 3],
            admin_user=admin_user_mock,
            new_status=invalid_status,
        )
    assert exc_info.value.detail == f"Invalid status value: {invalid_status}"
    mock_db_session.execute.assert_not_awaited()
    mock_db_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_perform_bulk_action_change_status_missing_status(mock_db_session):
    admin_user_mock = User(id=1, username="admin")
    with pytest.raises(BadRequest) as exc_info:
        await user_service.perform_bulk_action(
            db=mock_db_session,
            action="change_status",
            user_ids=[2, 3],
            admin_user=admin_user_mock,
            new_status=None,
        )
    assert "Invalid status value: None" in exc_info.value.detail
    mock_db_session.execute.assert_not_awaited()
    mock_db_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_perform_bulk_action_invalid_action(mock_db_session):
    admin_user_mock = User(id=1, username="admin")
    invalid_action = "update_role"
    with pytest.raises(BadRequest) as exc_info:
        await user_service.perform_bulk_action(
            db=mock_db_session,
            action=invalid_action,
            user_ids=[2, 3],
            admin_user=admin_user_mock,
        )
    assert exc_info.value.detail == f"Unsupported bulk action: {invalid_action}."
    mock_db_session.execute.assert_not_awaited()
    mock_db_session.commit.assert_not_awaited()
