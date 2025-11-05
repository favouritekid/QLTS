# tests/services/test_organization_service.py
# -*- coding: utf-8 -*-
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas

# Import các thành phần cần test
from app.services import organization_service
from app.utils.exceptions import DuplicateResourceError, ResourceNotFoundError

# Import constants
try:
    from ..fixtures.constants import NON_EXISTENT_ID, TestOrgData
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")


# === Fixture cho session mock (chuẩn) ===
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

    # Cấu hình mặc định (sẽ bị ghi đè trong tests)
    mock_execute_result = MagicMock()
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = []
    mock_scalars_result.first.return_value = None
    mock_scalars_result.one_or_none.return_value = None
    mock_scalars_result.unique.return_value = mock_scalars_result  # Chain .unique()
    mock_execute_result.scalars.return_value = mock_scalars_result
    mock_execute_result.scalar_one_or_none.return_value = None

    session.execute.return_value = mock_execute_result
    session.scalar.return_value = None
    session.get.return_value = None
    return session


# === Dữ liệu mẫu ===
@pytest.fixture
def mock_unit_1():
    """Trả về một đối tượng OrganizationUnit mẫu."""
    # Tạo đối tượng thật với relations giả lập (rỗng)
    unit = models.OrganizationUnit(**TestOrgData.UNIT_1)
    unit.children = []
    unit.majors = []
    unit.parent = None
    return unit


@pytest.fixture
def mock_unit_2_child(mock_unit_1):
    """Trả về một unit con của unit 1."""
    unit = models.OrganizationUnit(
        id=2, name="Test Unit 2 Child", type="Department", parent_id=mock_unit_1.id
    )
    unit.parent = mock_unit_1
    return unit


@pytest.fixture
def mock_major_1(mock_unit_1):
    """Trả về một đối tượng Major mẫu thuộc unit 1."""
    major = models.Major(**TestOrgData.MAJOR_1)
    major.unit = mock_unit_1
    return major


# === Mock các hàm nội bộ (Rất quan trọng) ===
# Các hàm CRUD của service này gọi lẫn nhau.
# Chúng ta patch các hàm "get" để cô lập logic của "create/update/delete".


@pytest.fixture
def mock_internal_get_unit(mocker):
    """Mocks the service's internal call to get_organization_unit_by_id"""
    return mocker.patch(
        "app.services.organization_service.get_organization_unit_by_id",
        new_callable=AsyncMock,
    )


@pytest.fixture
def mock_internal_get_major(mocker):
    """Mocks the service's internal call to get_major_by_id"""
    return mocker.patch(
        "app.services.organization_service.get_major_by_id", new_callable=AsyncMock
    )


# ==================================
# Tests cho OrganizationUnit
# ==================================


@pytest.mark.asyncio
async def test_get_all_organization_units(
    mock_db_session, mock_unit_1, mock_unit_2_child
):
    """Test lấy tất cả units thành công."""
    mock_list = [mock_unit_1, mock_unit_2_child]
    mock_db_session.execute.return_value.scalars.return_value.unique.return_value.all.return_value = (
        mock_list
    )

    result = await organization_service.get_all_organization_units(mock_db_session)

    mock_db_session.execute.assert_awaited_once()
    assert result == mock_list


@pytest.mark.asyncio
async def test_get_organization_unit_by_id_found(mock_db_session, mock_unit_1):
    """Test lấy unit theo ID thành công."""
    mock_db_session.execute.return_value.scalars.return_value.unique.return_value.one_or_none.return_value = (
        mock_unit_1
    )

    result = await organization_service.get_organization_unit_by_id(
        mock_db_session, mock_unit_1.id
    )

    mock_db_session.execute.assert_awaited_once()
    assert result == mock_unit_1


@pytest.mark.asyncio
async def test_get_organization_unit_by_id_not_found(mock_db_session):
    """Test lấy unit theo ID thất bại (404)."""
    mock_db_session.execute.return_value.scalars.return_value.unique.return_value.one_or_none.return_value = (
        None
    )

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await organization_service.get_organization_unit_by_id(
            mock_db_session, NON_EXISTENT_ID
        )

    assert str(NON_EXISTENT_ID) in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_organization_unit_success(
    mock_db_session, mock_internal_get_unit, mock_unit_1
):
    """Test tạo unit thành công (không có parent)."""
    unit_schema = schemas.OrganizationUnitCreate(
        name="New Unit", type="Faculty", parent_id=None
    )

    # Mock hàm get(parent_id)
    mock_db_session.get.return_value = None
    # Mock hàm get_organization_unit_by_id được gọi ở cuối
    mock_internal_get_unit.return_value = mock_unit_1

    result = await organization_service.create_organization_unit(
        mock_db_session, unit_schema
    )

    mock_db_session.add.assert_called_once()
    added_obj = mock_db_session.add.call_args[0][0]
    assert isinstance(added_obj, models.OrganizationUnit)
    assert added_obj.name == unit_schema.name
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_obj)
    mock_internal_get_unit.assert_awaited_once_with(mock_db_session, added_obj.id)
    assert result == mock_unit_1


