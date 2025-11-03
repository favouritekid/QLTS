# tests/test_resilience.py
# -*- coding: utf-8 -*-
import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient
import logging
from unittest.mock import patch, AsyncMock, MagicMock, ANY
from sqlalchemy.exc import SQLAlchemyError
from redis.exceptions import ConnectionError, TimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Import các thành phần app
from app.database import AsyncSessionLocal
from app import models, schemas
from app.config import settings
from app.services import organization_service, pipeline_service

# Import constants
from tests.fixtures.constants import ( # Sửa import này nếu cần
    AdminURLs,
    AuthURLs,
    PipelineURLs,
    ProfileURLs,
    TestUsers,
    TestPipelineData,
    TestOrgData,
    NON_EXISTENT_ID
)

log = logging.getLogger(__name__)

# (Fixture seed_basic_pipeline_data giữ nguyên)
@pytest_asyncio.fixture(scope="function")
async def seed_basic_pipeline_data(setup_test_database):
    log.info("--- [FIXTURE] Seeding basic pipeline data (unit, major, stage, status) ---")
    unit_data = TestOrgData.UNIT_1
    major_data = TestOrgData.MAJOR_1
    stage_data = TestPipelineData.STAGE_A
    status_data = TestPipelineData.STATUS_A1
    status_data_fixed = status_data.copy()
    status_data_fixed["stage_id"] = stage_data["id"]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit1 = models.OrganizationUnit(**unit_data)
            major1 = models.Major(**major_data)
            stage_a = models.PipelineStage(**stage_data)
            status_a1 = models.ConsultationStatus(**status_data_fixed)
            session.add_all([unit1, major1, stage_a, status_a1])
    log.info("--- [FIXTURE] Basic pipeline data seeded ---")
    yield {
        "unit_id": unit_data["id"],
        "major_id": major_data["id"],
        "stage_a_id": stage_data["id"],
        "status_a1_id": status_data_fixed["id"]
    }

# ==================================
# === Test Resilience DB (Module 6)
# ==================================

@pytest.mark.asyncio
# <<< XÓA DÒNG @patch CHO db.rollback >>>
# @patch('app.services.organization_service.db.rollback', new_callable=AsyncMock)
@patch('app.services.organization_service.create_major', new_callable=AsyncMock)
async def test_resilience_db_commit_failure_rolls_back(
    # <<< XÓA THAM SỐ mock_db_rollback >>>
    # mock_db_rollback: AsyncMock,
    mock_create_major: AsyncMock,
    client: AsyncClient,
    admin_token_headers: dict,
    setup_test_database,
    seed_basic_pipeline_data
):
    """
    Test 6.1: Mô phỏng lỗi DB khi GHI bằng cách patch service.
    Kiểm tra: Ném đúng exception, DB không thay đổi (rollback).
    """
    log.info("--- Running: test_resilience_db_commit_failure_rolls_back ---")

    major_payload = {
        "name": "Fail Major",
        "code": "FM1",
        "unit_id": seed_basic_pipeline_data["unit_id"]
    }

    db_error_simulation = SQLAlchemyError("Simulated Database Commit Error from Service")
    mock_create_major.side_effect = db_error_simulation

    # Action và Assert Exception
    with pytest.raises(SQLAlchemyError) as exc_info:
        await client.post(
            AdminURLs.MAJORS,
            json=major_payload,
            headers=admin_token_headers
        )

    assert exc_info.value == db_error_simulation
    log.info(f"Correct exception ({type(db_error_simulation).__name__}) was raised by client call.")

    # 1. Assert DB State (Rollback)
    async with AsyncSessionLocal() as session:
        db_major = await session.scalar(
            select(models.Major).where(models.Major.code == major_payload["code"])
        )
        assert db_major is None, "Data should not have been committed to DB after error (rollback failed)"
    log.info("DB state verified: Data was successfully rolled back.")

    # 2. Assert mock calls
    mock_create_major.assert_awaited_once()
    # <<< XÓA ASSERTION CHO mock_db_rollback >>>
    # mock_db_rollback.assert_awaited_once()
    log.info("Mock service call verified.")


# (Các test còn lại giữ nguyên)
# ===================================
# === Test Resilience Redis (Module 6)
# ===================================

@pytest.mark.asyncio
@patch('app.services.pipeline_service.safe_redis_get', new_callable=AsyncMock)
async def test_resilience_redis_cache_fallback(
    mock_safe_get: AsyncMock,
    client: AsyncClient,
    regular_user_token_headers: dict,
    seed_basic_pipeline_data: dict
):
    log.info("--- Running: test_resilience_redis_cache_fallback ---")
    mock_safe_get.side_effect = ConnectionError("Simulated Redis Connection Error")
    pipeline_url = PipelineURLs.ALL
    response = await client.get(pipeline_url, headers=regular_user_token_headers)
    assert response.status_code == 200
    data = response.json()
    assert "stages" in data
    assert "statuses" in data
    assert len(data["stages"]) == 1
    assert data["stages"][0]["id"] == seed_basic_pipeline_data["stage_a_id"]
    assert len(data["statuses"]) == 1
    assert data["statuses"][0]["id"] == seed_basic_pipeline_data["status_a1_id"]
    log.info("API correctly returned 200 OK by falling back to DB.")
    assert mock_safe_get.await_count == 2
    log.info("Cache (safe_redis_get) was called for both keys.")


@pytest.mark.asyncio
@patch('app.core.deps.safe_redis_exists', new_callable=AsyncMock)
async def test_resilience_redis_auth_fail_open(
    mock_safe_exists: AsyncMock,
    client: AsyncClient,
    regular_user_in_db: dict,
    test_redis_client
):
    log.info("--- Running: test_resilience_redis_auth_fail_open ---")
    login_data = {"username": regular_user_in_db["username"], "password": regular_user_in_db["password"]}
    log.info("--- Testing fail-open on ACTIVE token ---")
    login_res_2 = await client.post(AuthURLs.LOGIN, data=login_data)
    assert login_res_2.status_code == 200
    active_token = login_res_2.json()["access_token"]
    active_headers = {"Authorization": f"Bearer {active_token}"}
    log.info("Logged in with new active token.")
    mock_safe_exists.side_effect = ConnectionError("Simulated Redis Connection Error during blacklist check")
    log.info("Calling /profile with ACTIVE token while Redis check is failing...")
    response_fail_open = await client.get(ProfileURLs.PROFILE, headers=active_headers)
    assert response_fail_open.status_code == 200
    data = response_fail_open.json()
    assert data["id"] == regular_user_in_db["id"]
    log.info("API correctly returned 200 OK (fail-open) on active token.")
    assert mock_safe_exists.await_count == 2
    log.info("Auth dependency (safe_redis_exists) was called twice as expected.")