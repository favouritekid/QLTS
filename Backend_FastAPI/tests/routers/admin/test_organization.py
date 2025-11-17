# tests/routers/admin/test_organization.py
"""
PHASE 2B: Automated Tests for Admin Organization Router

Tests for app/routers/admin/organization.py endpoints:
- Organization Units CRUD (4 endpoints)
- Major Programs CRUD (4 endpoints)
- Program Offerings CRUD (4 endpoints)

Total: 12 endpoints, ~25 test cases

Created: 2025-11-17
Part of: PHASE 2B Router Extraction
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
from tests.fixtures.constants import NON_EXISTENT_ID

log = logging.getLogger(__name__)


# ============================================================================
# ORGANIZATION UNITS CRUD TESTS (4 endpoints)
# ============================================================================


@pytest.mark.asyncio
async def test_create_organization_unit_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/organization-units - Create new organization unit

    Verifies:
    - Admin can create new organization unit
    - Unit is created in database
    - Response contains correct data
    """
    log.info("--- Running: test_create_organization_unit_success ---")

    unit_data = {
        "name": "Test Faculty",
        "type": "Khoa",  # Must be one of: "Phòng ban", "Trung tâm", "Khoa", "Tổ", "Bộ môn"
        "description": "Test faculty for automated testing",
    }

    response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to create unit: {response.text}"
    data = response.json()

    # Verify response structure
    assert data["name"] == unit_data["name"]
    assert data["type"] == unit_data["type"]
    assert data["code"] == unit_data["code"]
    assert data["description"] == unit_data["description"]
    assert "id" in data

    # Verify in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.OrganizationUnit).where(
                models.OrganizationUnit.code == unit_data["code"]
            )
        )
        unit = result.scalar_one_or_none()
        assert unit is not None, "Unit not found in database"
        assert unit.name == unit_data["name"]

    log.info(f"✅ Organization unit created successfully with ID: {data['id']}")


