"""ADM-008 regression: activate/deactivate admission path is admin-only.

Per Q3=a in the audit thread: Manager creates and edits draft paths but
cannot activate or deactivate — Admin "approves = activates". The
service-level gate is defense-in-depth; the route also guards via
``Depends(require_admin)``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.constants import UserRole
from app.services.admission_path_service import AdmissionPathService
from app.utils.exceptions import BusinessRuleViolation, PermissionDeniedError


pytestmark = pytest.mark.unit


def _make_service(*, method_group=object(), shared_groups=None):
    """Service stub with a patched DocumentGroupRepository so
    validate_activation can resolve documents without a real DB."""
    service = AdmissionPathService.__new__(AdmissionPathService)
    service.db = MagicMock()
    service.repo = MagicMock()

    # repo.update needs to return a path-shaped object; mirror the input
    async def _fake_update(path, data):
        for k, v in data.items():
            setattr(path, k, v)
        return path

    service.repo.update = AsyncMock(side_effect=_fake_update)

    doc_repo = MagicMock()
    doc_repo.get_method_specific_group = AsyncMock(return_value=method_group)
    doc_repo.get_shared_groups = AsyncMock(return_value=shared_groups or [])
    return service, doc_repo


def _patch_doc_repo(doc_repo):
    return patch(
        "app.repositories.document_group_repository.DocumentGroupRepository",
        return_value=doc_repo,
    )


def _ready_path(status: str = "draft"):
    """Build a fully-ready AdmissionPath stand-in so readiness validation
    inside ``activate_path`` won't trip — we want the role check to be
    the failure surface, not the readiness gate."""
    offering = SimpleNamespace(offering_type_id=1)
    academic_info = SimpleNamespace(
        annual_admission_quota=100,
        offering=offering,
    )
    return SimpleNamespace(
        id=42,
        status=status,
        academic_info=academic_info,
        criteria_id=7,
        admission_method_id=1,
    )


def _user(role: UserRole):
    return SimpleNamespace(id=1, role=role)


class TestActivatePathAdminOnly:
    async def test_manager_cannot_activate(self):
        service, doc_repo = _make_service()
        with _patch_doc_repo(doc_repo):
            with pytest.raises(PermissionDeniedError, match="admin"):
                await service.activate_path(
                    _ready_path("draft"), _user(UserRole.MANAGER)
                )

    @pytest.mark.parametrize(
        "role",
        [UserRole.OFFICER, UserRole.ACCOUNTANT, UserRole.USER],
    )
    async def test_non_admin_cannot_activate(self, role):
        service, doc_repo = _make_service()
        with _patch_doc_repo(doc_repo):
            with pytest.raises(PermissionDeniedError, match="admin"):
                await service.activate_path(_ready_path("draft"), _user(role))

    async def test_admin_can_activate_ready_path(self):
        service, doc_repo = _make_service()
        path = _ready_path("draft")
        with _patch_doc_repo(doc_repo):
            updated, _cb = await service.activate_path(
                path, _user(UserRole.ADMIN)
            )
        assert updated.status == "active"
        assert updated.activated_by == 1

    async def test_cannot_activate_archived_path(self):
        """``archived`` is terminal: re-activation rejected by the early
        guard (before readiness/round-lock), so the terminal contract holds
        even though ``archived`` is now reachable via the archive endpoint."""
        service, doc_repo = _make_service()
        with _patch_doc_repo(doc_repo):
            with pytest.raises(BusinessRuleViolation, match="lưu trữ"):
                await service.activate_path(
                    _ready_path("archived"), _user(UserRole.ADMIN)
                )


class TestDeactivatePathAdminOnly:
    async def test_manager_cannot_deactivate(self):
        service, _doc_repo = _make_service()
        with pytest.raises(PermissionDeniedError, match="admin"):
            await service.deactivate_path(
                _ready_path("active"), _user(UserRole.MANAGER)
            )

    @pytest.mark.parametrize(
        "role",
        [UserRole.OFFICER, UserRole.ACCOUNTANT, UserRole.USER],
    )
    async def test_non_admin_cannot_deactivate(self, role):
        service, _doc_repo = _make_service()
        with pytest.raises(PermissionDeniedError, match="admin"):
            await service.deactivate_path(_ready_path("active"), _user(role))

    async def test_admin_can_deactivate_active_path(self):
        service, _doc_repo = _make_service()
        path = _ready_path("active")
        updated, _cb = await service.deactivate_path(
            path, _user(UserRole.ADMIN)
        )
        assert updated.status == "inactive"

    async def test_role_check_runs_before_status_check(self):
        """Manager hitting deactivate on a non-active path must still
        get PermissionDeniedError — the role gate is the first thing
        evaluated, otherwise we'd leak that the path is in a wrong
        state to a caller who shouldn't have reached the route."""
        service, _doc_repo = _make_service()
        with pytest.raises(PermissionDeniedError, match="admin"):
            await service.deactivate_path(
                _ready_path("draft"), _user(UserRole.MANAGER)
            )


class TestArchivePathAdminOnly:
    """Archive (draft/inactive → archived) is admin-only, symmetric to
    activate/deactivate. Wires the previously-unexposed ``archive_path``
    service so admin can retire unused draft/inactive paths via API/UI
    instead of raw SQL."""

    async def test_manager_cannot_archive(self):
        service, _doc_repo = _make_service()
        with pytest.raises(PermissionDeniedError, match="admin"):
            await service.archive_path(
                _ready_path("draft"), _user(UserRole.MANAGER)
            )

    @pytest.mark.parametrize(
        "role",
        [UserRole.OFFICER, UserRole.ACCOUNTANT, UserRole.USER],
    )
    async def test_non_admin_cannot_archive(self, role):
        service, _doc_repo = _make_service()
        with pytest.raises(PermissionDeniedError, match="admin"):
            await service.archive_path(_ready_path("draft"), _user(role))

    async def test_admin_can_archive_draft(self):
        service, _doc_repo = _make_service()
        path = _ready_path("draft")
        updated, _cb = await service.archive_path(path, _user(UserRole.ADMIN))
        assert updated.status == "archived"

    async def test_admin_can_archive_inactive(self):
        service, _doc_repo = _make_service()
        path = _ready_path("inactive")
        updated, _cb = await service.archive_path(path, _user(UserRole.ADMIN))
        assert updated.status == "archived"

    async def test_cannot_archive_active_path(self):
        """Active must be deactivated first (archived is terminal)."""
        service, _doc_repo = _make_service()
        with pytest.raises(BusinessRuleViolation, match="[Dd]eactivate"):
            await service.archive_path(
                _ready_path("active"), _user(UserRole.ADMIN)
            )

    async def test_cannot_archive_already_archived(self):
        service, _doc_repo = _make_service()
        with pytest.raises(BusinessRuleViolation, match="already archived"):
            await service.archive_path(
                _ready_path("archived"), _user(UserRole.ADMIN)
            )

    async def test_role_check_runs_before_status_check(self):
        """Manager hitting archive on an active path still gets
        PermissionDeniedError (role gate first), not a state-leak."""
        service, _doc_repo = _make_service()
        with pytest.raises(PermissionDeniedError, match="admin"):
            await service.archive_path(
                _ready_path("active"), _user(UserRole.MANAGER)
            )
