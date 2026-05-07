"""Governance regression tests for the phase1_03 admin-only fields
on ``AdmissionPathService.create_path`` / ``update_path``
(#184 Wave 1 PR-1B'-FE / BE micro-patch).

Codex P1 catch on PR-1B'-FE pre-commit review: backend service
``create_path`` was silently dropping the 3 new fields
(``applicable_to`` / ``method_quota`` / ``bonus_rule_override``)
and the governance guard only covered ``minor_correction_allowed_fields``.
The result was admin filling the new audience filter / quota /
bonus override on the wizard, hitting "Tạo & Tiếp tục", and the
DB row staying NULL — a particularly bad failure mode because
the FE toast says "Tạo đợt tuyển sinh thành công".

This file locks the contract:

* Admin **can** create a path with all 3 new fields populated
  → fields persist verbatim (post Pydantic validation).
* Manager **cannot** set the 3 new fields on create or update
  → ``BusinessRuleViolation`` raised; FE form / API caller
  surfaces the failure rather than silent-drop.
* The existing ``minor_correction_allowed_fields`` guard still
  works (no regression from the broader rewrite).

What does NOT live here:
* Pydantic shape (``BonusRuleOverride`` 3-field structure, range
  guards, ENUM literal) — see ``test_admission_path_schema_bonus_rule_override.py``.
* Repository ``@>`` / ``&&`` operator contract — see
  ``test_admission_path_repository_audience.py``.
* Migration revision chain + ENUM type creation — see
  ``test_phase1_03_revision_chain.py``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.constants import UserRole
from app.schemas.admission_path import (
    AdmissionPathCreate,
    AdmissionPathUpdate,
    BonusRuleOverride,
)
from app.services.admission_path_service import AdmissionPathService
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.unit


def _user(role: UserRole):
    return SimpleNamespace(id=1, role=role, full_name="Test User")


def _make_service():
    """Service stub with mocked repo. Both ``create`` and ``update``
    echo their input back as the resulting path so we can inspect
    the persisted column dict."""
    service = AdmissionPathService.__new__(AdmissionPathService)
    service.db = MagicMock()
    service.repo = MagicMock()
    service.repo.get_path_by_offering_and_method = AsyncMock(return_value=None)

    persisted: dict = {}

    async def _fake_create(data: dict):
        # Capture the arg for assertion + return a path-shaped object
        # so the caller can also inspect it via the return value.
        persisted.update(data)
        return SimpleNamespace(id=1, **data)

    async def _fake_update(path, data: dict):
        # Update path attrs in-place, capture into ``persisted`` for
        # assertion. Mirrors ``_fake_update`` shape used elsewhere.
        for k, v in data.items():
            setattr(path, k, v)
        persisted.clear()
        persisted.update(data)
        return path

    service.repo.create = AsyncMock(side_effect=_fake_create)
    service.repo.update = AsyncMock(side_effect=_fake_update)
    return service, persisted


# =============================================================================
# create_path — admin happy path (3 fields persist verbatim)
# =============================================================================


def _admin_create_payload(**overrides) -> AdmissionPathCreate:
    base = {
        "academic_info_id": 1,
        "admission_method_id": 1,
        "applicable_to": ["POST_THPT", "LIEN_THONG_TC"],
        "method_quota": 50,
        "bonus_rule_override": {
            "apply_area_bonus": True,
            "apply_subject_bonus": False,
            "max_total_bonus": 2.5,
        },
    }
    base.update(overrides)
    return AdmissionPathCreate.model_validate(base)


class TestCreatePathAdminCanSetGovernance:
    async def test_admin_create_persists_applicable_to(self):
        service, persisted = _make_service()
        path, _cb = await service.create_path(
            _admin_create_payload(), _user(UserRole.ADMIN)
        )
        assert persisted["applicable_to"] == ["POST_THPT", "LIEN_THONG_TC"]
        assert path.applicable_to == ["POST_THPT", "LIEN_THONG_TC"]

    async def test_admin_create_persists_method_quota(self):
        service, persisted = _make_service()
        path, _cb = await service.create_path(
            _admin_create_payload(method_quota=42), _user(UserRole.ADMIN)
        )
        assert persisted["method_quota"] == 42
        assert path.method_quota == 42

    async def test_admin_create_persists_bonus_rule_override_as_dict(self):
        service, persisted = _make_service()
        path, _cb = await service.create_path(
            _admin_create_payload(), _user(UserRole.ADMIN)
        )
        # Persist as plain dict so the JSONB column accepts it; caller
        # never sees a raw Pydantic instance on the model attribute.
        assert persisted["bonus_rule_override"] == {
            "apply_area_bonus": True,
            "apply_subject_bonus": False,
            "max_total_bonus": 2.5,
        }
        assert isinstance(path.bonus_rule_override, dict)

    async def test_admin_create_with_all_governance_fields_null_persists_null(self):
        # Admin choosing to leave the 3 fields empty (= legacy / no
        # cap / inherit method bonus default) — must persist as NULL,
        # not silently coerce to defaults.
        service, persisted = _make_service()
        payload = AdmissionPathCreate.model_validate(
            {
                "academic_info_id": 1,
                "admission_method_id": 1,
            }
        )
        await service.create_path(payload, _user(UserRole.ADMIN))
        assert persisted["applicable_to"] is None
        assert persisted["method_quota"] is None
        assert persisted["bonus_rule_override"] is None


# =============================================================================
# create_path — manager governance guard (BusinessRuleViolation)
# =============================================================================


class TestCreatePathManagerGovernanceGuard:
    @pytest.mark.parametrize(
        "field_kwarg",
        [
            ({"applicable_to": ["POST_THPT"]}),
            ({"method_quota": 50}),
            (
                {
                    "bonus_rule_override": {
                        "apply_area_bonus": True,
                        "apply_subject_bonus": False,
                    }
                }
            ),
        ],
        ids=["applicable_to", "method_quota", "bonus_rule_override"],
    )
    async def test_manager_cannot_set_phase1_03_field_on_create(self, field_kwarg):
        service, _ = _make_service()
        payload = AdmissionPathCreate.model_validate(
            {
                "academic_info_id": 1,
                "admission_method_id": 1,
                **field_kwarg,
            }
        )
        with pytest.raises(BusinessRuleViolation, match="Chỉ admin"):
            await service.create_path(payload, _user(UserRole.MANAGER))

    async def test_manager_existing_minor_correction_guard_still_works(self):
        # Regression check: the existing minor_correction_allowed_fields
        # guard must still raise for managers — the broader rewrite
        # didn't accidentally drop it.
        service, _ = _make_service()
        payload = AdmissionPathCreate.model_validate(
            {
                "academic_info_id": 1,
                "admission_method_id": 1,
                "minor_correction_allowed_fields": ["gender"],
            }
        )
        with pytest.raises(BusinessRuleViolation, match="Chỉ admin"):
            await service.create_path(payload, _user(UserRole.MANAGER))

    async def test_manager_can_create_path_with_no_governance_fields(self):
        # Sanity — manager creating a vanilla draft path should still
        # work; the guard fires only when governance fields are touched.
        service, _ = _make_service()
        payload = AdmissionPathCreate.model_validate(
            {
                "academic_info_id": 1,
                "admission_method_id": 1,
                "display_name": "Manager-created draft",
            }
        )
        path, _cb = await service.create_path(payload, _user(UserRole.MANAGER))
        assert path.display_name == "Manager-created draft"


# =============================================================================
# update_path — manager governance guard (BusinessRuleViolation)
# =============================================================================


def _draft_path():
    """Path stub passing the lifecycle guard (manager can edit draft)."""
    return SimpleNamespace(
        id=1,
        status="draft",
        academic_info_id=1,
        admission_method_id=1,
        applicable_to=None,
        method_quota=None,
        bonus_rule_override=None,
    )


class TestUpdatePathManagerGovernanceGuard:
    @pytest.mark.parametrize(
        "update_kwarg",
        [
            ({"applicable_to": ["POST_THPT"]}),
            ({"method_quota": 50}),
            (
                {
                    "bonus_rule_override": {
                        "apply_area_bonus": True,
                        "apply_subject_bonus": False,
                    }
                }
            ),
            ({"minor_correction_allowed_fields": ["gender"]}),
        ],
        ids=[
            "applicable_to",
            "method_quota",
            "bonus_rule_override",
            "minor_correction_allowed_fields_existing_regression",
        ],
    )
    async def test_manager_cannot_update_governance_field(self, update_kwarg):
        service, _ = _make_service()
        path = _draft_path()
        update = AdmissionPathUpdate.model_validate(update_kwarg)
        with pytest.raises(BusinessRuleViolation, match="Chỉ admin"):
            await service.update_path(path, update, _user(UserRole.MANAGER))

    async def test_manager_can_update_non_governance_fields(self):
        # Display name / order / fee are still freely editable by
        # manager on draft paths — only the 4 governance fields gate.
        service, persisted = _make_service()
        path = _draft_path()
        update = AdmissionPathUpdate.model_validate(
            {
                "display_name": "Manager-edited draft",
                "display_order": 5,
            }
        )
        result, _cb = await service.update_path(
            path, update, _user(UserRole.MANAGER)
        )
        assert persisted["display_name"] == "Manager-edited draft"
        assert persisted["display_order"] == 5
        assert result.display_name == "Manager-edited draft"


# =============================================================================
# update_path — admin happy path persists 3 new fields correctly
# =============================================================================


class TestUpdatePathAdminPersistsPhase1_03Fields:
    async def test_admin_update_applicable_to_persists_as_list(self):
        service, persisted = _make_service()
        path = _draft_path()
        update = AdmissionPathUpdate.model_validate(
            {"applicable_to": ["POST_THPT", "VLVH"]}
        )
        await service.update_path(path, update, _user(UserRole.ADMIN))
        assert persisted["applicable_to"] == ["POST_THPT", "VLVH"]

    async def test_admin_update_bonus_rule_override_persists_as_dict(self):
        # Pydantic shape becomes a plain dict for JSONB column.
        service, persisted = _make_service()
        path = _draft_path()
        update = AdmissionPathUpdate.model_validate(
            {
                "bonus_rule_override": {
                    "apply_area_bonus": False,
                    "apply_subject_bonus": True,
                    "max_total_bonus": 1.0,
                }
            }
        )
        await service.update_path(path, update, _user(UserRole.ADMIN))
        assert persisted["bonus_rule_override"] == {
            "apply_area_bonus": False,
            "apply_subject_bonus": True,
            "max_total_bonus": 1.0,
        }

    async def test_admin_update_clear_field_to_null(self):
        # Admin passes ``null`` (= clear the override and inherit
        # method default). The ``exclude_unset=True`` semantic means
        # the key reaches ``update_data`` only if the admin explicitly
        # sent ``null``; unset → key absent → field unchanged.
        service, persisted = _make_service()
        path = _draft_path()
        path.bonus_rule_override = {
            "apply_area_bonus": True,
            "apply_subject_bonus": True,
            "max_total_bonus": None,
        }
        update = AdmissionPathUpdate.model_validate(
            {"bonus_rule_override": None}
        )
        await service.update_path(path, update, _user(UserRole.ADMIN))
        assert persisted["bonus_rule_override"] is None

    async def test_admin_update_omitted_field_left_unchanged(self):
        # Key NOT in the update payload → ``model_dump(exclude_unset=
        # True)`` drops it → repo.update receives a dict without the
        # key → DB column stays unchanged.
        service, persisted = _make_service()
        path = _draft_path()
        path.applicable_to = ["POST_THPT"]
        update = AdmissionPathUpdate.model_validate(
            {"display_name": "Touch only the name"}
        )
        await service.update_path(path, update, _user(UserRole.ADMIN))
        assert "applicable_to" not in persisted
        # path.applicable_to was NOT touched (still the original).
        assert path.applicable_to == ["POST_THPT"]
