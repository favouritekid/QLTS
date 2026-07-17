"""Unit tests for lead_service.compute_consultation_action_permissions() (Nhóm 4).

Pure function (no DB): cờ quyền thin-client can_edit / can_delete / can_reschedule
+ blocker, mirror guard THẬT ở update_consultation / delete_consultation (+F3).
FE gate nút Sửa/Xóa/Dời-Hủy thuần theo cờ, KHÔNG đọc user.role.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.constants import UserRole
from app.services.lead_service import compute_consultation_action_permissions

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 17, 8, 0, 0, tzinfo=timezone.utc)
_RECENT = _NOW - timedelta(hours=1)
_OLD = _NOW - timedelta(hours=30)  # ngoài 24h


def _user(role, uid=1):
    return SimpleNamespace(role=role, id=uid)


def _lead(assigned_officer_id=None):
    return SimpleNamespace(assigned_officer_id=assigned_officer_id)


def _consult(method="phone", officer_id=1, anchor=_RECENT):
    return SimpleNamespace(
        method=method, officer_id=officer_id,
        created_at=anchor, consultation_date=anchor,
    )


def _perm(consult, lead, user, is_latest=True, is_active=True):
    return compute_consultation_action_permissions(
        consult, lead, user, is_latest=is_latest,
        is_active_appointment=is_active, now=_NOW,
    )


# --- current_user None → {} ---
def test_none_user_returns_empty():
    assert _perm(_consult(), _lead(5), None) == {}


# --- admin/manager: sửa/xóa cuộc bất kỳ non-system, không cần latest/author/24h ---
def test_admin_can_edit_delete_any_non_system():
    p = _perm(_consult(officer_id=99), _lead(5), _user(UserRole.ADMIN), is_latest=False)
    assert p["can_edit"] and p["can_delete"]
    assert p["edit_blocker"] is None and p["delete_blocker"] is None


def test_manager_old_consultation_still_editable():
    """Admin/Manager KHÔNG bị gate 24h."""
    p = _perm(_consult(anchor=_OLD), _lead(5), _user(UserRole.MANAGER))
    assert p["can_edit"] and p["can_delete"]


# --- officer: latest + assigned + author + 24h ---
def test_officer_own_latest_recent_can_edit_delete():
    p = _perm(_consult(officer_id=2), _lead(2), _user(UserRole.OFFICER, 2))
    assert p["can_edit"] and p["can_delete"]


def test_officer_not_latest_blocked():
    p = _perm(_consult(officer_id=2), _lead(2), _user(UserRole.OFFICER, 2), is_latest=False)
    assert not p["can_edit"] and p["edit_blocker"] == "not_latest"
    assert not p["can_delete"] and p["delete_blocker"] == "not_latest"


def test_officer_not_assigned_blocked():
    p = _perm(_consult(officer_id=2), _lead(999), _user(UserRole.OFFICER, 2))
    assert not p["can_edit"] and p["edit_blocker"] == "not_assigned"


def test_officer_not_author_blocked():
    """Cuộc do officer KHÁC tạo → not_author (F3: delete cũng đòi author)."""
    p = _perm(_consult(officer_id=77), _lead(2), _user(UserRole.OFFICER, 2))
    assert not p["can_edit"] and p["edit_blocker"] == "not_author"
    assert not p["can_delete"] and p["delete_blocker"] == "not_author"


def test_officer_expired_24h_edit_blocked_but_delete_ok():
    """24h CHỈ áp cho can_edit; can_delete KHÔNG có 24h (khớp BE)."""
    p = _perm(_consult(officer_id=2, anchor=_OLD), _lead(2), _user(UserRole.OFFICER, 2))
    assert not p["can_edit"] and p["edit_blocker"] == "expired_24h"
    assert p["can_delete"] and p["delete_blocker"] is None


def test_officer_null_created_at_falls_back_to_consultation_date():
    """anchor = created_at ?? consultation_date — created_at NULL vẫn tính 24h
    theo consultation_date (không drift)."""
    c = SimpleNamespace(
        method="phone", officer_id=2, created_at=None, consultation_date=_RECENT
    )
    p = _perm(c, _lead(2), _user(UserRole.OFFICER, 2))
    assert p["can_edit"]  # consultation_date recent → trong 24h


# --- system → bất biến, mọi cờ False, blocker 'system' (kể cả admin) ---
def test_system_consultation_all_false_even_admin():
    p = _perm(_consult(method="system"), _lead(5), _user(UserRole.ADMIN))
    assert not p["can_edit"] and not p["can_delete"] and not p["can_reschedule"]
    assert p["edit_blocker"] == "system" and p["delete_blocker"] == "system"


# --- can_reschedule = is_active_appointment AND can_edit ---
def test_reschedule_requires_active_appointment():
    admin = _user(UserRole.ADMIN)
    assert _perm(_consult(), _lead(5), admin, is_active=True)["can_reschedule"]
    assert not _perm(_consult(), _lead(5), admin, is_active=False)["can_reschedule"]


def test_reschedule_false_when_cannot_edit():
    """Officer không phải tác giả → can_edit False → can_reschedule False dù
    is_active_appointment."""
    p = _perm(_consult(officer_id=77), _lead(2), _user(UserRole.OFFICER, 2), is_active=True)
    assert not p["can_reschedule"]


# --- vai trò khác (accountant) → mọi cờ False ---
def test_other_role_all_false():
    p = _perm(_consult(), _lead(5), _user(UserRole.ACCOUNTANT, 3))
    assert not p["can_edit"] and not p["can_delete"] and not p["can_reschedule"]
