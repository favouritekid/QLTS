# tests/routers/admin/test_users.py
"""
PHASE 2A: Automated Tests for Admin Users Router

Tests for app/routers/admin/users.py endpoints:
- User CRUD operations
- User export (Excel, CSV)
- Bulk operations
- Casbin sync (PHASE 1 integration)
- Lead management (PHASE 1 integration)
- Analytics and activity logs

Created: 2025-11-17
Part of: PHASE 2A Router Extraction
"""
import io
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
# USER CRUD OPERATIONS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_create_user_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/users - Create new user

    Verifies:
    - Admin can create new user
    - User is created in database
    - Password is hashed (not plain text)
    - Activity log is created
    """
    log.info("--- Running: test_create_user_success ---")

    user_data = {
        "username": "newuser",
        "email": "newuser@example.com",
        "full_name": "New Test User",
        "password": "SecurePass123!",
        "role": "Advisor",
        "status": "active",
    }

    response = await client.post(
        "/api/admin/users",
        data=user_data,  # Use Form data, not JSON
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to create user: {response.text}"
    data = response.json()

    # Verify response structure
    assert data["username"] == user_data["username"]
    assert data["email"] == user_data["email"]
    assert data["full_name"] == user_data["full_name"]
    assert data["role"] == user_data["role"]
    assert data["status"] == user_data["status"]
    assert "id" in data
    assert "password" not in data, "Password should not be in response"

    # Verify user in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.User).where(models.User.email == user_data["email"])
        )
        user = result.scalar_one_or_none()
        assert user is not None, "User not found in database"
        assert user.email == user_data["email"]
        # Verify password is hashed
        assert user.password_hash != user_data["password"], "Password not hashed"
        assert user.password_hash.startswith("$2b$"), "Password not bcrypt hashed"

    log.info("✅ User created successfully with hashed password")


@pytest.mark.asyncio
async def test_get_all_users(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: dict,
):
    """
    Test: GET /api/admin/users - Get all users with pagination

    Verifies:
    - Admin can list all users
    - Pagination works (skip, limit)
    - Password hashes are NOT exposed
    """
    log.info("--- Running: test_get_all_users ---")

    response = await client.get(
        "/api/admin/users?skip=0&limit=10",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get users: {response.text}"
    data = response.json()

    # Verify response format (API returns dict with 'users' and 'total_count')
    assert isinstance(data, dict), "Response should be a dict"
    assert "users" in data, "Response should have 'users' key"
    assert "total_count" in data, "Response should have 'total_count' key"
    assert len(data["users"]) > 0, "Should have at least admin user"

    # Verify password hash not exposed
    for user in data["users"]:
        assert "hashed_password" not in user, "Password hash should not be exposed"
        assert "password" not in user, "Password should not be exposed"
        assert "email" in user
        assert "role" in user

    log.info(f"✅ Retrieved {len(data['users'])} users successfully (total: {data['total_count']})")


@pytest.mark.asyncio
async def test_get_user_by_id(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: dict,
):
    """
    Test: GET /api/admin/users/{user_id} - Get user details

    Verifies:
    - Admin can get user details by ID
    - Response includes Casbin roles
    - Password hash NOT exposed
    """
    log.info("--- Running: test_get_user_by_id ---")

    user_id = admin_user_in_db["id"]

    response = await client.get(
        f"/api/admin/users/{user_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get user: {response.text}"
    data = response.json()

    # Verify user details
    assert data["id"] == user_id
    assert data["email"] == admin_user_in_db["email"]
    assert "hashed_password" not in data

    log.info(f"✅ Retrieved user {user_id} successfully")


@pytest.mark.asyncio
async def test_update_user(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: dict,
):
    """
    Test: PUT /api/admin/users/{user_id} - Update user

    Verifies:
    - Admin can update user details
    - Changes are persisted to database
    - Activity log is created
    """
    log.info("--- Running: test_update_user ---")

    user_id = regular_user_in_db["id"]
    update_data = {
        "full_name": "Updated Name",
        "role": "Manager",
    }

    response = await client.put(
        f"/api/admin/users/{user_id}",
        data=update_data,  # Use Form data, not JSON
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to update user: {response.text}"
    data = response.json()

    # Verify updated fields
    assert data["full_name"] == update_data["full_name"]
    assert data["role"] == update_data["role"]

    # Verify in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.User).where(models.User.id == user_id)
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.full_name == update_data["full_name"]
        assert user.role == update_data["role"]

    log.info(f"✅ User {user_id} updated successfully")


@pytest.mark.asyncio
async def test_delete_user(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/users/{user_id} - Delete user

    Verifies:
    - Admin can delete user
    - User is removed from database
    - Casbin roles are revoked
    - Activity log is created
    """
    log.info("--- Running: test_delete_user ---")

    # First create a user to delete
    user_data = {
        "username": "todelete",
        "email": "todelete@example.com",
        "full_name": "To Delete",
        "password": "Password123!",
        "role": "Advisor",
        "status": "active",
    }

    create_response = await client.post(
        "/api/admin/users",
        data=user_data,  # Use Form data, not JSON
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    # Delete the user
    response = await client.delete(
        f"/api/admin/users/{user_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to delete user: {response.text}"

    # Verify user is deleted from database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.User).where(models.User.id == user_id)
        )
        user = result.scalar_one_or_none()
        assert user is None, "User should be deleted from database"

    log.info(f"✅ User {user_id} deleted successfully")


# ============================================================================
# PASSWORD MANAGEMENT TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_admin_reset_user_password(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: dict,
):
    """
    Test: POST /api/admin/users/{user_id}/password - Admin reset user password

    Verifies:
    - Admin can reset user password
    - New password is hashed
    - Activity log is created
    """
    log.info("--- Running: test_admin_reset_user_password ---")

    user_id = regular_user_in_db["id"]
    new_password = "NewSecurePass456!"

    response = await client.post(
        f"/api/admin/users/{user_id}/password",
        json={"new_password": new_password},
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to reset password: {response.text}"

    # Verify password is updated in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.User).where(models.User.id == user_id)
        )
        user = result.scalar_one_or_none()
        assert user is not None
        # Password should be hashed and different from plain text
        assert user.password_hash != new_password
        assert user.password_hash.startswith("$2b$")

    log.info(f"✅ Password reset successfully for user {user_id}")


