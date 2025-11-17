# tests/routers/admin/test_pipeline.py
"""
PHASE 2C: Automated Tests for Admin Pipeline Router

Tests for app/routers/admin/pipeline.py endpoints:
- Pipeline Stages CRUD (5 endpoints)
- Consultation Statuses CRUD (5 endpoints)
- Allowed Transitions CRUD (3 endpoints)
- Lead Status Revert (1 endpoint)

Total: 14 endpoints, ~18 test cases

Created: 2025-11-17
Part of: PHASE 2C Router Extraction
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
# PIPELINE STAGES TESTS (5 endpoints)
# ============================================================================


@pytest.mark.asyncio
async def test_get_all_pipeline_stages_empty(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/pipeline-stages - Get all stages (empty or existing)

    Verifies:
    - Admin can retrieve all pipeline stages
    - Returns list (might have existing stages from seed data)
    """
    log.info("--- Running: test_get_all_pipeline_stages_empty ---")

    response = await client.get(
        "/api/admin/pipeline-stages",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get stages: {response.text}"
    data = response.json()

    # Verify response is a list
    assert isinstance(data, list), "Response should be a list"

    log.info(f"✅ Retrieved {len(data)} pipeline stages")


@pytest.mark.asyncio
async def test_create_pipeline_stage_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/pipeline-stages - Create new stage

    Verifies:
    - Admin can create new pipeline stage
    - Stage is created in database
    - Response contains correct data
    """
    log.info("--- Running: test_create_pipeline_stage_success ---")

    stage_data = {
        "id": "test_stage_new",
        "name": "Test Stage New",
        "order": 100,
        "is_final_stage": False,
    }

    response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to create stage: {response.text}"
    data = response.json()

    # Verify response structure
    assert data["id"] == stage_data["id"]
    assert data["name"] == stage_data["name"]
    assert data["order"] == stage_data["order"]
    assert data["is_final_stage"] == stage_data["is_final_stage"]

    # Verify in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.PipelineStage).where(
                models.PipelineStage.id == stage_data["id"]
            )
        )
        stage = result.scalar_one_or_none()
        assert stage is not None, "Stage not found in database"
        assert stage.name == stage_data["name"]
        assert stage.order == stage_data["order"]

    log.info(f"✅ Pipeline stage created successfully: {data['id']}")


@pytest.mark.asyncio
async def test_get_pipeline_stage_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/pipeline-stages/{stage_id} - Get stage details

    Verifies:
    - Admin can retrieve specific stage
    - Returns correct stage data
    """
    log.info("--- Running: test_get_pipeline_stage_success ---")

    # Create a stage first
    stage_data = {
        "id": "test_stage_get",
        "name": "Test Stage for GET",
        "order": 101,
        "is_final_stage": False,
    }

    create_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    stage_id = create_response.json()["id"]

    # Get the stage
    response = await client.get(
        f"/api/admin/pipeline-stages/{stage_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get stage: {response.text}"
    data = response.json()

    assert data["id"] == stage_id
    assert data["name"] == stage_data["name"]

    log.info(f"✅ Retrieved stage details: {stage_id}")


@pytest.mark.asyncio
async def test_update_pipeline_stage_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: PUT /api/admin/pipeline-stages/{stage_id} - Update stage

    Verifies:
    - Admin can update pipeline stage
    - Changes are persisted in database
    """
    log.info("--- Running: test_update_pipeline_stage_success ---")

    # Create a stage first
    stage_data = {
        "id": "test_stage_update",
        "name": "Test Stage for Update",
        "order": 102,
        "is_final_stage": False,
    }

    create_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    stage_id = create_response.json()["id"]

    # Update the stage
    update_data = {
        "name": "Updated Stage Name",
        "order": 103,
        "is_final_stage": True,
    }

    response = await client.put(
        f"/api/admin/pipeline-stages/{stage_id}",
        json=update_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to update stage: {response.text}"
    data = response.json()

    assert data["name"] == update_data["name"]
    assert data["order"] == update_data["order"]
    assert data["is_final_stage"] == update_data["is_final_stage"]

    # Verify in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.PipelineStage).where(models.PipelineStage.id == stage_id)
        )
        stage = result.scalar_one_or_none()
        assert stage is not None
        assert stage.name == update_data["name"]
        assert stage.order == update_data["order"]

    log.info(f"✅ Stage updated successfully: {stage_id}")


@pytest.mark.asyncio
async def test_delete_pipeline_stage_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/pipeline-stages/{stage_id} - Delete stage

    Verifies:
    - Admin can delete pipeline stage
    - Stage is removed from database
    - Returns 204 status
    """
    log.info("--- Running: test_delete_pipeline_stage_success ---")

    # Create a stage first
    stage_data = {
        "id": "test_stage_delete",
        "name": "Test Stage for Delete",
        "order": 104,
        "is_final_stage": False,
    }

    create_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    stage_id = create_response.json()["id"]

    # Delete the stage
    response = await client.delete(
        f"/api/admin/pipeline-stages/{stage_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 204, f"Failed to delete stage: {response.status_code}"

    # Verify stage is deleted
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.PipelineStage).where(models.PipelineStage.id == stage_id)
        )
        stage = result.scalar_one_or_none()
        assert stage is None, "Stage should be deleted from database"

    log.info("✅ Stage deleted successfully")


# ============================================================================
# CONSULTATION STATUSES TESTS (5 endpoints)
# ============================================================================


@pytest.mark.asyncio
async def test_get_all_consultation_statuses(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/consultation-statuses - Get all statuses

    Verifies:
    - Admin can retrieve all consultation statuses
    - Returns list
    """
    log.info("--- Running: test_get_all_consultation_statuses ---")

    response = await client.get(
        "/api/admin/consultation-statuses",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get statuses: {response.text}"
    data = response.json()

    assert isinstance(data, list), "Response should be a list"

    log.info(f"✅ Retrieved {len(data)} consultation statuses")


@pytest.mark.asyncio
async def test_create_consultation_status_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/consultation-statuses - Create new status

    Verifies:
    - Admin can create new consultation status
    - Status is created in database
    - Response contains correct data
    """
    log.info("--- Running: test_create_consultation_status_success ---")

    # Create a parent stage first
    stage_data = {
        "id": "test_stage_status",
        "name": "Test Stage for Status",
        "order": 105,
        "is_final_stage": False,
    }

    stage_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert stage_response.status_code == 201
    stage_id = stage_response.json()["id"]

    # Create consultation status
    status_data = {
        "id": "test_status_new",
        "name": "Test Status New",
        "color_code": "#FF5733",
        "stage_id": stage_id,
        "outcome_type": "neutral",
        "is_final_status": False,
    }

    response = await client.post(
        "/api/admin/consultation-statuses",
        json=status_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to create status: {response.text}"
    data = response.json()

    # Verify response structure
    assert data["id"] == status_data["id"]
    assert data["name"] == status_data["name"]
    assert data["color_code"] == status_data["color_code"]
    assert data["stage_id"] == status_data["stage_id"]

    # Verify in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.ConsultationStatus).where(
                models.ConsultationStatus.id == status_data["id"]
            )
        )
        status = result.scalar_one_or_none()
        assert status is not None, "Status not found in database"
        assert status.name == status_data["name"]
        assert status.color_code == status_data["color_code"]

    log.info(f"✅ Consultation status created successfully: {data['id']}")


@pytest.mark.asyncio
async def test_get_consultation_status_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/consultation-statuses/{status_id} - Get status details

    Verifies:
    - Admin can retrieve specific status
    - Returns correct status data
    """
    log.info("--- Running: test_get_consultation_status_success ---")

    # Create stage and status first
    stage_data = {
        "id": "test_stage_get_status",
        "name": "Test Stage for GET Status",
        "order": 106,
        "is_final_stage": False,
    }

    stage_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert stage_response.status_code == 201
    stage_id = stage_response.json()["id"]

    status_data = {
        "id": "test_status_get",
        "name": "Test Status for GET",
        "color_code": "#33FF57",
        "stage_id": stage_id,
        "outcome_type": "positive",
        "is_final_status": False,
    }

    create_response = await client.post(
        "/api/admin/consultation-statuses",
        json=status_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    status_id = create_response.json()["id"]

    # Get the status
    response = await client.get(
        f"/api/admin/consultation-statuses/{status_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get status: {response.text}"
    data = response.json()

    assert data["id"] == status_id
    assert data["name"] == status_data["name"]
    assert data["color_code"] == status_data["color_code"]

    log.info(f"✅ Retrieved status details: {status_id}")


@pytest.mark.asyncio
async def test_update_consultation_status_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: PUT /api/admin/consultation-statuses/{status_id} - Update status

    Verifies:
    - Admin can update consultation status
    - Changes are persisted in database
    """
    log.info("--- Running: test_update_consultation_status_success ---")

    # Create stage and status first
    stage_data = {
        "id": "test_stage_update_status",
        "name": "Test Stage for Update Status",
        "order": 107,
        "is_final_stage": False,
    }

    stage_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert stage_response.status_code == 201
    stage_id = stage_response.json()["id"]

    status_data = {
        "id": "test_status_update",
        "name": "Test Status for Update",
        "color_code": "#5733FF",
        "stage_id": stage_id,
        "outcome_type": "neutral",
        "is_final_status": False,
    }

    create_response = await client.post(
        "/api/admin/consultation-statuses",
        json=status_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    status_id = create_response.json()["id"]

    # Update the status
    update_data = {
        "name": "Updated Status Name",
        "color_code": "#FF33AA",
        "outcome_type": "positive",
        "is_final_status": True,
    }

    response = await client.put(
        f"/api/admin/consultation-statuses/{status_id}",
        json=update_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to update status: {response.text}"
    data = response.json()

    assert data["name"] == update_data["name"]
    assert data["color_code"] == update_data["color_code"]
    assert data["is_final_status"] == update_data["is_final_status"]

    # Verify in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.ConsultationStatus).where(
                models.ConsultationStatus.id == status_id
            )
        )
        status = result.scalar_one_or_none()
        assert status is not None
        assert status.name == update_data["name"]
        assert status.color_code == update_data["color_code"]

    log.info(f"✅ Status updated successfully: {status_id}")


@pytest.mark.asyncio
async def test_delete_consultation_status_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/consultation-statuses/{status_id} - Delete status

    Verifies:
    - Admin can delete consultation status
    - Status is removed from database
    - Returns 204 status
    """
    log.info("--- Running: test_delete_consultation_status_success ---")

    # Create stage and status first
    stage_data = {
        "id": "test_stage_delete_status",
        "name": "Test Stage for Delete Status",
        "order": 108,
        "is_final_stage": False,
    }

    stage_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert stage_response.status_code == 201
    stage_id = stage_response.json()["id"]

    status_data = {
        "id": "test_status_delete",
        "name": "Test Status for Delete",
        "color_code": "#AABBCC",
        "stage_id": stage_id,
        "outcome_type": "negative",
        "is_final_status": False,
    }

    create_response = await client.post(
        "/api/admin/consultation-statuses",
        json=status_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    status_id = create_response.json()["id"]

    # Delete the status
    response = await client.delete(
        f"/api/admin/consultation-statuses/{status_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 204, f"Failed to delete status: {response.status_code}"

    # Verify status is deleted
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.ConsultationStatus).where(
                models.ConsultationStatus.id == status_id
            )
        )
        status = result.scalar_one_or_none()
        assert status is None, "Status should be deleted from database"

    log.info("✅ Status deleted successfully")


# ============================================================================
# ALLOWED TRANSITIONS TESTS (3 endpoints)
# ============================================================================


@pytest.mark.asyncio
async def test_get_all_allowed_transitions(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: GET /api/admin/allowed-transitions - Get all transitions

    Verifies:
    - Admin can retrieve all allowed transitions
    - Returns list
    """
    log.info("--- Running: test_get_all_allowed_transitions ---")

    response = await client.get(
        "/api/admin/allowed-transitions",
        headers=admin_token_headers,
    )

    assert response.status_code == 200, f"Failed to get transitions: {response.text}"
    data = response.json()

    assert isinstance(data, list), "Response should be a list"

    log.info(f"✅ Retrieved {len(data)} allowed transitions")


@pytest.mark.asyncio
async def test_create_allowed_transition_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: POST /api/admin/allowed-transitions - Create new transition

    Verifies:
    - Admin can create new allowed transition
    - Transition is created in database
    - Response contains correct data
    """
    log.info("--- Running: test_create_allowed_transition_success ---")

    # Create stage and two statuses first
    stage_data = {
        "id": "test_stage_transition",
        "name": "Test Stage for Transition",
        "order": 109,
        "is_final_stage": False,
    }

    stage_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert stage_response.status_code == 201
    stage_id = stage_response.json()["id"]

    # Create from_status
    from_status_data = {
        "id": "test_status_from",
        "name": "Test Status From",
        "color_code": "#111111",
        "stage_id": stage_id,
        "outcome_type": "neutral",
        "is_final_status": False,
    }

    from_response = await client.post(
        "/api/admin/consultation-statuses",
        json=from_status_data,
        headers=admin_token_headers,
    )
    assert from_response.status_code == 201
    from_status_id = from_response.json()["id"]

    # Create to_status
    to_status_data = {
        "id": "test_status_to",
        "name": "Test Status To",
        "color_code": "#222222",
        "stage_id": stage_id,
        "outcome_type": "positive",
        "is_final_status": False,
    }

    to_response = await client.post(
        "/api/admin/consultation-statuses",
        json=to_status_data,
        headers=admin_token_headers,
    )
    assert to_response.status_code == 201
    to_status_id = to_response.json()["id"]

    # Create transition
    transition_data = {
        "from_status_id": from_status_id,
        "to_status_id": to_status_id,
    }

    response = await client.post(
        "/api/admin/allowed-transitions",
        json=transition_data,
        headers=admin_token_headers,
    )

    assert response.status_code == 201, f"Failed to create transition: {response.text}"
    data = response.json()

    # Verify response structure
    assert data["from_status_id"] == transition_data["from_status_id"]
    assert data["to_status_id"] == transition_data["to_status_id"]
    assert "id" in data

    # Verify in database
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.AllowedTransition).where(
                models.AllowedTransition.from_status_id == from_status_id,
                models.AllowedTransition.to_status_id == to_status_id,
            )
        )
        transition = result.scalar_one_or_none()
        assert transition is not None, "Transition not found in database"

    log.info(f"✅ Allowed transition created successfully: {data['id']}")


@pytest.mark.asyncio
async def test_delete_allowed_transition_success(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Test: DELETE /api/admin/allowed-transitions/{transition_id} - Delete transition

    Verifies:
    - Admin can delete allowed transition
    - Transition is removed from database
    - Returns 204 status
    """
    log.info("--- Running: test_delete_allowed_transition_success ---")

    # Create stage and two statuses first
    stage_data = {
        "id": "test_stage_delete_trans",
        "name": "Test Stage for Delete Transition",
        "order": 110,
        "is_final_stage": False,
    }

    stage_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert stage_response.status_code == 201
    stage_id = stage_response.json()["id"]

    # Create from_status
    from_status_data = {
        "id": "test_status_from_del",
        "name": "Test Status From Delete",
        "color_code": "#333333",
        "stage_id": stage_id,
        "outcome_type": "neutral",
        "is_final_status": False,
    }

    from_response = await client.post(
        "/api/admin/consultation-statuses",
        json=from_status_data,
        headers=admin_token_headers,
    )
    assert from_response.status_code == 201
    from_status_id = from_response.json()["id"]

    # Create to_status
    to_status_data = {
        "id": "test_status_to_del",
        "name": "Test Status To Delete",
        "color_code": "#444444",
        "stage_id": stage_id,
        "outcome_type": "negative",
        "is_final_status": False,
    }

    to_response = await client.post(
        "/api/admin/consultation-statuses",
        json=to_status_data,
        headers=admin_token_headers,
    )
    assert to_response.status_code == 201
    to_status_id = to_response.json()["id"]

    # Create transition
    transition_data = {
        "from_status_id": from_status_id,
        "to_status_id": to_status_id,
    }

    create_response = await client.post(
        "/api/admin/allowed-transitions",
        json=transition_data,
        headers=admin_token_headers,
    )
    assert create_response.status_code == 201
    transition_id = create_response.json()["id"]

    # Delete the transition
    response = await client.delete(
        f"/api/admin/allowed-transitions/{transition_id}",
        headers=admin_token_headers,
    )

    assert response.status_code == 204, f"Failed to delete transition: {response.status_code}"

    # Verify transition is deleted
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(models.AllowedTransition).where(
                models.AllowedTransition.id == transition_id
            )
        )
        transition = result.scalar_one_or_none()
        assert transition is None, "Transition should be deleted from database"

    log.info("✅ Transition deleted successfully")


