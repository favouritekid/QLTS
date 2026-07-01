# tests/unit/test_admission_coordination_filters.py
"""
Unit tests for the Admission List v2 coordination layer — pure functions, no DB,
no Casbin, no HTTP (mirrors ``test_admission_idor_filters.py``):

- ``admission_service._resolve_coordination_filters`` — layers the user-supplied
  officer/unit/reviewer/unassigned filters ON TOP of the role IDOR scope. The
  security contract: officer is self-locked (cannot widen), manager is forced to
  its own unit (``unit_id`` param ignored), admin is free, and "unassigned" is
  mutually exclusive with the officer-IN list.
- ``admission_repository._hk1_status`` — maps (paid, remaining, overdue) → the
  HK1 display status; MUST normalize ``None`` (a profile with no HK1 fee) to 0 so
  it never raises ``None > 0`` (the no-HK1 → "none", not a 500).
"""
from decimal import Decimal

import pytest

from app import models
from app.core.constants import UserRole
from app.services.admission_service import _resolve_coordination_filters
from app.repositories.admission_repository import _hk1_status
from app.utils.exceptions import PermissionDeniedError

pytestmark = pytest.mark.unit


def _user(role, unit_id, uid=1):
    return models.User(id=uid, username=f"u{uid}", role=role, unit_id=unit_id)


class TestCoordinationFiltersAdmin:
    """Admin: free officer / unit / reviewer / unassigned."""

    def test_admin_free_officer_unit_reviewer(self):
        out = _resolve_coordination_filters(
            _user(UserRole.ADMIN, None),
            officer_ids=[5, 7],
            unit_id_param=3,
            reviewer_ids=[9],
            unassigned=False,
        )
        assert out == {
            "unit_id": 3,
            "assigned_officer_id": None,
            "assigned_officer_ids": [5, 7],
            "assigned_reviewer_ids": [9],
            "unassigned": False,
        }

    def test_admin_unassigned_drops_officer_list_xor(self):
        out = _resolve_coordination_filters(
            _user(UserRole.ADMIN, None),
            officer_ids=[5],
            unit_id_param=None,
            reviewer_ids=None,
            unassigned=True,
        )
        assert out["unassigned"] is True
        assert out["assigned_officer_ids"] is None  # XOR: officer list dropped


class TestCoordinationFiltersManager:
    """Manager: ALWAYS scoped to own unit; may narrow within it."""

    def test_manager_forced_own_unit_ignores_unit_param(self):
        out = _resolve_coordination_filters(
            _user(UserRole.MANAGER, 7),
            officer_ids=[5],
            unit_id_param=3,  # must be IGNORED — manager cannot pick another unit
            reviewer_ids=None,
            unassigned=False,
        )
        assert out["unit_id"] == 7
        assert out["assigned_officer_ids"] == [5]
        assert out["assigned_officer_id"] is None

    def test_manager_unassigned_within_own_unit(self):
        out = _resolve_coordination_filters(
            _user(UserRole.MANAGER, 7),
            officer_ids=[5],
            unit_id_param=None,
            reviewer_ids=None,
            unassigned=True,
        )
        assert out["unit_id"] == 7
        assert out["unassigned"] is True
        assert out["assigned_officer_ids"] is None  # XOR

    def test_manager_without_unit_denied(self):
        with pytest.raises(PermissionDeniedError):
            _resolve_coordination_filters(
                _user(UserRole.MANAGER, None), officer_ids=[5]
            )


class TestCoordinationFiltersOfficerSelfLock:
    """Officer: hard-locked to self; ALL coordination inputs dropped (no widen)."""

    def test_officer_self_lock_ignores_all_inputs(self):
        out = _resolve_coordination_filters(
            _user(UserRole.OFFICER, 7, uid=3),
            officer_ids=[99],       # crafted — must be ignored
            unit_id_param=3,        # ignored
            reviewer_ids=[9],       # ignored
            unassigned=True,        # ignored
        )
        assert out == {
            "unit_id": 7,
            "assigned_officer_id": 3,       # forced self
            "assigned_officer_ids": None,
            "assigned_reviewer_ids": None,
            "unassigned": False,
        }

    def test_officer_without_unit_denied(self):
        with pytest.raises(PermissionDeniedError):
            _resolve_coordination_filters(_user(UserRole.OFFICER, None, uid=3))


class TestHk1Status:
    """_hk1_status(paid, remaining, overdue, final) mapping + None-normalization.

    ``final`` (Σ final_amount HK1) distinguishes 'has a HK1 fee' (final>0) from
    'no HK1 fee' (final<=0 → none), so a fully-waived fee reads as settled.
    """

    def test_overdue_wins(self):
        assert _hk1_status(Decimal("1"), Decimal("1"), True, Decimal("9200000")) == "overdue"

    def test_paid_full(self):
        assert _hk1_status(Decimal("9200000"), Decimal("0"), False, Decimal("9200000")) == "paid"

    def test_fully_waived_is_paid_not_none(self):
        # Miễn 100%: final=9.2M, paid=0, remaining=0 → đã tất toán ("paid"), KHÔNG "none".
        assert _hk1_status(Decimal("0"), Decimal("0"), False, Decimal("9200000")) == "paid"

    def test_partial(self):
        assert _hk1_status(Decimal("3000000"), Decimal("6200000"), False, Decimal("9200000")) == "partial"

    def test_unpaid(self):
        assert _hk1_status(Decimal("0"), Decimal("9200000"), False, Decimal("9200000")) == "unpaid"

    def test_none_when_no_fee(self):
        # final<=0 = chưa có fee HK1 (hoặc chỉ có fee đã hủy → bị loại khỏi subquery).
        assert _hk1_status(Decimal("0"), Decimal("0"), False, Decimal("0")) == "none"

    def test_none_inputs_do_not_crash(self):
        # SUM trên 0 hàng → NULL (None). Normalize → "none", not 500.
        assert _hk1_status(None, None, False, None) == "none"

    def test_none_paid_with_remaining(self):
        assert _hk1_status(None, Decimal("9200000"), False, Decimal("9200000")) == "unpaid"
