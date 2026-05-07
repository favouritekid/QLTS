"""Service invariant tests for the phase1_06 DocumentGroup
``admission_path_id`` field (#184 Wave 1 PR-1C').

PLAN line 2671-2682 contract — when admin creates / updates a
DocumentGroup with ``admission_path_id`` set, the service must
validate:

* ``DocumentGroup.offering_type_id == path.academic_info.offering.offering_type_id``
* ``DocumentGroup.admission_method_id`` is None OR equals
  ``path.admission_method_id``

Mismatch → ``BusinessRuleViolation``. Reason: the 3-tier
resolution rule chooses path-level groups BEFORE checking
offering_type / method, so an inconsistent group would silently
leak into a profile that doesn't match the path's offering.

This file locks the invariant on both create + update paths,
plus the path-NULL passthrough (legacy method/shared groups
keep working unchanged).

What does NOT live here:
* Migration shape — see ``test_phase1_05_06_revision_chain.py``.
* 3-tier resolution rule (which tier wins) — see
  ``test_admission_path_resolution_3tier.py``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.document_group import (
    DocumentGroupCreate,
    DocumentGroupUpdate,
)
from app.services.document_group_service import (
    DocumentGroupService,
    _validate_path_invariant,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    ResourceNotFoundError,
)


pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


def _path(*, path_id=42, offering_type_id=1, admission_method_id=10):
    """Path stub with eager-loaded academic_info → offering chain so
    ``_validate_path_invariant`` can read offering_type without a
    real DB."""
    offering = SimpleNamespace(offering_type_id=offering_type_id)
    academic_info = SimpleNamespace(offering=offering)
    return SimpleNamespace(
        id=path_id,
        admission_method_id=admission_method_id,
        academic_info=academic_info,
    )


def _make_db_with_path(path):
    """AsyncSession stub whose ``execute`` returns ``path`` from
    ``scalars().first()``."""
    db = MagicMock()

    async def _execute(query):
        result = MagicMock()
        scalars = MagicMock()
        scalars.first = MagicMock(return_value=path)
        result.scalars = MagicMock(return_value=scalars)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_db_with_no_path():
    db = MagicMock()

    async def _execute(query):
        result = MagicMock()
        scalars = MagicMock()
        scalars.first = MagicMock(return_value=None)
        result.scalars = MagicMock(return_value=scalars)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_service(db):
    """Construct a DocumentGroupService with a stubbed repo."""
    service = DocumentGroupService.__new__(DocumentGroupService)
    service.db = db

    repo = MagicMock()
    repo.get_by_code = AsyncMock(return_value=None)
    repo.create_group = AsyncMock(side_effect=lambda **kwargs: SimpleNamespace(
        id=1, **kwargs
    ))

    async def _fake_update(group, **updates):
        for k, v in updates.items():
            setattr(group, k, v)
        return group

    repo.update_group = AsyncMock(side_effect=_fake_update)
    repo.add_item_to_group = AsyncMock()
    service.repo = repo
    return service


def _user():
    return SimpleNamespace(id=1, role="admin")


# =============================================================================
# 1. _validate_path_invariant — direct unit tests
# =============================================================================


class TestValidatePathInvariant:
    @pytest.mark.asyncio
    async def test_matches_offering_and_method_passes(self):
        path = _path(offering_type_id=5, admission_method_id=10)
        db = _make_db_with_path(path)
        # No raise — invariant satisfied.
        await _validate_path_invariant(
            db,
            admission_path_id=42,
            offering_type_id=5,
            admission_method_id=10,
        )

    @pytest.mark.asyncio
    async def test_method_null_with_matching_offering_passes(self):
        """DocumentGroup with method=NULL is the "applies to any
        method" semantic. PR-1C' spec allows this — invariant
        only blocks mismatched non-null methods."""
        path = _path(offering_type_id=5, admission_method_id=10)
        db = _make_db_with_path(path)
        await _validate_path_invariant(
            db,
            admission_path_id=42,
            offering_type_id=5,
            admission_method_id=None,
        )

    @pytest.mark.asyncio
    async def test_offering_type_drift_raises(self):
        path = _path(offering_type_id=5, admission_method_id=10)
        db = _make_db_with_path(path)
        with pytest.raises(BusinessRuleViolation, match="offering_type"):
            await _validate_path_invariant(
                db,
                admission_path_id=42,
                offering_type_id=99,
                admission_method_id=10,
            )

    @pytest.mark.asyncio
    async def test_method_drift_raises(self):
        path = _path(offering_type_id=5, admission_method_id=10)
        db = _make_db_with_path(path)
        with pytest.raises(BusinessRuleViolation, match="method"):
            await _validate_path_invariant(
                db,
                admission_path_id=42,
                offering_type_id=5,
                admission_method_id=99,
            )

    @pytest.mark.asyncio
    async def test_path_not_found_raises_resource_not_found(self):
        db = _make_db_with_no_path()
        with pytest.raises(ResourceNotFoundError, match="AdmissionPath"):
            await _validate_path_invariant(
                db,
                admission_path_id=42,
                offering_type_id=5,
                admission_method_id=10,
            )


# =============================================================================
# 2. create_group — invariant integration
# =============================================================================


class TestCreateGroupPathInvariant:
    @pytest.mark.asyncio
    async def test_create_with_matching_path_persists(self):
        path = _path(offering_type_id=5, admission_method_id=10)
        service = _make_service(_make_db_with_path(path))

        data = DocumentGroupCreate.model_validate(
            {
                "offering_type_id": 5,
                "admission_method_id": 10,
                "admission_path_id": 42,
                "code": "HS_PATH_42",
                "name": "Hồ sơ path 42",
            }
        )
        group, _ = await service.create_group(data, _user())
        assert group.admission_path_id == 42
        # Repo received the path id.
        service.repo.create_group.assert_called_once()
        kwargs = service.repo.create_group.call_args.kwargs
        assert kwargs["admission_path_id"] == 42

    @pytest.mark.asyncio
    async def test_create_with_offering_drift_raises(self):
        path = _path(offering_type_id=5, admission_method_id=10)
        service = _make_service(_make_db_with_path(path))

        data = DocumentGroupCreate.model_validate(
            {
                "offering_type_id": 99,  # drift
                "admission_method_id": 10,
                "admission_path_id": 42,
                "code": "HS_DRIFT",
                "name": "Lệch offering",
            }
        )
        with pytest.raises(BusinessRuleViolation, match="offering_type"):
            await service.create_group(data, _user())
        # Repo never reached because invariant failed first.
        service.repo.create_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_with_path_null_skips_invariant(self):
        """Legacy method/shared groups (path NULL) MUST keep working
        without the invariant query. Otherwise PR-1C' would break
        every existing legacy create path."""
        # No path → no validation; the db.execute should never run.
        db = MagicMock()
        db.execute = AsyncMock()
        service = _make_service(db)

        data = DocumentGroupCreate.model_validate(
            {
                "offering_type_id": 5,
                "admission_method_id": 10,
                "code": "HS_LEGACY_METHOD",
                "name": "Legacy method-specific",
            }
        )
        group, _ = await service.create_group(data, _user())
        assert group.admission_path_id is None
        db.execute.assert_not_awaited()


# =============================================================================
# 3. update_group — invariant on path re-target
# =============================================================================


def _existing_group(*, group_id=7, offering_type_id=5, admission_method_id=10,
                    admission_path_id=None):
    """Stand-in for an already-persisted DocumentGroup row that
    update_group operates on."""
    return SimpleNamespace(
        id=group_id,
        offering_type_id=offering_type_id,
        admission_method_id=admission_method_id,
        admission_path_id=admission_path_id,
        name="Existing",
        description=None,
        is_active=True,
    )


class TestUpdateGroupPathInvariant:
    @pytest.mark.asyncio
    async def test_update_re_target_to_matching_path_persists(self):
        path = _path(path_id=42, offering_type_id=5, admission_method_id=10)
        service = _make_service(_make_db_with_path(path))
        group = _existing_group(offering_type_id=5, admission_method_id=10)

        data = DocumentGroupUpdate.model_validate({"admission_path_id": 42})
        updated, _ = await service.update_group(group, data, _user())
        assert updated.admission_path_id == 42

    @pytest.mark.asyncio
    async def test_update_clear_path_to_null_skips_invariant(self):
        """Admin can clear the path FK back to NULL (= fall back to
        method/shared tier). No invariant query needed because the
        target state has no path constraint."""
        db = MagicMock()
        db.execute = AsyncMock()
        service = _make_service(db)
        group = _existing_group(admission_path_id=42)

        data = DocumentGroupUpdate.model_validate({"admission_path_id": None})
        updated, _ = await service.update_group(group, data, _user())
        assert updated.admission_path_id is None
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_re_target_to_drifted_path_raises(self):
        path = _path(offering_type_id=99, admission_method_id=10)
        service = _make_service(_make_db_with_path(path))
        group = _existing_group(offering_type_id=5, admission_method_id=10)

        data = DocumentGroupUpdate.model_validate({"admission_path_id": 42})
        with pytest.raises(BusinessRuleViolation, match="offering_type"):
            await service.update_group(group, data, _user())
        # Repo update never ran because invariant failed first.
        service.repo.update_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_omitted_path_key_left_unchanged(self):
        """exclude_unset semantic — admin omitting the key means
        "leave path unchanged"; invariant must not run."""
        db = MagicMock()
        db.execute = AsyncMock()
        service = _make_service(db)
        group = _existing_group(admission_path_id=42)

        data = DocumentGroupUpdate.model_validate({"name": "Renamed"})
        updated, _ = await service.update_group(group, data, _user())
        # Path unchanged because the key wasn't in the payload.
        assert updated.admission_path_id == 42
        assert updated.name == "Renamed"
        db.execute.assert_not_awaited()