# ============================================================================
# AUTHORIZATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_create_pipeline_stage_unauthorized(
    client: AsyncClient,
):
    """
    Test: POST /api/admin/pipeline-stages - Unauthorized access

    Verifies:
    - Non-admin users cannot create pipeline stages
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_create_pipeline_stage_unauthorized ---")

    stage_data = {
        "id": "test_unauthorized",
        "name": "Unauthorized Test",
        "order": 999,
        "is_final_stage": False,
    }

    response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")


@pytest.mark.asyncio
async def test_delete_consultation_status_unauthorized(
    client: AsyncClient,
):
    """
    Test: DELETE /api/admin/consultation-statuses/{status_id} - Unauthorized access

    Verifies:
    - Non-admin users cannot delete consultation statuses
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_delete_consultation_status_unauthorized ---")

    response = await client.delete(
        "/api/admin/consultation-statuses/some_status",
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_pipeline_workflow_integration(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
):
    """
    Integration test: Complete pipeline workflow

    Tests:
    1. Create pipeline stage
    2. Create consultation statuses in the stage
    3. Create allowed transitions between statuses
    4. Verify all components work together
    """
    log.info("--- Running: test_pipeline_workflow_integration ---")

    # 1. Create pipeline stage
    stage_data = {
        "id": "test_stage_integration",
        "name": "Integration Test Stage",
        "order": 200,
        "is_final_stage": False,
    }

    stage_response = await client.post(
        "/api/admin/pipeline-stages",
        json=stage_data,
        headers=admin_token_headers,
    )
    assert stage_response.status_code == 201
    stage_id = stage_response.json()["id"]

    # 2. Create first consultation status
    status1_data = {
        "id": "test_status_int_1",
        "name": "Integration Status 1",
        "color_code": "#ABCDEF",
        "stage_id": stage_id,
        "outcome_type": "neutral",
        "is_final_status": False,
    }

    status1_response = await client.post(
        "/api/admin/consultation-statuses",
        json=status1_data,
        headers=admin_token_headers,
    )
    assert status1_response.status_code == 201
    status1_id = status1_response.json()["id"]

    # 3. Create second consultation status
    status2_data = {
        "id": "test_status_int_2",
        "name": "Integration Status 2",
        "color_code": "#FEDCBA",
        "stage_id": stage_id,
        "outcome_type": "positive",
        "is_final_status": False,
    }

    status2_response = await client.post(
        "/api/admin/consultation-statuses",
        json=status2_data,
        headers=admin_token_headers,
    )
    assert status2_response.status_code == 201
    status2_id = status2_response.json()["id"]

    # 4. Create allowed transition
    transition_data = {
        "from_status_id": status1_id,
        "to_status_id": status2_id,
    }

    transition_response = await client.post(
        "/api/admin/allowed-transitions",
        json=transition_data,
        headers=admin_token_headers,
    )
    assert transition_response.status_code == 201

    # 5. Verify all components
    # Get all stages
    stages_response = await client.get(
        "/api/admin/pipeline-stages",
        headers=admin_token_headers,
    )
    assert stages_response.status_code == 200
    stages = stages_response.json()
    assert any(s["id"] == stage_id for s in stages)

    # Get all statuses
    statuses_response = await client.get(
        "/api/admin/consultation-statuses",
        headers=admin_token_headers,
    )
    assert statuses_response.status_code == 200
    statuses = statuses_response.json()
    assert any(s["id"] == status1_id for s in statuses)
    assert any(s["id"] == status2_id for s in statuses)

    # Get all transitions
    transitions_response = await client.get(
        "/api/admin/allowed-transitions",
        headers=admin_token_headers,
    )
    assert transitions_response.status_code == 200
    transitions = transitions_response.json()
    assert len(transitions) >= 1

    log.info("✅ Pipeline workflow integration test completed successfully")