@pytest.mark.asyncio
async def test_create_organization_unit_parent_not_found(
    mock_db_session, mock_internal_get_unit
):
    """Test tạo unit thất bại (parent_id không tồn tại)."""
    unit_schema = schemas.OrganizationUnitCreate(
        name="New Unit", type="Faculty", parent_id=NON_EXISTENT_ID
    )

    mock_db_session.get.return_value = None  # Không tìm thấy parent

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await organization_service.create_organization_unit(
            mock_db_session, unit_schema
        )

    assert f"Parent unit with id {NON_EXISTENT_ID} not found" in exc_info.value.detail
    mock_db_session.rollback.assert_awaited_once()
    mock_internal_get_unit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_organization_unit_success(
    mock_db_session, mock_internal_get_unit, mock_unit_1, mock_unit_2_child
):
    """Test cập nhật unit thành công."""
    unit_id = mock_unit_1.id
    update_schema = schemas.OrganizationUnitUpdate(
        name="Updated Name", parent_id=mock_unit_2_child.id
    )

    # Mock get_unit (lần 1)
    mock_internal_get_unit.side_effect = [
        mock_unit_1,  # Lần gọi đầu tiên (lấy unit để update)
        mock_unit_1,  # Lần gọi thứ hai (ở cuối hàm để trả về)
    ]
    # Mock get(parent_id)
    mock_db_session.get.return_value = mock_unit_2_child  # Tìm thấy parent mới

    result = await organization_service.update_organization_unit(
        mock_db_session, unit_id, update_schema
    )

    assert mock_internal_get_unit.await_count == 2
    mock_db_session.get.assert_awaited_once_with(
        models.OrganizationUnit, mock_unit_2_child.id
    )
    assert mock_unit_1.name == "Updated Name"
    assert mock_unit_1.parent_id == mock_unit_2_child.id
    mock_db_session.add.assert_called_once_with(mock_unit_1)
    mock_db_session.commit.assert_awaited_once()
    assert result == mock_unit_1


@pytest.mark.asyncio
async def test_update_organization_unit_parent_self(
    mock_db_session, mock_internal_get_unit, mock_unit_1
):
    """Test cập nhật unit thất bại (tự làm cha)."""
    unit_id = mock_unit_1.id
    update_schema = schemas.OrganizationUnitUpdate(parent_id=unit_id)  # Tự tham chiếu

    mock_internal_get_unit.return_value = mock_unit_1

    with pytest.raises(DuplicateResourceError) as exc_info:
        await organization_service.update_organization_unit(
            mock_db_session, unit_id, update_schema
        )

    assert "A unit cannot be its own parent" in exc_info.value.detail
    mock_db_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_organization_unit_success(
    mock_db_session, mock_internal_get_unit, mock_unit_1
):
    """Test xóa unit thành công (không có con/major)."""
    unit_id = mock_unit_1.id
    mock_unit_1.children = []  # Đảm bảo rỗng
    mock_unit_1.majors = []  # Đảm bảo rỗng
    mock_internal_get_unit.return_value = mock_unit_1

    await organization_service.delete_organization_unit(mock_db_session, unit_id)

    mock_internal_get_unit.assert_awaited_once_with(mock_db_session, unit_id)
    mock_db_session.delete.assert_awaited_once_with(mock_unit_1)
    mock_db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_organization_unit_conflict_children(
    mock_db_session, mock_internal_get_unit, mock_unit_1, mock_unit_2_child
):
    """Test xóa unit thất bại (còn unit con)."""
    unit_id = mock_unit_1.id
    mock_unit_1.children = [mock_unit_2_child]  # Có con
    mock_unit_1.majors = []
    mock_internal_get_unit.return_value = mock_unit_1

    with pytest.raises(DuplicateResourceError) as exc_info:
        await organization_service.delete_organization_unit(mock_db_session, unit_id)

    assert "It contains child units or majors" in exc_info.value.detail
    mock_db_session.rollback.assert_awaited_once()
    mock_db_session.delete.assert_not_awaited()


# ==================================
# Tests cho Major
# ==================================


@pytest.mark.asyncio
async def test_get_major_by_id_found(mock_db_session, mock_major_1):
    """Test lấy major theo ID thành công."""
    mock_db_session.get.return_value = mock_major_1
    result = await organization_service.get_major_by_id(
        mock_db_session, mock_major_1.id
    )
    mock_db_session.get.assert_awaited_once_with(models.Major, mock_major_1.id)
    assert result == mock_major_1


