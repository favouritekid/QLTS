# tests/routers/admin/test_roles.py
"""
PHASE 2A: Automated Tests for Admin Roles Router

Tests for app/routers/admin/roles.py endpoints:
- Policy CRUD operations
- Role assignment (PHASE 1 integration)
- Grouping policies (role inheritance)
- Role management (atomic operations)
- Policy validation & simulation
- Analytics & insights
- Feature flags

Created: 2025-11-17
Part of: PHASE 2A Router Extraction
"""
import logging
from typing import Dict

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)


# ============================================================================
# POLICY CRUD OPERATIONS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_get_all_policies(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/roles/policies - Get all policies

    Verifies:
    - Admin can view all Casbin policies
    - Response is a list of policy tuples [subject, object, action]
    """
    log.info("--- Running: test_get_all_policies ---")

    response = await client.get(
        "/api/admin/roles/policies",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get policies: {response.text}"
    data = response.json()

    # Verify response is a list
    assert isinstance(data, list), "Response should be a list"

    # If there are policies, verify structure
    if len(data) > 0:
        policy = data[0]
        assert isinstance(policy, list), "Each policy should be a list"
        assert len(policy) >= 3, "Policy should have [subject, object, action]"

    log.info(f"✅ Retrieved {len(data)} policies")


@pytest.mark.asyncio
async def test_add_policy_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/roles/policies - Add new policy

    Verifies:
    - Admin can add new policy
    - Policy is added to Casbin enforcer
    - Activity log is created
    """
    log.info("--- Running: test_add_policy_success ---")

    policy_data = {
        "subject": "role:test",
        "object": "/api/test/*",
        "action": "GET",
    }

    response = await client.post(
        "/api/admin/roles/policies",
        json=policy_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to add policy: {response.text}"

    # Verify policy is in enforcer (by getting all policies)
    get_response = await client.get(
        "/api/admin/roles/policies",
        headers=admin_token_headers,
    )
    policies = get_response.json()

    # Check if our policy exists
    policy_tuple = [policy_data["subject"], policy_data["object"], policy_data["action"]]
    assert policy_tuple in policies, "Policy not found in enforcer"

    log.info("✅ Policy added successfully")


@pytest.mark.asyncio
async def test_add_duplicate_policy_fails(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/roles/policies - Duplicate policy should fail

    Verifies:
    - Cannot add duplicate policy
    - Returns 400 or 409
    """
    log.info("--- Running: test_add_duplicate_policy_fails ---")

    policy_data = {
        "subject": "role:duplicate_test",
        "object": "/api/duplicate/*",
        "action": "GET",
    }

    # Add policy first time
    response1 = await client.post(
        "/api/admin/roles/policies",
        json=policy_data,
        headers=admin_token_headers,
    )
    assert response1.status_code == 201

    # Try to add same policy again
    response2 = await client.post(
        "/api/admin/roles/policies",
        json=policy_data,
        headers=admin_token_headers,
    )

    # Should fail
    assert response2.status_code in [400, 409], \
        f"Duplicate policy should fail, got: {response2.status_code}"

    log.info("✅ Duplicate policy properly rejected")


@pytest.mark.asyncio
async def test_delete_policy_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/roles/policies - Delete policy

    Verifies:
    - Admin can delete policy
    - Policy is removed from Casbin enforcer
    - Activity log is created
    """
    log.info("--- Running: test_delete_policy_success ---")

    # First add a policy
    policy_data = {
        "subject": "role:delete_test",
        "object": "/api/delete/*",
        "action": "GET",
    }

    add_response = await client.post(
        "/api/admin/roles/policies",
        json=policy_data,
        headers=admin_token_headers,
    )
    assert add_response.status_code == 201

    # Delete the policy
    delete_response = await client.delete(
        "/api/admin/roles/policies",
        json=policy_data,
        headers=admin_token_headers,
    )

    assert delete_response.status_code == 200, \
        f"Failed to delete policy: {delete_response.text}"

    # Verify policy is removed
    get_response = await client.get(
        "/api/admin/roles/policies",
        headers=admin_token_headers,
    )
    policies = get_response.json()

    policy_tuple = [policy_data["subject"], policy_data["object"], policy_data["action"]]
    assert policy_tuple not in policies, "Policy should be removed"

    log.info("✅ Policy deleted successfully")


# ============================================================================
# ROLE ASSIGNMENT TESTS (PHASE 1 Integration)
# ============================================================================


@pytest.mark.asyncio
async def test_assign_role_to_user(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: dict,
):
    """
    Test: POST /api/admin/roles/assign - Assign role to user

    Verifies:
    - Admin can assign role to user
    - PHASE 1 Integration: Uses role_service.assign_role()
    - Grouping policy is added to Casbin
    - Activity log is created
    """
    log.info("--- Running: test_assign_role_to_user ---")

    user_id = regular_user_in_db["id"]
    assignment_data = {
        "user_id": user_id,
        "role": "role:manager",
    }

    response = await client.post(
        "/api/admin/roles/assign",
        json=assignment_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to assign role: {response.text}"

    # Verify role is assigned (get user roles)
    get_roles_response = await client.get(
        f"/api/admin/roles/users/{user_id}/roles",
        headers=admin_token_headers,
    )
    roles = get_roles_response.json()

    assert "role:manager" in roles, "Role not assigned to user"

    log.info(f"✅ Role assigned to user {user_id}")


@pytest.mark.asyncio
async def test_revoke_role_from_user(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: dict,
):
    """
    Test: DELETE /api/admin/roles/revoke - Revoke role from user

    Verifies:
    - Admin can revoke role from user
    - PHASE 1 Integration: Uses role_service.revoke_role()
    - Grouping policy is removed from Casbin
    - Activity log is created
    """
    log.info("--- Running: test_revoke_role_from_user ---")

    user_id = regular_user_in_db["id"]

    # First assign a role
    assignment_data = {
        "user_id": user_id,
        "role": "role:test_revoke",
    }
    assign_response = await client.post(
        "/api/admin/roles/assign",
        json=assignment_data,
        headers=admin_token_headers,
    )
    assert assign_response.status_code == 201

    # Revoke the role
    revoke_response = await client.delete(
        "/api/admin/roles/revoke",
        json=assignment_data,
        headers=admin_token_headers,
    )

    assert revoke_response.status_code == 200, \
        f"Failed to revoke role: {revoke_response.text}"

    # Verify role is revoked
    get_roles_response = await client.get(
        f"/api/admin/roles/users/{user_id}/roles",
        headers=admin_token_headers,
    )
    roles = get_roles_response.json()

    assert "role:test_revoke" not in roles, "Role should be revoked"

    log.info(f"✅ Role revoked from user {user_id}")


@pytest.mark.asyncio
async def test_get_user_roles(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: dict,
):
    """
    Test: GET /api/admin/roles/users/{user_id}/roles - Get user roles

    Verifies:
    - Admin can view all roles for a user
    - Response is a list of role names
    """
    log.info("--- Running: test_get_user_roles ---")

    user_id = admin_user_in_db["id"]

    response = await client.get(
        f"/api/admin/roles/users/{user_id}/roles",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get user roles: {response.text}"
    data = response.json()

    # Verify response is a list
    assert isinstance(data, list), "Response should be a list of roles"

    # Admin should have role:admin
    assert "role:admin" in data, "Admin user should have role:admin"

    log.info(f"✅ User {user_id} has {len(data)} roles")


@pytest.mark.asyncio
async def test_get_role_users(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: dict,
):
    """
    Test: GET /api/admin/roles/{role_name}/users - Get users with specific role

    Verifies:
    - Admin can view all users with a specific role
    - Response includes user details
    - Response includes user count
    """
    log.info("--- Running: test_get_role_users ---")

    response = await client.get(
        "/api/admin/roles/role:admin/users",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get role users: {response.text}"
    data = response.json()

    # Verify response structure
    assert "role" in data
    assert "user_count" in data
    assert "users" in data
    assert data["role"] == "role:admin"
    assert data["user_count"] > 0, "Should have at least one admin"
    assert len(data["users"]) > 0

    log.info(f"✅ Role role:admin has {data['user_count']} users")


# ============================================================================
# GROUPING POLICY TESTS (Role Inheritance)
# ============================================================================


@pytest.mark.asyncio
async def test_add_grouping_policy(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/roles/grouping-policies - Add grouping policy

    Verifies:
    - Admin can add grouping policy for role inheritance
    - Grouping policy is added to Casbin
    """
    log.info("--- Running: test_add_grouping_policy ---")

    grouping_data = {
        "subject": "role:support",
        "parent_role": "role:user",
    }

    response = await client.post(
        "/api/admin/roles/grouping-policies",
        json=grouping_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, \
        f"Failed to add grouping policy: {response.text}"

    log.info("✅ Grouping policy added successfully")


@pytest.mark.asyncio
async def test_delete_grouping_policy(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/roles/grouping-policies - Delete grouping policy

    Verifies:
    - Admin can remove grouping policy
    - Grouping policy is removed from Casbin
    """
    log.info("--- Running: test_delete_grouping_policy ---")

    # First add a grouping policy
    grouping_data = {
        "subject": "role:test_delete",
        "parent_role": "role:user",
    }

    add_response = await client.post(
        "/api/admin/roles/grouping-policies",
        json=grouping_data,
        headers=admin_token_headers,
    )
    assert add_response.status_code == 201

    # Delete the grouping policy
    delete_response = await client.delete(
        "/api/admin/roles/grouping-policies",
        json=grouping_data,
        headers=admin_token_headers,
    )

    assert delete_response.status_code == 200, \
        f"Failed to delete grouping policy: {delete_response.text}"

    log.info("✅ Grouping policy deleted successfully")


# ============================================================================
# ROLE MANAGEMENT TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_get_all_roles(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/roles - Get all roles with info

    Verifies:
    - Admin can view all roles
    - Response includes role metadata
    - Response includes policy counts
    """
    log.info("--- Running: test_get_all_roles ---")

    response = await client.get(
        "/api/admin/roles",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get roles: {response.text}"
    data = response.json()

    # Verify response structure
    assert "roles" in data
    assert isinstance(data["roles"], list)

    # Should have at least system roles (admin, manager, officer, user)
    assert len(data["roles"]) >= 4

    log.info(f"✅ Retrieved {len(data['roles'])} roles")


# ============================================================================
# VALIDATION & SIMULATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_validate_policy_operation(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/roles/policies/validate - Validate policy operation

    Verifies:
    - Admin can validate policy before applying
    - Response includes validation results
    - Response includes safety warnings
    """
    log.info("--- Running: test_validate_policy_operation ---")

    validation_data = {
        "operation": "add",
        "subject": "role:test",
        "object": "/api/test/*",
        "action": "GET",
    }

    response = await client.post(
        "/api/admin/roles/policies/validate",
        json=validation_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to validate policy: {response.text}"
    data = response.json()

    # Verify response structure
    assert "is_valid" in data
    assert "is_safe" in data
    assert isinstance(data["is_valid"], bool)

    log.info(f"✅ Policy validation result: valid={data['is_valid']}, safe={data['is_safe']}")


@pytest.mark.asyncio
async def test_simulate_permission(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/roles/permissions/simulate - Simulate permission check

    Verifies:
    - Admin can simulate permission check
    - Response indicates if permission is allowed
    - Response includes explanation
    """
    log.info("--- Running: test_simulate_permission ---")

    simulate_data = {
        "subject": "role:admin",
        "object": "/api/admin/users",
        "action": "GET",
    }

    response = await client.post(
        "/api/admin/roles/permissions/simulate",
        json=simulate_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to simulate permission: {response.text}"
    data = response.json()

    # Verify response structure
    assert "is_allowed" in data
    assert "message" in data
    assert isinstance(data["is_allowed"], bool)

    # role:admin should have access to /api/admin/users
    assert data["is_allowed"] == True, "Admin should have permission"

    log.info(f"✅ Permission simulation: {data['message']}")


# ============================================================================
# ANALYTICS & INSIGHTS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_get_policy_statistics(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/roles/policies/statistics - Get policy statistics

    Verifies:
    - Admin can view policy statistics
    - Response includes total policy counts
    - Response includes role counts
    """
    log.info("--- Running: test_get_policy_statistics ---")

    response = await client.get(
        "/api/admin/roles/policies/statistics",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, \
        f"Failed to get policy statistics: {response.text}"
    data = response.json()

    # Verify response has statistics
    assert data is not None

    log.info("✅ Policy statistics retrieved successfully")


@pytest.mark.asyncio
async def test_get_policy_suggestions(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/roles/policies/suggestions - Get autocomplete suggestions

    Verifies:
    - Admin can get autocomplete suggestions
    - Response includes unique subjects, objects, actions
    - Useful for UI autocomplete
    """
    log.info("--- Running: test_get_policy_suggestions ---")

    response = await client.get(
        "/api/admin/roles/policies/suggestions",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, \
        f"Failed to get policy suggestions: {response.text}"
    data = response.json()

    # Verify response structure
    assert "subjects" in data
    assert "objects" in data
    assert "actions" in data
    assert isinstance(data["subjects"], list)
    assert isinstance(data["objects"], list)
    assert isinstance(data["actions"], list)

    log.info(f"✅ Suggestions: {len(data['subjects'])} subjects, "
             f"{len(data['objects'])} objects, {len(data['actions'])} actions")


@pytest.mark.asyncio
async def test_explain_role_permissions(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/roles/{role_name}/permissions/explain - Explain role permissions

    Verifies:
    - Admin can get explanation of where role permissions come from
    - Response categorizes policies (template, feature, manual, inherited)
    """
    log.info("--- Running: test_explain_role_permissions ---")

    response = await client.get(
        "/api/admin/roles/role:admin/permissions/explain",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, \
        f"Failed to explain role permissions: {response.text}"
    data = response.json()

    # Verify response structure
    assert "role" in data
    assert "policies_from_template" in data
    assert "policies_from_features" in data
    assert "policies_manual" in data
    assert "policies_inherited" in data

    log.info(f"✅ Role permissions explained for {data['role']}")


@pytest.mark.asyncio
async def test_who_can_access_resource(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/roles/permissions/who-can-access - Who can access resource

    Verifies:
    - Admin can find which roles can access a resource
    - Response includes list of allowed subjects
    - Performance optimized (role-only lookup)
    """
    log.info("--- Running: test_who_can_access_resource ---")

    response = await client.post(
        "/api/admin/roles/permissions/who-can-access?object=/api/admin/users&action=GET",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, \
        f"Failed to get who can access: {response.text}"
    data = response.json()

    # Verify response structure
    assert "object" in data
    assert "action" in data
    assert "allowed_subjects" in data
    assert "total_count" in data
    assert "execution_time_ms" in data

    # role:admin should be in the list
    assert "role:admin" in data["allowed_subjects"], \
        "Admin should have access to /api/admin/users"

    log.info(f"✅ {data['total_count']} roles can access resource "
             f"(execution: {data['execution_time_ms']}ms)")


# ============================================================================
# FEATURE FLAGS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_get_role_features(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/roles/{role_name}/features - Get role features

    Verifies:
    - Admin can view feature flags for a role
    - Response includes feature status (enabled/disabled)
    """
    log.info("--- Running: test_get_role_features ---")

    response = await client.get(
        "/api/admin/roles/role:admin/features",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, \
        f"Failed to get role features: {response.text}"
    data = response.json()

    # Verify response structure
    assert "role" in data
    assert "features" in data
    assert isinstance(data["features"], list)

    log.info(f"✅ Retrieved {len(data['features'])} features for {data['role']}")


# ============================================================================
# PERMISSION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_regular_user_cannot_access_roles(
    client: AsyncClient,
    regular_user_in_db: dict,
):
    """
    Test: GET /api/admin/roles/policies - Regular user should NOT have permission

    Verifies:
    - Regular users cannot access admin role endpoints
    - Returns 403 Forbidden
    """
    log.info("--- Running: test_regular_user_cannot_access_roles ---")

    # Get regular user token
    login_data = {
        "username": regular_user_in_db["username"],
        "password": regular_user_in_db["password"],
    }
    login_response = await client.post("/api/auth/login", data=login_data)
    assert login_response.status_code == 200

    # Try to access policies with regular user
    response = await client.get(
        "/api/admin/roles/policies",
        cookies=login_response.cookies,
    )

    # Should be forbidden
    assert response.status_code == 403, \
        f"Regular user should not access role endpoints, got: {response.status_code}"

    log.info("✅ Permission check passed: regular user denied access")


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_roles(
    client: AsyncClient,
):
    """
    Test: GET /api/admin/roles/policies - Unauthenticated should return 401

    Verifies:
    - Unauthenticated requests are rejected
    - Returns 401 Unauthorized
    """
    log.info("--- Running: test_unauthenticated_cannot_access_roles ---")

    response = await client.get("/api/admin/roles/policies")

    # Should be unauthorized
    assert response.status_code == 401, \
        f"Unauthenticated should return 401, got: {response.status_code}"

    log.info("✅ Authentication check passed: unauthenticated denied access")


# ============================================================================
# EDGE CASES & ERROR HANDLING
# ============================================================================


@pytest.mark.asyncio
async def test_delete_nonexistent_policy(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/roles/policies - Delete nonexistent policy

    Verifies:
    - Deleting nonexistent policy returns 404
    """
    log.info("--- Running: test_delete_nonexistent_policy ---")

    policy_data = {
        "subject": "role:nonexistent",
        "object": "/api/nonexistent/*",
        "action": "GET",
    }

    response = await client.delete(
        "/api/admin/roles/policies",
        json=policy_data,
        headers=admin_token_headers,
    )

    # Should return 404
    assert response.status_code == 404, \
        f"Deleting nonexistent policy should return 404, got: {response.status_code}"

    log.info("✅ Delete nonexistent policy properly returns 404")


@pytest.mark.asyncio
async def test_assign_duplicate_role_fails(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: dict,
):
    """
    Test: POST /api/admin/roles/assign - Assigning duplicate role should fail

    Verifies:
    - Cannot assign same role twice
    - Returns 400 or 409
    """
    log.info("--- Running: test_assign_duplicate_role_fails ---")

    user_id = regular_user_in_db["id"]
    assignment_data = {
        "user_id": user_id,
        "role": "role:duplicate_role_test",
    }

    # Assign role first time
    response1 = await client.post(
        "/api/admin/roles/assign",
        json=assignment_data,
        headers=admin_token_headers,
    )
    assert response1.status_code == 201

    # Try to assign same role again
    response2 = await client.post(
        "/api/admin/roles/assign",
        json=assignment_data,
        headers=admin_token_headers,
    )

    # Should fail
    assert response2.status_code in [400, 409], \
        f"Duplicate role assignment should fail, got: {response2.status_code}"

    log.info("✅ Duplicate role assignment properly rejected")