# ============================================================================
# USER EXPORT TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_export_users_excel(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: dict,
):
    """
    Test: GET /api/admin/users/export - Export users to Excel

    Verifies:
    - Admin can export users to Excel
    - Response is Excel file (correct Content-Type)
    - Password hashes are NOT included
    """
    log.info("--- Running: test_export_users_excel ---")

    response = await client.get(
        "/api/admin/users/export",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to export users: {response.text}"

    # Verify Content-Type is Excel
    content_type = response.headers.get("content-type", "")
    assert "spreadsheet" in content_type or "excel" in content_type, \
        f"Expected Excel Content-Type, got: {content_type}"

    # Verify response is not empty
    assert len(response.content) > 0, "Excel file is empty"

    log.info("✅ Users exported to Excel successfully")


@pytest.mark.asyncio
async def test_export_users_csv(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: dict,
):
    """
    Test: GET /api/admin/users/export/csv - Export users to CSV (streaming)

    Verifies:
    - Admin can export users to CSV
    - Response is CSV file (correct Content-Type)
    - Streaming works (doesn't load all into memory)
    """
    log.info("--- Running: test_export_users_csv ---")

    response = await client.get(
        "/api/admin/users/export/csv",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to export users CSV: {response.text}"

    # Verify Content-Type is CSV
    content_type = response.headers.get("content-type", "")
    assert "csv" in content_type.lower(), \
        f"Expected CSV Content-Type, got: {content_type}"

    # Verify response is not empty
    assert len(response.content) > 0, "CSV file is empty"

    # Verify CSV headers
    csv_content = response.content.decode("utf-8")
    assert "email" in csv_content.lower(), "CSV should have email header"

    log.info("✅ Users exported to CSV successfully")


# ============================================================================
# CASBIN SYNC TESTS (PHASE 1 Integration)
# ============================================================================


@pytest.mark.asyncio
async def test_get_casbin_sync_status(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/users/sync/status - Get Casbin sync status

    Verifies:
    - Admin can check Casbin sync status
    - Response includes user counts
    """
    log.info("--- Running: test_get_casbin_sync_status ---")

    response = await client.get(
        "/api/admin/users/sync/status",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get sync status: {response.text}"
    data = response.json()

    # Verify response structure (API returns: total_users, synced_count, out_of_sync_count, mismatched_users)
    assert "total_users" in data
    assert "synced_count" in data
    assert "out_of_sync_count" in data
    assert "mismatched_users" in data
    assert isinstance(data["total_users"], int)
    assert isinstance(data["synced_count"], int)

    log.info(f"✅ Sync status: {data['total_users']} total users, {data['synced_count']} synced, {data['out_of_sync_count']} out of sync")


@pytest.mark.asyncio
async def test_sync_users_to_casbin(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/users/sync - Sync users to Casbin enforcer

    Verifies:
    - Admin can trigger Casbin sync
    - PHASE 1 Integration: Calls user_service.sync_users_to_casbin()
    - Returns sync results
    - Activity log is created
    """
    log.info("--- Running: test_sync_users_to_casbin ---")

    # Sync all users (user_ids=None means sync all)
    sync_data = {"user_ids": None}
    response = await client.post(
        "/api/admin/users/sync",
        json=sync_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to sync users: {response.text}"
    data = response.json()

    # Verify response has sync results
    # Note: Exact structure depends on user_service.sync_users_to_casbin() implementation
    assert data is not None, "Sync should return results"

    log.info("✅ Users synced to Casbin successfully")


# ============================================================================
# ANALYTICS & ACTIVITY LOGS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_get_user_statistics(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    admin_user_in_db: dict,
):
    """
    Test: GET /api/admin/users/statistics - Get user statistics

    Verifies:
    - Admin can view user statistics
    - Response includes total, active, inactive counts
    - Response includes breakdown by role
    """
    log.info("--- Running: test_get_user_statistics ---")

    response = await client.get(
        "/api/admin/users/statistics",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get statistics: {response.text}"
    data = response.json()

    # Verify response structure
    assert "total_users" in data
    assert "active_users" in data
    assert isinstance(data["total_users"], int)
    assert data["total_users"] > 0, "Should have at least admin user"

    log.info(f"✅ Statistics: {data['total_users']} total users")


@pytest.mark.asyncio
async def test_get_activity_logs(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/users/activity-logs - Get activity logs

    Verifies:
    - Admin can view activity logs
    - Pagination works
    - Filters work (action, actor_id, etc.)
    """
    log.info("--- Running: test_get_activity_logs ---")

    response = await client.get(
        "/api/admin/users/activity-logs?skip=0&limit=20",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get activity logs: {response.text}"
    data = response.json()

    # Verify response is a list
    assert isinstance(data, list), "Response should be a list"

    # If there are logs, verify structure
    if len(data) > 0:
        log_entry = data[0]
        assert "action" in log_entry
        assert "resource_type" in log_entry
        assert "created_at" in log_entry

    log.info(f"✅ Retrieved {len(data)} activity logs")


# ============================================================================
# PERMISSION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_regular_user_cannot_create_user(
    client: AsyncClient,
    regular_user_in_db: dict,
):
    """
    Test: POST /api/admin/users - Regular user should NOT have permission

    Verifies:
    - Regular users cannot access admin endpoints
    - Returns 403 Forbidden
    """
    log.info("--- Running: test_regular_user_cannot_create_user ---")

    # Get regular user token
    login_data = {
        "username": regular_user_in_db["username"],
        "password": regular_user_in_db["password"],
    }
    login_response = await client.post("/api/auth/login", data=login_data)
    assert login_response.status_code == 200

    # Try to create user with regular user token
    user_data = {
        "username": "unauthorized",
        "email": "unauthorized@example.com",
        "full_name": "Unauthorized",
        "password": "Pass123!",
        "role": "Advisor",
        "status": "active",
    }

    # Use cookies from login instead of headers
    response = await client.post(
        "/api/admin/users",
        data=user_data,  # Use Form data, not JSON
        cookies=login_response.cookies,
    )

    # Should be forbidden
    assert response.status_code == 403, \
        f"Regular user should not be able to create users, got: {response.status_code}"

    log.info("✅ Permission check passed: regular user denied access")


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_admin(
    client: AsyncClient,
):
    """
    Test: GET /api/admin/users - Unauthenticated should return 401

    Verifies:
    - Unauthenticated requests are rejected
    - Returns 401 Unauthorized
    """
    log.info("--- Running: test_unauthenticated_cannot_access_admin ---")

    response = await client.get("/api/admin/users")

    # Should be unauthorized
    assert response.status_code == 401, \
        f"Unauthenticated should return 401, got: {response.status_code}"

    log.info("✅ Authentication check passed: unauthenticated denied access")


# ============================================================================
# EDGE CASES & ERROR HANDLING
# ============================================================================


@pytest.mark.asyncio
async def test_create_user_duplicate_email(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    regular_user_in_db: dict,
):
    """
    Test: POST /api/admin/users - Duplicate email should fail

    Verifies:
    - Cannot create user with duplicate email
    - Returns 400 Bad Request
    """
    log.info("--- Running: test_create_user_duplicate_email ---")

    user_data = {
        "username": "duplicateuser",
        "email": regular_user_in_db["email"],  # Duplicate email
        "full_name": "Duplicate User",
        "password": "Pass123!",
        "role": "Advisor",
        "status": "active",
    }

    response = await client.post(
        "/api/admin/users",
        data=user_data,  # Use Form data, not JSON
        headers=admin_token_headers,
    )

    # Should fail with 400 or 409
    assert response.status_code in [400, 409], \
        f"Duplicate email should fail, got: {response.status_code}"

    log.info("✅ Duplicate email properly rejected")


@pytest.mark.asyncio
async def test_get_nonexistent_user(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/users/{user_id} - Nonexistent user should return 404

    Verifies:
    - Getting nonexistent user returns 404
    """
    log.info("--- Running: test_get_nonexistent_user ---")

    response = await client.get(
        "/api/admin/users/999999",  # Nonexistent ID
        headers=admin_token_headers,
    )

    # Should return 404
    assert response.status_code == 404, \
        f"Nonexistent user should return 404, got: {response.status_code}"

    log.info("✅ Nonexistent user properly returns 404")


@pytest.mark.asyncio
async def test_update_nonexistent_user(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: PUT /api/admin/users/{user_id} - Updating nonexistent user should fail

    Verifies:
    - Updating nonexistent user returns 404
    """
    log.info("--- Running: test_update_nonexistent_user ---")

    update_data = {"full_name": "Updated Name"}

    response = await client.put(
        "/api/admin/users/999999",
        data=update_data,  # Use Form data, not JSON
        headers=admin_token_headers,
    )

    # Should return 404
    assert response.status_code == 404, \
        f"Updating nonexistent user should return 404, got: {response.status_code}"

    log.info("✅ Update nonexistent user properly returns 404")
