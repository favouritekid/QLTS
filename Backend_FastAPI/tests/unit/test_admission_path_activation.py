"""ADM-004 regression: ``validate_activation`` must enforce the same
readiness contract as ``get_coverage_matrix``.

Before the fix, ``validate_activation`` only checked status + quota and
left criteria/documents as "placeholder" comments. The route therefore
let admins activate paths that the coverage matrix flagged as not-ready.
Now both code paths agree:

- status in {draft, inactive}
- academic_info.annual_admission_quota > 0
- path.criteria_id is set
- a DocumentGroup resolves for offering_type + admission_method
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.admission_path_service import AdmissionPathService


pytestmark = pytest.mark.unit


def _make_path(
    *,
    status: str = "draft",
    quota: int = 100,
    criteria_id: int | None = 7,
    offering_type_id: int | None = 1,
    admission_method_id: int = 1,
):
    """Build an in-memory AdmissionPath stand-in with just the attrs the
    service touches. Avoids needing a DB session for unit tests."""
    offering = SimpleNamespace(offering_type_id=offering_type_id)
    academic_info = SimpleNamespace(
        annual_admission_quota=quota,
        offering=offering,
    )
    return SimpleNamespace(
        id=1,
        status=status,
        academic_info=academic_info,
        criteria_id=criteria_id,
        admission_method_id=admission_method_id,
    )


def _make_service(
    *,
    method_group: object | None = None,
    shared_groups: list | None = None,
):
    """Build an AdmissionPathService with a stub DocumentGroupRepository.

    The service constructs ``DocumentGroupRepository(self.db)`` lazily
    inside ``validate_activation``. We patch the import site so the stub
    is returned regardless of the db arg.
    """
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


class TestValidateActivation:
    async def test_ready_path_can_activate(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is True, errors
        assert errors == []

    async def test_active_status_blocks_activation(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path(status="active")

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("status" in e.lower() for e in errors)

    async def test_zero_quota_blocks_activation(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path(quota=0)

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("Quota" in e or "chỉ tiêu" in e.lower() for e in errors)

    async def test_missing_criteria_blocks_activation(self):
        service, doc_repo = _make_service(method_group=object())
        path = _make_path(criteria_id=None)

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("Criteria" in e or "tiêu chí" in e.lower() for e in errors)

    async def test_missing_documents_blocks_activation(self):
        # Neither method-specific nor shared groups exist
        service, doc_repo = _make_service(method_group=None, shared_groups=[])
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        assert any("Documents" in e or "hồ sơ" in e.lower() for e in errors)

    async def test_shared_documents_satisfy_requirement(self):
        # No method-specific group, but shared group exists
        service, doc_repo = _make_service(
            method_group=None, shared_groups=[object()]
        )
        path = _make_path()

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is True, errors

    async def test_all_missing_collects_all_errors(self):
        """validate_activation should accumulate every gap, not bail early."""
        service, doc_repo = _make_service(method_group=None, shared_groups=[])
        path = _make_path(quota=0, criteria_id=None)

        with _patch_doc_repo(doc_repo):
            can_activate, errors = await service.validate_activation(path)

        assert can_activate is False
        # Quota + criteria + documents — three independent gaps
        assert len(errors) >= 3
