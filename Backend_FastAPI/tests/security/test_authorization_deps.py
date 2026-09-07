# tests/security/test_authorization_deps.py
"""
Unit tests for Authorization dependencies (Phase 3).

Tests new dependencies created in Phase 1-2:
- require_admin
- require_admin_or_manager
- require_any_staff
- check_permission (inactive user blocking)
- get_lead_list_filter
- get_kpi_target_for_admin

Per AUTHORIZATION_GUIDELINES.md v1.0
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.deps import (
    require_admin,
    require_admin_or_manager,
    require_any_staff,
    get_lead_list_filter,
    LeadListFilter,
    check_permission,
    get_current_user,
)
from app.core.constants import UserRole
from app.utils.exceptions import PermissionDeniedError


# =============================================================================
# FIXTURES
# =============================================================================

def create_mock_user(role: str, is_active: bool = True, user_id: int = 1, unit_id: int = 10):
    """Create a mock user with specified role and status."""
    user = MagicMock()
    user.id = user_id
    user.role = role
    user.is_active = is_active
    user.unit_id = unit_id
    user.username = f"test_{role}"
    return user


# =============================================================================
# TEST: require_admin
# =============================================================================

class TestRequireAdmin:
    """Tests for require_admin dependency."""
    
    @pytest.mark.asyncio
    async def test_admin_passes(self):
        """Admin role should pass."""
        user = create_mock_user(role=UserRole.ADMIN)
        result = await require_admin(user)
        assert result == user
    
    @pytest.mark.asyncio
    async def test_manager_rejected(self):
        """Manager role should be rejected."""
        user = create_mock_user(role=UserRole.MANAGER)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await require_admin(user)
        assert "Admin access required" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_officer_rejected(self):
        """Officer role should be rejected."""
        user = create_mock_user(role=UserRole.OFFICER)
        with pytest.raises(PermissionDeniedError):
            await require_admin(user)


# =============================================================================
# TEST: require_admin_or_manager
# =============================================================================

class TestRequireAdminOrManager:
    """Tests for require_admin_or_manager dependency."""
    
    @pytest.mark.asyncio
    async def test_admin_passes(self):
        """Admin role should pass."""
        user = create_mock_user(role=UserRole.ADMIN)
        result = await require_admin_or_manager(user)
        assert result == user
    
    @pytest.mark.asyncio
    async def test_manager_passes(self):
        """Manager role should pass."""
        user = create_mock_user(role=UserRole.MANAGER)
        result = await require_admin_or_manager(user)
        assert result == user
    
    @pytest.mark.asyncio
    async def test_officer_rejected(self):
        """Officer role should be rejected."""
        user = create_mock_user(role=UserRole.OFFICER)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await require_admin_or_manager(user)
        assert "Admin or Manager access required" in str(exc_info.value.detail)


# =============================================================================
# TEST: require_any_staff
# =============================================================================

class TestRequireAnyStaff:
    """Tests for require_any_staff dependency."""
    
    @pytest.mark.asyncio
    async def test_admin_passes(self):
        """Admin role should pass."""
        user = create_mock_user(role=UserRole.ADMIN)
        result = await require_any_staff(user)
        assert result == user
    
    @pytest.mark.asyncio
    async def test_manager_passes(self):
        """Manager role should pass."""
        user = create_mock_user(role=UserRole.MANAGER)
        result = await require_any_staff(user)
        assert result == user
    
    @pytest.mark.asyncio
    async def test_officer_passes(self):
        """Officer role should pass."""
        user = create_mock_user(role=UserRole.OFFICER)
        result = await require_any_staff(user)
        assert result == user
    
    @pytest.mark.asyncio
    async def test_non_staff_rejected(self):
        """Non-staff role should be rejected."""
        user = create_mock_user(role="customer")  # Unknown role
        with pytest.raises(PermissionDeniedError) as exc_info:
            await require_any_staff(user)
        assert "Staff access required" in str(exc_info.value.detail)


# =============================================================================
# TEST: get_lead_list_filter
# =============================================================================

class TestGetLeadListFilter:
    """Tests for get_lead_list_filter context filtering dependency."""
    
    @pytest.mark.asyncio
    async def test_officer_forced_to_own_leads(self):
        """Officer should only see their own leads, ignoring passed filter."""
        user = create_mock_user(role=UserRole.OFFICER, user_id=123)
        
        result = await get_lead_list_filter(
            assigned_officer_id="999",  # Agent tries to pass different ID
            unit_id=5,
            current_user=user
        )
        
        assert isinstance(result, LeadListFilter)
        assert result.assigned_officer_id == "123"  # Forced to own ID
        assert result.unit_id is None  # Officers cannot filter by unit
        assert result.is_forced_officer_filter is True
        assert result.requesting_user == user
    
    @pytest.mark.asyncio
    async def test_manager_forced_to_own_unit(self):
        """Manager can filter by officers but forced to their unit."""
        user = create_mock_user(role=UserRole.MANAGER, unit_id=10)
        
        result = await get_lead_list_filter(
            assigned_officer_id="456",  # Manager can filter by officer
            unit_id=99,  # Should be overridden
            current_user=user
        )
        
        assert result.assigned_officer_id == "456"  # Preserved
        assert result.unit_id == 10  # Forced to manager's unit
        assert result.is_forced_officer_filter is False
    
    @pytest.mark.asyncio
    async def test_admin_full_access(self):
        """Admin should have full access to all filters."""
        user = create_mock_user(role=UserRole.ADMIN)
        
        result = await get_lead_list_filter(
            assigned_officer_id="789",
            unit_id=50,
            current_user=user
        )
        
        assert result.assigned_officer_id == "789"  # Preserved
        assert result.unit_id == 50  # Preserved
        assert result.is_forced_officer_filter is False

    @pytest.mark.asyncio
    async def test_dashboard_context_is_preserved_in_filter_contract(self):
        """Dashboard context should be resolved once and exposed via LeadListFilter."""
        user = create_mock_user(role=UserRole.MANAGER, unit_id=10)
        db = MagicMock()
        ctx = MagicMock()
        ctx.effective_officer_ids = []
        ctx.effective_unit_ids = [10, 11]
        ctx.effective_unit_root_id = 10
        ctx.includes_descendants = True
        ctx.scope_kind = "unit"
        ctx.label = "Đơn vị"
        ctx.forced_by_role = True
        ctx.requested_officer_id = None
        ctx.requested_unit_id = 10

        with patch("app.core.deps.get_officer_dashboard_scope", new=AsyncMock(return_value=ctx)):
            result = await get_lead_list_filter(
                nav_source="dashboard",
                scope="unit",
                scope_unit_id=10,
                include_descendants=True,
                loss_reason="PRICE_HIGH",
                db=db,
                current_user=user,
            )

        assert result.unit_id is None
        assert result.unit_ids == [10, 11]
        assert result.scope == "unit"
        assert result.scope_unit_id == 10
        assert result.include_descendants is True
        assert result.loss_reason == "PRICE_HIGH"
        assert result.effective_scope == {
            "scope_kind": "unit",
            "label": "Đơn vị",
            "forced_by_role": True,
            "includes_descendants": True,
        }


# =============================================================================
# TEST: check_permission (Inactive User Blocking)
# =============================================================================

# ⚠️ `create_mock_user` above sets `user.is_active`, but the production gate
# (`app/core/deps.get_current_active_user`) reads `user.status`. On a MagicMock
# an unset `user.status` is itself a MagicMock and is therefore `!= "active"`,
# so EVERY user built by that helper would be blocked and the test below would
# go green for the wrong reason. This helper sets `status` explicitly — same
# shape as tests/security/test_idor_protection.py::create_mock_user.
def create_mock_user_with_status(
    role: str, status: str, user_id: int = 1, unit_id: int = 10
):
    """Create a mock user whose `status` attribute is set EXPLICITLY."""
    user = MagicMock()
    user.id = user_id
    user.role = role
    user.status = status
    user.unit_id = unit_id
    user.username = f"test_{role}_{status}"
    # get_current_active_user also enforces MFA for privileged roles. Pin this
    # True so the tests isolate the active-status gate and can never be carried
    # by the MFA branch instead.
    user.mfa_enabled = True
    return user


def build_casbin_protected_app(current_user, enforcer):
    """
    Build a real FastAPI app with one route guarded by `check_permission`.

    `check_permission` is a plain dependency, not a factory — its signature is

        async def check_permission(
            request: Request,
            current_user: models.User = Depends(get_current_active_user),
        ) -> models.User

    so it is wired as `Depends(check_permission)` with no call.

    Only `get_current_user` is overridden. `get_current_active_user` stays REAL,
    because it is exactly the gate under test.
    """
    app = FastAPI()
    app.state.enforcer = enforcer

    @app.get("/protected")
    async def protected_route(user=Depends(check_permission)):
        return {"user_id": user.id}

    async def _override_current_user():
        return current_user

    app.dependency_overrides[get_current_user] = _override_current_user
    return app


class TestCheckPermissionInactiveUser:
    """
    Tests for check_permission blocking inactive users.

    This verifies the security fix from Phase 1 where check_permission
    was changed from get_current_user to get_current_active_user.
    """

    @pytest.mark.asyncio
    async def test_inactive_user_blocked_from_casbin_protected_route(self):
        """
        An inactive user must be blocked BEFORE Casbin is consulted.

        Casbin is rigged to ALLOW (`enforce` -> True), so a rejection here can
        only come from the active-user dependency. Asserting that `enforce` was
        never called pins the dependency ORDER, not merely the outcome.
        """
        enforcer = MagicMock()
        enforcer.enforce = MagicMock(return_value=True)
        user = create_mock_user_with_status(role=UserRole.OFFICER, status="inactive")
        app = build_casbin_protected_app(user, enforcer)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            res = await ac.get("/protected")

        # app/core/deps.py: get_current_active_user raises
        # HTTPException(status.HTTP_400_BAD_REQUEST, detail="Inactive user")
        assert res.status_code == 400, res.text
        assert "Inactive user" in res.text
        enforcer.enforce.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_user_passes_same_casbin_protected_route(self):
        """
        Counter-case on the SAME route with the SAME rigged-allow Casbin: an
        active user must get through.

        Without this, a `check_permission` that denied everything (or a route
        that 500'd for an unrelated reason) would still make the test above
        pass, so the 400 alone proves nothing about the active-status gate.
        """
        enforcer = MagicMock()
        enforcer.enforce = MagicMock(return_value=True)
        user = create_mock_user_with_status(role=UserRole.OFFICER, status="active")
        app = build_casbin_protected_app(user, enforcer)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            res = await ac.get("/protected")

        assert res.status_code == 200, res.text
        assert res.json() == {"user_id": user.id}
        # Proof the request really traversed check_permission's Casbin call
        # (and therefore that the 400 above was raised before this point).
        enforcer.enforce.assert_called_once()
        subject, object_path, action = enforcer.enforce.call_args.args
        assert subject == f"role:{UserRole.OFFICER}"
        assert object_path == "/protected"
        assert action == "GET"
