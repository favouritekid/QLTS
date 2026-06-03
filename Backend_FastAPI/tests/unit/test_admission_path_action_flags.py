"""ADM-021: AdmissionPath response action flags are role-aware.

The frontend must render from backend ``available_actions`` / ``can_*``
fields rather than guessing from ``user.role``. These tests pin the backend
contract after ADM-008 made activate/deactivate admin-only.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constants import UserRole
from app.services.admission_path_service import AdmissionPathService


pytestmark = pytest.mark.unit


def _make_service(*, method_group=object(), shared_groups=None):
    service = AdmissionPathService.__new__(AdmissionPathService)
    service.db = MagicMock()
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
