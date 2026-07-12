"""Unit tests for lead_service.compute_lead_action_permissions().

Pure function (no DB): verifies the query-free transfer/reassign action flags
shared by the LeadDetail populate path and the paginated list serializer. These
flags gate "Chuyển giao lead" (manager/admin) vs "Yêu cầu đổi người phụ trách"
(officer được giao) in the row/card menu without the FE reading user.role.
"""
from types import SimpleNamespace

import pytest

from app.core.constants import UserRole
from app.services.lead_service import compute_lead_action_permissions

pytestmark = pytest.mark.unit


def _lead(assigned_officer_id=None):
    return SimpleNamespace(assigned_officer_id=assigned_officer_id)


def _user(role, uid=1):
    return SimpleNamespace(role=role, id=uid)


def test_manager_assigned_can_transfer_not_reassign():
    p = compute_lead_action_permissions(_lead(assigned_officer_id=5), _user(UserRole.MANAGER))
    assert p["can_transfer_lead"] is True
    assert p["can_request_reassign"] is False
    assert p["can_assign_lead"] is True  # manager luôn được gán (endpoint admin/manager-only)


def test_admin_assigned_can_transfer():
    p = compute_lead_action_permissions(_lead(assigned_officer_id=5), _user(UserRole.ADMIN))
    assert p["can_transfer_lead"] is True
    assert p["can_assign_lead"] is True


def test_manager_unassigned_can_assign_not_transfer():
    # lead chưa có người phụ trách → hiện "Gán cho cán bộ" (can_assign), không transfer
    p = compute_lead_action_permissions(_lead(assigned_officer_id=None), _user(UserRole.MANAGER))
    assert p["can_assign_lead"] is True
    assert p["can_transfer_lead"] is False
    assert p["can_request_reassign"] is False


def test_officer_assigned_to_self_can_request_reassign():
    p = compute_lead_action_permissions(
        _lead(assigned_officer_id=7), _user(UserRole.OFFICER, uid=7)
    )
    assert p["can_request_reassign"] is True
    assert p["can_transfer_lead"] is False
    assert p["can_assign_lead"] is False  # officer KHÔNG được gán (thin-client ẩn nút)


def test_officer_not_assigned_no_flags():
    # officer nhìn lead của người khác → không có cờ hành động nào
    p = compute_lead_action_permissions(
        _lead(assigned_officer_id=99), _user(UserRole.OFFICER, uid=7)
    )
    assert p["can_request_reassign"] is False
    assert p["can_transfer_lead"] is False
    assert p["can_assign_lead"] is False


def test_system_context_none_user_returns_empty():
    assert compute_lead_action_permissions(_lead(assigned_officer_id=5), None) == {}
