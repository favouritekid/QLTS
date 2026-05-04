"""Admin-only governance tests for ``SystemConfigService.update``
(#184 Wave 1 PR-1D / phase1_13).

Q10 governance — only admin can mutate runtime config rows.
Manager / officer / accountant / user submitting PATCH must get
``BusinessRuleViolation`` (translated to 403 by router). Read
path (``list_all`` / ``get_by_key`` / ``get_value``) is permissive
because FE storefront needs it during anonymous flows.

What lives here:
* Admin happy path — value + description persist + audit fields set.
* Manager / officer / accountant / user blocked.
* Read path permissive — every role can read.
* Key-not-found → ResourceNotFoundError on update + get_by_key.
* ``get_value`` fallback contract (returns default when absent).

What does NOT live here:
* Migration shape — see ``test_phase1_07b_08_13_revision_chain.py``.
* Router-level audit row write — covered indirectly via the router
  using activity_service which has its own tests.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.constants import UserRole
from app.models.system_config import SystemConfig
from app.schemas.system_config import SystemConfigUpdate
from app.services.system_config_service import SystemConfigService
from app.utils.exceptions import (
    BusinessRuleViolation,
    ResourceNotFoundError,
)


pytestmark = pytest.mark.unit


def _user(role: UserRole, *, user_id: int = 1):
    return SimpleNamespace(id=user_id, role=role, full_name="Test User")


def _existing_row(key: str = "current_intake_year", value=2026):
    """SystemConfig row stand-in with the columns the service touches."""
    return SimpleNamespace(
        key=key,
        value=value,
        description="Năm tuyển sinh hiện tại",
        updated_at=None,
        updated_by_user_id=None,
    )


def _make_service(*, row=None):
    """Service stub — db.execute returns ``row`` from ``scalars().first()``."""
    db = MagicMock()
    db.flush = AsyncMock()

    async def _execute(query):
        result = MagicMock()
        scalars = MagicMock()
        scalars.first = MagicMock(return_value=row)
        scalars.all = MagicMock(return_value=[row] if row is not None else [])
        result.scalars = MagicMock(return_value=scalars)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    service = SystemConfigService(db)
    return service, db


# ---------------------------------------------------------------------------
# 1. Admin happy path
# ---------------------------------------------------------------------------


class TestAdminUpdate:
    @pytest.mark.asyncio
    async def test_admin_updates_value_and_description(self):
        row = _existing_row(value=2026)
        service, db = _make_service(row=row)

        update = SystemConfigUpdate.model_validate(
            {"value": 2027, "description": "Năm 2027"}
        )
        updated, cb = await service.update(
            "current_intake_year", update, _user(UserRole.ADMIN, user_id=42)
        )

        assert updated.value == 2027
        assert updated.description == "Năm 2027"
        assert updated.updated_by_user_id == 42
        # Service flushes; router commits.
        db.flush.assert_awaited_once()
        # No-op callback returned per service contract.
        assert cb is not None

    @pytest.mark.asyncio
    async def test_admin_value_only_leaves_description_unchanged(self):
        """exclude_unset semantic — admin omits ``description`` →
        existing description survives."""
        row = _existing_row(value=2026)
        existing_desc = row.description
        service, _db = _make_service(row=row)

        update = SystemConfigUpdate.model_validate({"value": 2027})
        updated, _cb = await service.update(
            "current_intake_year", update, _user(UserRole.ADMIN)
        )

        assert updated.value == 2027
        assert updated.description == existing_desc

    @pytest.mark.asyncio
    async def test_admin_value_can_be_complex_jsonb_shape(self):
        """``value`` is JSONB — admin can store list / nested object
        / bool. Service does not validate inner shape (Q10 admin
        responsibility)."""
        row = _existing_row(key="zalo_template_approved", value=False)
        service, _db = _make_service(row=row)

        nested = {"primary": True, "fallback_template_ids": ["abc", "def"]}
        update = SystemConfigUpdate.model_validate({"value": nested})
        updated, _cb = await service.update(
            "zalo_template_approved", update, _user(UserRole.ADMIN)
        )

        assert updated.value == nested


# ---------------------------------------------------------------------------
# 2. Non-admin blocked
# ---------------------------------------------------------------------------


class TestNonAdminBlocked:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role",
        [
            UserRole.MANAGER,
            UserRole.OFFICER,
            UserRole.ACCOUNTANT,
            UserRole.USER,
        ],
    )
    async def test_non_admin_cannot_update(self, role):
        row = _existing_row()
        service, db = _make_service(row=row)

        update = SystemConfigUpdate.model_validate({"value": 2027})
        with pytest.raises(BusinessRuleViolation, match="Chỉ admin"):
            await service.update("current_intake_year", update, _user(role))

        # Service rejects BEFORE the row is fetched — no flush, no
        # mutation reaches the DB.
        db.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. Read path permissive
# ---------------------------------------------------------------------------


class TestReadPermissive:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "role",
        [
            UserRole.ADMIN,
            UserRole.MANAGER,
            UserRole.OFFICER,
            UserRole.ACCOUNTANT,
            UserRole.USER,
        ],
    )
    async def test_any_role_can_read_via_get_by_key(self, role):
        # Service.get_by_key has no role guard — it's the router's
        # responsibility to gate the endpoint via Depends. This
        # asserts the service contract is read-permissive.
        row = _existing_row()
        service, _db = _make_service(row=row)
        result = await service.get_by_key("current_intake_year")
        assert result is row

    @pytest.mark.asyncio
    async def test_list_all_works_without_role_guard(self):
        row = _existing_row()
        service, _db = _make_service(row=row)
        rows = await service.list_all()
        assert len(rows) == 1
        assert rows[0].key == "current_intake_year"


# ---------------------------------------------------------------------------
# 4. Key-not-found contract
# ---------------------------------------------------------------------------


class TestKeyNotFound:
    @pytest.mark.asyncio
    async def test_get_by_key_raises_404_when_absent(self):
        service, _db = _make_service(row=None)
        with pytest.raises(ResourceNotFoundError, match="không tồn tại"):
            await service.get_by_key("missing_key")

    @pytest.mark.asyncio
    async def test_update_raises_404_when_key_absent(self):
        """Update on missing key → ResourceNotFoundError (404),
        not 400. Caller gets a clear "key doesn't exist" signal."""
        service, _db = _make_service(row=None)
        update = SystemConfigUpdate.model_validate({"value": 2027})
        with pytest.raises(ResourceNotFoundError, match="không tồn tại"):
            await service.update("missing_key", update, _user(UserRole.ADMIN))

    @pytest.mark.asyncio
    async def test_get_value_returns_default_when_absent(self):
        """Convenience accessor — service callers that prefer a
        fallback over a 404 use ``get_value(key, default)``."""
        service, _db = _make_service(row=None)
        result = await service.get_value("missing_key", default=2025)
        assert result == 2025

    @pytest.mark.asyncio
    async def test_get_value_returns_value_when_present(self):
        row = _existing_row(value=2026)
        service, _db = _make_service(row=row)
        result = await service.get_value("current_intake_year", default=9999)
        assert result == 2026
