"""compute_can_edit_governance gate (PR matrix-funnel — thin-client flag).

The FE 'Nâng cao' (governance) tab now gates on the server-computed
``can_edit_governance`` flag instead of ``user.role``. The service helper
mirrors EXACTLY the prior FE gate: admin-only, regardless of path status.

Pure unit test — the helper only reads ``user.role``; no DB needed. The
``status != 'archived'`` condition is deliberately ABSENT (admin can still
edit governance on archived paths today; adding it would be a silent
behavior change). See plan §1C + memory ``pattern-change-impact-audit``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.constants import UserRole
from app.services.admission_path_service import AdmissionPathService

pytestmark = pytest.mark.unit


def _svc() -> AdmissionPathService:
    # Helper reads no instance state — bypass __init__ (needs a db session).
    return AdmissionPathService.__new__(AdmissionPathService)


def _user(role) -> SimpleNamespace:
    return SimpleNamespace(role=role)


def _path(status: str = "active") -> SimpleNamespace:
    return SimpleNamespace(status=status)


def test_admin_can_edit_governance():
    assert _svc().compute_can_edit_governance(_path(), _user(UserRole.ADMIN)) is True


def test_manager_cannot_edit_governance():
    assert (
        _svc().compute_can_edit_governance(_path(), _user(UserRole.MANAGER)) is False
    )


def test_officer_cannot_edit_governance():
    assert (
        _svc().compute_can_edit_governance(_path(), _user(UserRole.OFFICER)) is False
    )


def test_none_user_cannot_edit_governance():
    assert _svc().compute_can_edit_governance(_path(), None) is False


def test_admin_can_edit_governance_even_on_archived_path():
    # Deliberate: no status!='archived' guard — mirrors current FE behavior.
    assert (
        _svc().compute_can_edit_governance(_path("archived"), _user(UserRole.ADMIN))
        is True
    )