@pytest.mark.asyncio
async def test_get_major_by_id_not_found(mock_db_session):
    """Test lấy major theo ID thất bại (404)."""
    mock_db_session.get.return_value = None
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await organization_service.get_major_by_id(mock_db_session, NON_EXISTENT_ID)
    assert f"Major with id {NON_EXISTENT_ID} not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_major_success(mock_db_session, mock_major_1):
    """Test tạo major thành công."""
    major_schema = schemas.MajorCreate(
        name=mock_major_1.name, code=mock_major_1.code, unit_id=mock_major_1.unit_id
    )
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = (
        None  # Không trùng code
    )

    result = await organization_service.create_major(mock_db_session, major_schema)

    mock_db_session.execute.assert_awaited_once()
    mock_db_session.add.assert_called_once()
    added_obj = mock_db_session.add.call_args[0][0]
    assert isinstance(added_obj, models.Major)
    assert added_obj.code == major_schema.code
    mock_db_session.commit.assert_awaited_once()
    mock_db_session.refresh.assert_awaited_once_with(added_obj)
    assert result == added_obj


@pytest.mark.asyncio
async def test_create_major_duplicate_code(mock_db_session, mock_major_1):
    """Test tạo major thất bại (trùng code)."""
    major_schema = schemas.MajorCreate(
        name=mock_major_1.name, code=mock_major_1.code, unit_id=mock_major_1.unit_id
    )
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = (
        mock_major_1  # Trùng code
    )

    with pytest.raises(DuplicateResourceError) as exc_info:
        await organization_service.create_major(mock_db_session, major_schema)

    assert (
        f"Major with code '{major_schema.code}' already exists" in exc_info.value.detail
    )
    mock_db_session.rollback.assert_awaited_once()


# ... (Các test cho update_major và delete_major tương tự) ...

# ==================================
# Tests cho get_majors_by_unit_tree
# ==================================


@pytest.mark.asyncio
async def test_get_majors_by_unit_tree_success(mock_db_session, mock_major_1):
    """Test lấy major theo cây unit thành công (không search)."""
    unit_id = 1
    # 1. Mock kết quả cho query đệ quy (raw SQL)
    mock_unit_ids_result = MagicMock()
    mock_unit_ids_result.all.return_value = [(1,), (2,)]  # Trả về list các tuple ID

    # 2. Mock kết quả cho query select Major
    mock_majors_result_proxy = MagicMock()
    mock_majors_scalars = MagicMock()
    mock_majors_scalars.all.return_value = [mock_major_1]
    mock_majors_result_proxy.scalars.return_value = mock_majors_scalars

    # 3. Cấu hình side_effect cho execute
    mock_db_session.execute.side_effect = [
        mock_unit_ids_result,  # Lần gọi 1 (raw SQL)
        mock_majors_result_proxy,  # Lần gọi 2 (select Major)
    ]

    result = await organization_service.get_majors_by_unit_tree(
        mock_db_session, unit_id
    )

    assert mock_db_session.execute.await_count == 2
    # Kiểm tra query thứ 2 (select Major)
    second_call_args = mock_db_session.execute.await_args_list[1].args
    query_str = str(second_call_args[0])

    assert "major" in query_str
    assert "unit_id IN" in query_str
    assert "major.name ILIKE" not in query_str  # Không search

    # === SỬA LỖI 1 ===
    assert "LIMIT :param_1" in query_str  # Kiểm tra tham số LIMIT
    # === KẾT THÚC SỬA ===

    assert result == [mock_major_1]


@pytest.mark.asyncio
async def test_get_majors_by_unit_tree_with_search(mock_db_session, mock_major_1):
    """Test lấy major theo cây unit thành công (có search)."""
    unit_id = 1
    search_term = "Test"

    # 1. Mock kết quả cho query đệ quy (raw SQL)
    mock_unit_ids_result = MagicMock()
    mock_unit_ids_result.all.return_value = [(1,)]  # Chỉ unit 1

    # 2. Mock kết quả cho query select Major
    mock_majors_result_proxy = MagicMock()
    mock_majors_scalars = MagicMock()
    mock_majors_scalars.all.return_value = [mock_major_1]
    mock_majors_result_proxy.scalars.return_value = mock_majors_scalars

    # 3. Cấu hình side_effect
    mock_db_session.execute.side_effect = [
        mock_unit_ids_result,
        mock_majors_result_proxy,
    ]

    result = await organization_service.get_majors_by_unit_tree(
        mock_db_session, unit_id, search_term
    )

    assert mock_db_session.execute.await_count == 2
    # Kiểm tra query thứ 2
    second_call_args = mock_db_session.execute.await_args_list[1].args
    query_str = str(second_call_args[0])

    assert "unit_id IN" in query_str

    # === SỬA LỖI 1 ===
    # Kiểm tra logic ILIKE đã được dịch sang lower()
    assert "lower(major.name) LIKE lower(:name_1)" in query_str
    # === KẾT THÚC SỬA ===

    assert result == [mock_major_1]


@pytest.mark.asyncio
async def test_get_majors_by_unit_tree_no_unit_id(mock_db_session):
    """Test lấy major khi unit_id là None."""
    result = await organization_service.get_majors_by_unit_tree(mock_db_session, None)

    assert result == []
    mock_db_session.execute.assert_not_awaited()