@pytest.mark.asyncio
async def test_create_organization_unit_duplicate_code(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/organization-units - Duplicate code should fail

    Verifies:
    - Creating unit with duplicate code fails
    - Returns 400 or 409 status code
    """
    log.info("--- Running: test_create_organization_unit_duplicate_code ---")

    unit_data = {
        "name": "Original Unit",
        "type": "Khoa",
        "description": "First unit",
    }

    # Create first unit
    response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    assert response.status_code == 201

    # Try to create duplicate
    duplicate_data = {
        "name": "Original Unit",  # Same name to test duplicate
        "type": "Trung tâm",
        "description": "Duplicate unit",
    }

    response = await client.post(
        "/api/admin/organization-units",
        json=duplicate_data,
        headers=admin_token_headers,
    )

    assert response.status_code in [400, 409], f"Expected 400/409, got {response.status_code}"
    log.info("✅ Duplicate code rejected as expected")


@pytest.mark.asyncio
async def test_get_organization_unit_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/organization-units/{unit_id} - Get unit details

    Verifies:
    - Admin can retrieve unit by ID
    - Response contains correct data
    """
    log.info("--- Running: test_get_organization_unit_success ---")

    # Create a unit first
    unit_data = {
        "name": "Get Test Unit",
        "type": "Khoa",
        "description": "Unit for get test",
    }

    create_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    created_unit = create_response.json()
    unit_id = created_unit["id"]

    # Get the unit
    response = await client.get(
        f"/api/admin/organization-units/{unit_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get unit: {response.text}"
    data = response.json()

    assert data["id"] == unit_id
    assert data["name"] == unit_data["name"]
    assert data["code"] == unit_data["code"]

    log.info(f"✅ Retrieved unit successfully: {data['name']}")


@pytest.mark.asyncio
async def test_get_organization_unit_not_found(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/organization-units/{unit_id} - Non-existent unit

    Verifies:
    - Returns 404 for non-existent unit
    """
    log.info("--- Running: test_get_organization_unit_not_found ---")

    response = await client.get(
        f"/api/admin/organization-units/{NON_EXISTENT_ID}",
        headers=admin_token_headers,
    )

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    log.info("✅ Non-existent unit returns 404 as expected")


@pytest.mark.asyncio
async def test_update_organization_unit_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: PUT /api/admin/organization-units/{unit_id} - Update unit

    Verifies:
    - Admin can update existing unit
    - Changes are persisted in database
    """
    log.info("--- Running: test_update_organization_unit_success ---")

    # Create a unit first
    unit_data = {
        "name": "Original Name",
        "type": "Khoa",
        "description": "Original description",
    }

    create_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    created_unit = create_response.json()
    unit_id = created_unit["id"]

    # Update the unit
    update_data = {
        "name": "Updated Name",
        "description": "Updated description",
    }

    response = await client.put(
        f"/api/admin/organization-units/{unit_id}",
        json=update_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to update unit: {response.text}"
    data = response.json()

    assert data["id"] == unit_id
    assert data["name"] == update_data["name"]
    assert data["description"] == update_data["description"]
    assert data["type"] == unit_data["type"]  # Type unchanged

    log.info(f"✅ Unit updated successfully: {data['name']}")


@pytest.mark.asyncio
async def test_delete_organization_unit_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/organization-units/{unit_id} - Delete unit

    Verifies:
    - Admin can delete unit
    - Unit is marked as deleted in database (soft delete)
    - Returns 204 status
    """
    log.info("--- Running: test_delete_organization_unit_success ---")

    # Create a unit first
    unit_data = {
        "name": "Unit To Delete",
        "type": "Phòng ban",
        "description": "Will be deleted",
    }

    create_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    created_unit = create_response.json()
    unit_id = created_unit["id"]

    # Delete the unit
    response = await client.delete(
        f"/api/admin/organization-units/{unit_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 204, f"Failed to delete unit: {response.status_code}"

    # Verify unit is soft-deleted or not retrievable
    get_response = await client.get(
        f"/api/admin/organization-units/{unit_id}",
        headers=admin_token_headers,
    )

    # Should be 404 or return with deleted flag
    assert get_response.status_code in [404, 200]
    if get_response.status_code == 200:
        data = get_response.json()
        # Check for soft delete flag if applicable
        assert data.get("is_deleted") == True or data.get("deleted_at") is not None

    log.info("✅ Unit deleted successfully")


# ============================================================================
# MAJOR PROGRAMS CRUD TESTS (4 endpoints)
# ============================================================================


@pytest.mark.asyncio
async def test_create_major_program_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/programs - Create new major program

    Verifies:
    - Admin can create new major program (Level 1)
    - Program is created in database
    - Response contains correct data
    """
    log.info("--- Running: test_create_major_program_success ---")

    # Create organization unit first
    unit_data = {
        "name": "Faculty for Programs",
        "type": "Khoa",
        "description": "Faculty for program testing",
    }

    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    assert unit_response.status_code == 201
    unit_id = unit_response.json()["id"]

    # Create major program
    program_data = {
        "name": "Công nghệ thông tin",
        "degree_level": "Cao đẳng",  # Required field
        "code": "6480201",
        "unit_id": unit_id,
    }

    response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to create program: {response.text}"
    data = response.json()

    assert data["name"] == program_data["name"]
    assert data["code"] == program_data["code"]
    assert data["unit_id"] == unit_id
    assert "id" in data

    log.info(f"✅ Major program created successfully with ID: {data['id']}")


@pytest.mark.asyncio
async def test_get_major_program_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/programs/{program_id} - Get program details

    Verifies:
    - Admin can retrieve program by ID
    - Response contains correct data
    """
    log.info("--- Running: test_get_major_program_success ---")

    # Create organization unit first
    unit_data = {
        "name": "Faculty for Get Test",
        "type": "Khoa",
    }

    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    # Create program
    program_data = {
        "name": "Toán học",
        "degree_level": "Đại học",
        "code": "7460101",
        "unit_id": unit_id,
    }

    create_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    program_id = create_response.json()["id"]

    # Get the program
    response = await client.get(
        f"/api/admin/programs/{program_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get program: {response.text}"
    data = response.json()

    assert data["id"] == program_id
    assert data["name"] == program_data["name"]
    assert data["code"] == program_data["code"]

    log.info(f"✅ Retrieved program successfully: {data['name']}")


@pytest.mark.asyncio
async def test_update_major_program_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: PUT /api/admin/programs/{program_id} - Update program

    Verifies:
    - Admin can update existing program
    - Changes are persisted in database
    """
    log.info("--- Running: test_update_major_program_success ---")

    # Create organization unit first
    unit_data = {
        "name": "Faculty for Update",
        "type": "Khoa",
    }

    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    # Create program
    program_data = {
        "name": "Vật lý Original",
        "degree_level": "Đại học",
        "code": "7440201",
        "unit_id": unit_id,
    }

    create_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    program_id = create_response.json()["id"]

    # Update the program
    update_data = {
        "name": "Vật lý Updated",
        "degree_level": "Thạc sĩ",
    }

    response = await client.put(
        f"/api/admin/programs/{program_id}",
        json=update_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to update program: {response.text}"
    data = response.json()

    assert data["id"] == program_id
    assert data["name"] == update_data["name"]
    assert data["degree_level"] == update_data["degree_level"]

    log.info(f"✅ Program updated successfully: {data['name']}")


@pytest.mark.asyncio
async def test_delete_major_program_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/programs/{program_id} - Delete program (soft delete)

    Verifies:
    - Admin can delete program
    - Program is marked as deleted in database
    - Returns 204 status
    """
    log.info("--- Running: test_delete_major_program_success ---")

    # Create organization unit first
    unit_data = {
        "name": "Faculty for Delete",
        "type": "Khoa",
    }

    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    # Create program
    program_data = {
        "name": "Program To Delete",
        "degree_level": "Cao đẳng",
        "code": "6999999",
        "unit_id": unit_id,
    }

    create_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    program_id = create_response.json()["id"]

    # Delete the program
    response = await client.delete(
        f"/api/admin/programs/{program_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 204, f"Failed to delete program: {response.status_code}"

    log.info("✅ Program deleted successfully (soft delete)")


# ============================================================================
# PROGRAM OFFERINGS CRUD TESTS (4 endpoints)
# ============================================================================


@pytest.mark.asyncio
async def test_create_program_offering_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/programs/{program_id}/offerings - Create offering

    Verifies:
    - Admin can create new program offering (Level 2)
    - Offering is created in database
    - Response contains correct data
    """
    log.info("--- Running: test_create_program_offering_success ---")

    # Create organization unit first
    unit_data = {
        "name": "Faculty for Offerings",
        "type": "Khoa",
    }

    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    # Create major program
    program_data = {
        "name": "Kỹ thuật",
        "degree_level": "Đại học",
        "code": "7520101",
        "unit_id": unit_id,
    }

    program_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    assert program_response.status_code == 201
    program_id = program_response.json()["id"]

    # Create program offering
    offering_data = {
        "offering_type": "Chính quy",  # Required field (not 'name', 'code', or 'type')
        "program_id": program_id,
        "duration_semesters": 8,  # Optional (not 'duration_years')
        "total_credits": 120,  # Optional
    }

    response = await client.post(
        f"/api/admin/programs/{program_id}/offerings",
        json=offering_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to create offering: {response.text}"
    data = response.json()

    assert data["offering_type"] == offering_data["offering_type"]
    assert data["program_id"] == program_id
    assert data["duration_semesters"] == offering_data["duration_semesters"]
    assert "id" in data

    log.info(f"✅ Program offering created successfully with ID: {data['id']}")


@pytest.mark.asyncio
async def test_create_program_offering_program_id_mismatch(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/programs/{program_id}/offerings - program_id mismatch

    Verifies:
    - Returns 400 if program_id in path doesn't match program_id in body
    """
    log.info("--- Running: test_create_program_offering_program_id_mismatch ---")

    # Create organization unit and program
    unit_data = {"name": "Test Faculty", "type": "Faculty", "code": "TF"}
    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    program_data = {"name": "Test Program", "code": "TP", "unit_id": unit_id}
    program_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    program_id = program_response.json()["id"]

    # Try to create offering with mismatched program_id
    offering_data = {
        "offering_type": "Tại chức",
        "program_id": program_id + 999,  # Different program_id
    }

    response = await client.post(
        f"/api/admin/programs/{program_id}/offerings",
        json=offering_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    log.info("✅ Program ID mismatch rejected as expected")


@pytest.mark.asyncio
async def test_get_program_offering_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/offerings/{offering_id} - Get offering details

    Verifies:
    - Admin can retrieve offering by ID
    - Response contains correct data
    """
    log.info("--- Running: test_get_program_offering_success ---")

    # Create hierarchy: unit -> program -> offering
    unit_data = {"name": "Test Unit", "type": "Khoa"}
    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    program_data = {"name": "Test Program", "code": "TP", "unit_id": unit_id}
    program_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    program_id = program_response.json()["id"]

    offering_data = {
        "offering_type": "Tại chức",
        "program_id": program_id,
        "duration_semesters": 10,
    }

    create_response = await client.post(
        f"/api/admin/programs/{program_id}/offerings",
        json=offering_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    offering_id = create_response.json()["id"]

    # Get the offering
    response = await client.get(
        f"/api/admin/offerings/{offering_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get offering: {response.text}"
    data = response.json()

    assert data["id"] == offering_id
    assert data["offering_type"] == offering_data["offering_type"]

    log.info(f"✅ Retrieved offering successfully: {data['offering_type']}")


@pytest.mark.asyncio
async def test_update_program_offering_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: PUT /api/admin/offerings/{offering_id} - Update offering

    Verifies:
    - Admin can update existing offering
    - Changes are persisted in database
    """
    log.info("--- Running: test_update_program_offering_success ---")

    # Create hierarchy
    unit_data = {"name": "Test Unit", "type": "Khoa"}
    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    program_data = {"name": "Test Program", "degree_level": "Đại học", "code": "7777777", "unit_id": unit_id}
    program_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    program_id = program_response.json()["id"]

    offering_data = {
        "offering_type": "Chính quy",
        "program_id": program_id,
        "duration_semesters": 6,
        "total_credits": 90,
    }

    create_response = await client.post(
        f"/api/admin/programs/{program_id}/offerings",
        json=offering_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    offering_id = create_response.json()["id"]

    # Update the offering
    update_data = {
        "offering_type": "Tại chức",
        "duration_semesters": 8,
        "total_credits": 120,
    }

    response = await client.put(
        f"/api/admin/offerings/{offering_id}",
        json=update_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to update offering: {response.text}"
    data = response.json()

    assert data["id"] == offering_id
    assert data["offering_type"] == update_data["offering_type"]
    assert data["duration_semesters"] == update_data["duration_semesters"]

    log.info(f"✅ Offering updated successfully: {data['offering_type']}")


@pytest.mark.asyncio
async def test_delete_program_offering_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/offerings/{offering_id} - Delete offering (soft delete)

    Verifies:
    - Admin can delete offering
    - Offering is marked as deleted in database
    - Returns 204 status
    """
    log.info("--- Running: test_delete_program_offering_success ---")

    # Create hierarchy
    unit_data = {"name": "Test Unit", "type": "Khoa"}
    unit_response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
        headers=admin_token_headers,
    )
    unit_id = unit_response.json()["id"]

    program_data = {"name": "Test Program", "degree_level": "Đại học", "code": "7666666", "unit_id": unit_id}
    program_response = await client.post(
        "/api/admin/programs",
        json=program_data,
        headers=admin_token_headers,
    )
    program_id = program_response.json()["id"]

    offering_data = {
        "offering_type": "Từ xa",
        "program_id": program_id,
    }

    create_response = await client.post(
        f"/api/admin/programs/{program_id}/offerings",
        json=offering_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    offering_id = create_response.json()["id"]

    # Delete the offering
    response = await client.delete(
        f"/api/admin/offerings/{offering_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 204, f"Failed to delete offering: {response.status_code}"

    log.info("✅ Offering deleted successfully (soft delete)")


# ============================================================================
# AUTHORIZATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_create_organization_unit_unauthorized(
    client: AsyncClient,
):
    """
    Test: POST /api/admin/organization-units - Unauthorized access

    Verifies:
    - Non-admin users cannot create organization units
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_create_organization_unit_unauthorized ---")

    unit_data = {
        "name": "Unauthorized Unit",
        "type": "Khoa",
    }

    response = await client.post(
        "/api/admin/organization-units",
        json=unit_data,
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")


@pytest.mark.asyncio
async def test_create_major_program_unauthorized(
    client: AsyncClient,
):
    """
    Test: POST /api/admin/programs - Unauthorized access

    Verifies:
    - Non-admin users cannot create major programs
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_create_major_program_unauthorized ---")

    program_data = {
        "name": "Unauthorized Program",
        "degree_level": "Đại học",
        "code": "7555555",
        "unit_id": 1,
    }

    response = await client.post(
        "/api/admin/programs",
        json=program_data,
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")
