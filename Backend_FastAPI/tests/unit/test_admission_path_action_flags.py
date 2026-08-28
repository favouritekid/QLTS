"""ADM-021: AdmissionPath response action flags are role-aware.

The frontend must render from backend ``available_actions`` / ``can_*``
fields rather than guessing from ``user.role``. These tests pin the backend
contract after ADM-008 made activate/deactivate admin-only.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession


import pytest

from app.core.constants import UserRole
from app.services.admission_path_service import AdmissionPathService


# Sentinel phân biệt "không truyền" với "truyền rõ None". Xem `_stub_db`.
_KHONG_TRUYEN = object()


def _round(*, round_id: int = 11, is_active: bool = True, archived_at=None):
    """Đợt tuyển sinh giả — chỉ bốn trường mà ``validate_activation`` đọc.

    ``validate_activation`` Check 1b lấy đợt qua ``db.get`` rồi soi
    ``archived_at`` và ``is_active``; ``activate_path`` khoá lại đợt qua
    ``db.execute(...).scalar_one_or_none()`` và soi cùng hai trường ấy, cộng
    ``round_code`` để dựng thông báo lỗi.
    """
    return SimpleNamespace(
        id=round_id,
        round_code="DOT_1",
        is_active=is_active,
        archived_at=archived_at,
    )


def _stub_db(active_round=_KHONG_TRUYEN):
    """Session giả GIỮ ĐÚNG ranh giới async/sync của ``AsyncSession``.

    ``spec=AsyncSession`` là phần quan trọng: một lời gọi sai contract sẽ nổ
    thay vì bị mock nuốt. KHÔNG dùng ``AsyncMock()`` cho cả session —
    ``AsyncSession`` có cả method async lẫn sync, nên mock async nguyên khối
    làm lệch contract và che lỗi mới.

    ``db.get`` phục vụ ``validate_activation`` Check 1b.
    ``db.execute(...).scalar_one_or_none()`` phục vụ khoá đợt trong
    ``activate_path`` — thiếu nó thì ca kích hoạt đỏ ở ``scalar_one_or_none``,
    một root khác bị che sau root ``db.get``.

    Mặc định (``active_round=_KHONG_TRUYEN``) dựng một đợt đang hoạt động.
    Truyền RÕ ``active_round=None`` thì ``db.get`` và ``scalar_one_or_none``
    cùng trả ``None`` — mô phỏng "đợt không tìm thấy".

    Phải dùng sentinel chứ không dùng ``None`` làm mặc định: nếu mặc định là
    ``None`` rồi thân hàm đổi nó thành đợt hoạt động, thì lời truyền ``None``
    tường minh bị nuốt và trạng thái mà docstring hứa KHÔNG dựng được — chú
    thích nói một đằng, mã làm một nẻo.

    ⚠️ "Đợt không tìm thấy" là LỖ COVERAGE của fixture, KHÔNG phải trạng thái
    dựng được trên CSDL thật: cột ``admission_round_id`` là NOT NULL, FK dùng
    ON DELETE RESTRICT, và ``activate_path`` từ chối tường minh khi khoá lại
    không thấy đợt.
    """
    if active_round is _KHONG_TRUYEN:
        active_round = _round()
    db = MagicMock(spec=AsyncSession)
    db.get = AsyncMock(return_value=active_round)
    locked_result = MagicMock()
    locked_result.scalar_one_or_none.return_value = active_round
    db.execute = AsyncMock(return_value=locked_result)
    return db


pytestmark = pytest.mark.unit


def _make_service(
    *,
    method_group=object(),
    shared_groups=None,
    active_round=_KHONG_TRUYEN,
):
    service = AdmissionPathService.__new__(AdmissionPathService)
    service.db = _stub_db(active_round)
    service.repo = MagicMock()

    doc_repo = MagicMock()
    doc_repo.get_method_specific_group = AsyncMock(return_value=method_group)
    doc_repo.get_shared_groups = AsyncMock(return_value=shared_groups or [])
    return service, doc_repo


def _patch_doc_repo(doc_repo):
    return patch(
        "app.repositories.document_group_repository.DocumentGroupRepository",
        return_value=doc_repo,
    )


def _path(status: str = "draft", *, ready: bool = True):
    offering = SimpleNamespace(offering_type_id=1)
    academic_info = SimpleNamespace(
        annual_admission_quota=100 if ready else 0,
        offering=offering,
    )
    return SimpleNamespace(
        id=42,
        status=status,
        academic_info=academic_info,
        criteria_id=7 if ready else None,
        admission_method_id=1,
        # Xem chú thích ở `_round`: cột thật NOT NULL, schema khai bắt buộc.
        admission_round_id=11,
    )


def _user(role: UserRole):
    return SimpleNamespace(id=1, role=role)


class TestAdmissionPathRoleAwareActionFlags:
    async def test_admin_draft_ready_can_edit_and_activate(self):
        service, doc_repo = _make_service()
        path = _path("draft")
        admin = _user(UserRole.ADMIN)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, admin) == [
                "save",
                "activate",
                "archive",
            ]
            assert service.compute_can_edit(path, admin) is True
            assert await service.compute_can_activate(path, admin) is True

    async def test_admin_active_can_edit_and_deactivate_only(self):
        service, doc_repo = _make_service()
        path = _path("active")
        admin = _user(UserRole.ADMIN)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, admin) == [
                "save",
                "deactivate",
            ]
            assert service.compute_can_edit(path, admin) is True
            assert await service.compute_can_activate(path, admin) is False

    async def test_admin_inactive_lists_activate_and_archive(self):
        """inactive (như draft) cho admin cả activate + archive — pin để
        nút 'Lưu trữ' FE (canPerformAction archive) không regress thầm lặng
        khi path ở trạng thái inactive, không chỉ draft."""
        service, doc_repo = _make_service()
        path = _path("inactive")
        admin = _user(UserRole.ADMIN)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, admin) == [
                "save",
                "activate",
                "archive",
            ]
            assert service.compute_can_edit(path, admin) is True

    async def test_admin_archived_has_no_actions(self):
        service, doc_repo = _make_service()
        path = _path("archived")
        admin = _user(UserRole.ADMIN)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, admin) == []
            assert service.compute_can_edit(path, admin) is False
            assert await service.compute_can_activate(path, admin) is False

    async def test_admin_draft_not_ready_lists_activate_but_cannot_activate(self):
        """The action list expresses lifecycle intent; ``can_activate`` pins
        readiness and is what the UI uses to enable the activate button."""
        service, doc_repo = _make_service()
        path = _path("draft", ready=False)
        admin = _user(UserRole.ADMIN)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, admin) == [
                "save",
                "activate",
                "archive",
            ]
            assert service.compute_can_edit(path, admin) is True
            assert await service.compute_can_activate(path, admin) is False

    async def test_manager_draft_can_save_but_not_activate(self):
        service, doc_repo = _make_service()
        path = _path("draft")
        manager = _user(UserRole.MANAGER)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, manager) == ["save"]
            assert service.compute_can_edit(path, manager) is True
            assert await service.compute_can_activate(path, manager) is False

    @pytest.mark.parametrize("status", ["active", "inactive"])
    async def test_manager_non_draft_has_no_lifecycle_actions(self, status):
        service, doc_repo = _make_service()
        path = _path(status)
        manager = _user(UserRole.MANAGER)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, manager) == []
            assert service.compute_can_edit(path, manager) is False
            assert await service.compute_can_activate(path, manager) is False

    async def test_non_config_role_gets_no_path_actions(self):
        service, doc_repo = _make_service()
        path = _path("active")
        officer = _user(UserRole.OFFICER)

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path, officer) == []
            assert service.compute_can_edit(path, officer) is False
            assert await service.compute_can_activate(path, officer) is False

    async def test_no_user_defaults_fail_closed(self):
        service, doc_repo = _make_service()
        path = _path("draft")

        with _patch_doc_repo(doc_repo):
            assert service.compute_available_actions(path) == []
            assert service.compute_can_edit(path) is False
            assert await service.compute_can_activate(path) is False
