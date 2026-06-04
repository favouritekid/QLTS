# tests/unit/test_admission_idor_filters.py
"""
Unit tests for ``admission_service._resolve_idor_filters`` — the 3-tier IDOR
scope resolver shared by the admission list / export / status-counts / stats /
academic-years / pending-diploma endpoints.

Focus: the fail-closed contract for staff whose ``unit_id IS NULL``. Returning
``(None, ...)`` for such a user makes ``admission_repository`` drop the unit
predicate (it only filters ``if unit_id is not None``), silently widening a
unit-scoped manager/officer to a system-wide view of every profile / CSV row /
status count / nợ-bằng entry. The resolver must deny instead — mirrors the KPI
precedent ``test_coverage_manager_no_unit_gets_403``.

Pure function test — no DB, no Casbin, no HTTP client (mirrors the
``models.User`` in-memory construction in
``tests/services/test_organization_m12_scoping.py``).
"""
import pytest

from app import models
from app.core.constants import UserRole
from app.services.admission_service import _resolve_idor_filters
from app.utils.exceptions import PermissionDeniedError

pytestmark = pytest.mark.unit


class TestResolveIdorFiltersScope:
    """Well-configured users resolve to the expected (unit, officer) tuple."""

    def test_admin_sees_all(self):
        user = models.User(id=1, username="admin", role=UserRole.ADMIN, unit_id=None)
        assert _resolve_idor_filters(user) == (None, None)

    def test_admin_with_unit_still_sees_all(self):
        # An admin carrying a unit_id is still unscoped — admin bypasses unit.
        user = models.User(id=1, username="admin", role=UserRole.ADMIN, unit_id=5)
        assert _resolve_idor_filters(user) == (None, None)

    def test_manager_scoped_to_own_unit(self):
        user = models.User(id=2, username="mgr", role=UserRole.MANAGER, unit_id=7)
        assert _resolve_idor_filters(user) == (7, None)

    def test_officer_scoped_to_unit_and_self(self):
        user = models.User(id=3, username="off", role=UserRole.OFFICER, unit_id=7)
        assert _resolve_idor_filters(user) == (7, 3)


class TestResolveIdorFiltersFailClosed:
    """Mis-scoped / unexpected users are denied, never widened to (None, ...)."""

    def test_manager_without_unit_denied(self):
        user = models.User(
            id=4, username="mgr_nounit", role=UserRole.MANAGER, unit_id=None
        )
        with pytest.raises(PermissionDeniedError):
            _resolve_idor_filters(user)

    def test_officer_without_unit_denied(self):
        user = models.User(
            id=5, username="off_nounit", role=UserRole.OFFICER, unit_id=None
        )
        with pytest.raises(PermissionDeniedError):
            _resolve_idor_filters(user)

    def test_unknown_role_denied(self):
        # accountant (or any non-admission role) that somehow bypasses the
        # Casbin gate hits the defense-in-depth else-branch.
        user = models.User(id=6, username="acct", role=UserRole.ACCOUNTANT, unit_id=7)
        with pytest.raises(PermissionDeniedError):
            _resolve_idor_filters(user)
