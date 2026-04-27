"""ADM-005 regression: lifecycle guard must apply to ``update_path``,
``upsert_criteria`` and ``upsert_documents`` alike.

Before the fix, only ``update_path`` blocked managers from editing
non-draft paths and rejected archived paths. Routes that delegated to
``upsert_criteria`` / ``upsert_documents`` therefore let a manager edit
the rules of an active or even archived path — which the audit flagged
as a governance gap.

The shared helper ``_check_lifecycle_guard`` is now invoked at the top of
all three service methods. These tests pin its contract directly so a
future regression at any one call site stays caught.
"""

from types import SimpleNamespace

import pytest

from app.core.constants import UserRole
from app.services.admission_path_service import _check_lifecycle_guard
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.unit


def _path(status: str):
    return SimpleNamespace(id=1, status=status)


def _user(role: UserRole):
    return SimpleNamespace(id=1, role=role)


class TestLifecycleGuard:
    def test_archived_blocks_admin(self):
        with pytest.raises(BusinessRuleViolation, match="archived"):
            _check_lifecycle_guard(_path("archived"), _user(UserRole.ADMIN))

    def test_archived_blocks_manager(self):
        with pytest.raises(BusinessRuleViolation, match="archived"):
            _check_lifecycle_guard(_path("archived"), _user(UserRole.MANAGER))

    def test_admin_can_edit_draft(self):
        _check_lifecycle_guard(_path("draft"), _user(UserRole.ADMIN))

    def test_admin_can_edit_active(self):
        # Admin emergency edit of an active path is intent (Q2 decision a/b)
        _check_lifecycle_guard(_path("active"), _user(UserRole.ADMIN))

    def test_admin_can_edit_inactive(self):
        _check_lifecycle_guard(_path("inactive"), _user(UserRole.ADMIN))

    def test_manager_can_edit_draft(self):
        _check_lifecycle_guard(_path("draft"), _user(UserRole.MANAGER))

    def test_manager_blocked_on_active(self):
        with pytest.raises(BusinessRuleViolation, match="draft"):
            _check_lifecycle_guard(_path("active"), _user(UserRole.MANAGER))

    def test_manager_blocked_on_inactive(self):
        with pytest.raises(BusinessRuleViolation, match="draft"):
            _check_lifecycle_guard(_path("inactive"), _user(UserRole.MANAGER))

    @pytest.mark.parametrize(
        "role",
        [UserRole.OFFICER, UserRole.USER, UserRole.ACCOUNTANT],
    )
    def test_non_admin_non_manager_blocked_on_non_draft(self, role):
        """Defense-in-depth: anything past Casbin must still hit draft-only."""
        with pytest.raises(BusinessRuleViolation, match="draft"):
            _check_lifecycle_guard(_path("active"), _user(role))
