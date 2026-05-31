# tests/routers/test_admin_config_api.py
# -*- coding: utf-8 -*-
import json
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.config import settings  # Cần settings để lấy cache TTL

# Import các thành phần app
from app.database import AsyncSessionLocal

# Import constants và NON_EXISTENT_ID
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from tests.fixtures.constants import (
        NON_EXISTENT_ID,
        AdminURLs,
        TestConfigData,
        TestOrgData,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# === Fixture để tạo OrganizationUnit mẫu ===
@pytest_asyncio.fixture(scope="function")
async def seed_organization_unit(setup_test_database):
    """Tạo một OrganizationUnit mẫu sử dụng hằng số."""
    log.info("--- [FIXTURE] Seeding organization unit ---")
    unit_data = TestOrgData.UNIT_1  # Lấy dữ liệu từ constant
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit1 = models.OrganizationUnit(
                id=unit_data["id"], name=unit_data["name"], type=unit_data["type"]
            )
            session.add(unit1)
    log.info(f"--- [FIXTURE] Unit seeded (ID: {unit_data['id']}) ---")
    return unit_data  # Trả về dict từ constant


# === Tests cho Assignment Config ===


@pytest.mark.asyncio
async def test_admin_update_assignment_config_success_create_and_cache(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_organization_unit: dict,
    test_redis_client,
):
    """
    Test PUT /assignment-config/{unit_id} - Tạo mới thành công.
    Kiểm tra response, DB state, và cache invalidation/creation.
    """
    log.info(
        "--- Running: test_admin_update_assignment_config_success_create_and_cache ---"
    )
    unit_id = seed_organization_unit["id"]
    config_url = AdminURLs.ASSIGNMENT_CONFIG_DETAIL(unit_id)  # Dùng constant URL
    cache_key = f"config:assignment:{unit_id}"
    config_payload = {
        "params": TestConfigData.ASSIGNMENT_PARAMS
    }  # Dùng constant payload

    # --- Bước 1: Đảm bảo cache trống trước khi PUT ---
    await test_redis_client.delete(cache_key)  # Xóa cache nếu có
    assert (
        await test_redis_client.exists(cache_key) == 0
    ), "Cache should NOT exist before first PUT"
    log.info("Initial cache check OK: Cache key does not exist.")

    # --- Bước 2: Tạo config (PUT lần 1) ---
    response_put = await client.put(
        config_url, json=config_payload, headers=admin_token_headers
    )

    # --- Assert PUT Response ---
    assert response_put.status_code == 200, f"PUT Response: {response_put.text}"
    data_put = response_put.json()
    assert isinstance(data_put, dict), "Response should be a dictionary"
    assert "params" in data_put, "Response should contain 'params' key"
    assert (
        data_put["params"] == config_payload["params"]
    ), "Response params mismatch payload"
    log.info("PUT request successful (200). Response content verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_config = await session.scalar(
            select(models.OfficerAssignmentConfig).where(
                models.OfficerAssignmentConfig.unit_id == unit_id
            )
        )
        assert db_config is not None, "Config not found in DB after PUT"
        assert db_config.unit_id == unit_id, "DB unit_id mismatch"
        assert db_config.params == config_payload["params"], "DB params mismatch"
    log.info("DB state verified: Config created correctly.")

    # --- Assert Cache Invalidation ---
    # Vì đây là lần tạo đầu tiên, cache key đáng lẽ không tồn tại để bị xóa,
    # nhưng service vẫn gọi delete, nên kiểm tra nó không tồn tại sau đó.
    is_cache_deleted = await test_redis_client.exists(cache_key)
    assert (
        is_cache_deleted == 0
    ), "Cache key should still NOT exist immediately after PUT (as it was never set)"
    log.info("Cache Invalidation check OK: Cache key does not exist after PUT.")

    # --- Bước 3: Kiểm tra GET (tạo cache mới) ---
    response_get = await client.get(config_url, headers=admin_token_headers)

    # --- Assert GET Response ---
    assert response_get.status_code == 200, f"GET Response: {response_get.text}"
    data_get = response_get.json()
    assert data_get == config_payload, "GET response mismatch original payload"
    log.info("GET request successful after PUT. Response content verified.")

    # --- Assert Cache Creation ---
    new_cache_data_str = await test_redis_client.get(cache_key)
    assert new_cache_data_str is not None, "Cache key should be populated after GET"
    try:
        new_cache_data = json.loads(new_cache_data_str)
        # Service chỉ cache phần params
        assert (
            new_cache_data == config_payload["params"]
        ), "Cache content mismatch expected params"
        # Kiểm tra TTL (xấp xỉ)
        ttl = await test_redis_client.ttl(cache_key)
        assert (
            ttl > 0 and ttl <= settings.CONFIG_CACHE_TTL_SECONDS
        ), f"Unexpected cache TTL: {ttl}"
    except json.JSONDecodeError:
        pytest.fail("Cache data is not valid JSON")
    log.info("Cache repopulated correctly with correct content and TTL.")

    log.info(
        "--- Finished: test_admin_update_assignment_config_success_create_and_cache ---"
    )


@pytest.mark.asyncio
async def test_admin_update_assignment_config_success_update_and_cache(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_organization_unit: dict,
    test_redis_client,
):
    """
    Test PUT /assignment-config/{unit_id} - Cập nhật thành công config đã tồn tại.
    Kiểm tra response, DB state, và cache invalidation.
    """
    log.info(
        "--- Running: test_admin_update_assignment_config_success_update_and_cache ---"
    )
    unit_id = seed_organization_unit["id"]
    config_url = AdminURLs.ASSIGNMENT_CONFIG_DETAIL(unit_id)
    cache_key = f"config:assignment:{unit_id}"
    initial_params = {"strategy": "initial", "value": 1}
    updated_params = {"strategy": "updated", "value": 2, "new_key": True}  # Params mới
    updated_payload = {"params": updated_params}

    # --- Bước 1: Tạo config ban đầu và mồi cache ---
    async with AsyncSessionLocal() as session:
        async with session.begin():
            initial_config = models.OfficerAssignmentConfig(
                unit_id=unit_id, params=initial_params
            )
            session.add(initial_config)
    await test_redis_client.set(cache_key, json.dumps(initial_params), ex=3600)
    assert (
        await test_redis_client.exists(cache_key) == 1
    ), "Cache should exist before update PUT"
    log.info("Initial config created and cache primed.")

    # --- Bước 2: Cập nhật config (PUT lần 2) ---
    response_put = await client.put(
        config_url, json=updated_payload, headers=admin_token_headers
    )

    # --- Assert PUT Response ---
    assert response_put.status_code == 200, f"PUT Update Response: {response_put.text}"
    data_put = response_put.json()
    assert (
        data_put["params"] == updated_params
    ), "Response params mismatch updated payload"
    log.info("PUT update request successful (200). Response content verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_config = await session.scalar(
            select(models.OfficerAssignmentConfig).where(
                models.OfficerAssignmentConfig.unit_id == unit_id
            )
        )
        assert db_config is not None, "Config not found in DB after update"
        assert db_config.params == updated_params, "DB params were not updated"
    log.info("DB state verified: Config updated correctly.")

    # --- Assert Cache Invalidation ---
    is_cache_deleted = await test_redis_client.exists(cache_key)
    assert is_cache_deleted == 0, "Cache key should be deleted after update PUT"
    log.info("Cache Invalidation check OK: Cache key deleted after update.")

    log.info(
        "--- Finished: test_admin_update_assignment_config_success_update_and_cache ---"
    )


@pytest.mark.asyncio
async def test_admin_get_assignment_config_not_found(
    client: AsyncClient, admin_token_headers: dict
):
    """Test GET /assignment-config/{unit_id} - Lỗi 404 (Unit ID không tồn tại)."""
    log.info("--- Running: test_admin_get_assignment_config_not_found ---")
    unit_id_no_config = NON_EXISTENT_ID

    response_get = await client.get(
        AdminURLs.ASSIGNMENT_CONFIG_DETAIL(unit_id_no_config),
        headers=admin_token_headers,
    )
    # --- Assert Error Response ---
    assert response_get.status_code == 404, f"Response: {response_get.text}"
    error_data = response_get.json()
    assert "detail" in error_data
    # API dependency checks unit first, so error is about unit not found
    assert "not found" in error_data["detail"].lower()
    log.info("GET non-existent config failed (404) with correct detail message.")
    log.info("--- Finished: test_admin_get_assignment_config_not_found ---")


@pytest.mark.asyncio
async def test_admin_update_assignment_config_unit_not_found(
    client: AsyncClient, admin_token_headers: dict
):
    """Test PUT /assignment-config/{unit_id} - Lỗi 404 (Unit ID không tồn tại)."""
    log.info("--- Running: test_admin_update_assignment_config_unit_not_found ---")
    unit_id_non_existent = NON_EXISTENT_ID
    config_payload = {"params": {"strategy": "round_robin"}}

    response_put = await client.put(
        AdminURLs.ASSIGNMENT_CONFIG_DETAIL(unit_id_non_existent),
        json=config_payload,
        headers=admin_token_headers,
    )
    # --- Assert Error Response ---
    assert response_put.status_code == 404, f"Response: {response_put.text}"
    error_data = response_put.json()
    assert "detail" in error_data
    assert (
        error_data["detail"]
        == f"Organization Unit with id {unit_id_non_existent} not found."
    )
    log.info("PUT to non-existent unit failed (404) with correct detail message.")
    log.info("--- Finished: test_admin_update_assignment_config_unit_not_found ---")


# === Tests cho Skill Rules ===


@pytest.mark.asyncio
async def test_admin_skill_rules_crud_flow(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
):
    """
    Test flow CRUD hoàn chỉnh cho /skill-rules.
    Bao gồm: GET (empty), POST, GET (one item), DELETE, GET (empty again).
    Kiểm tra response, DB state, và error messages.
    """
    log.info("--- Running: test_admin_skill_rules_crud_flow ---")
    skill_rules_url = AdminURLs.SKILL_RULES

    # --- 1. GET (Empty List) ---
    log.info("Checking GET (empty list)...")
    response_get_empty = await client.get(skill_rules_url, headers=admin_token_headers)
    assert (
        response_get_empty.status_code == 200
    ), f"GET Empty Resp: {response_get_empty.text}"
    assert response_get_empty.json() == [], "Expected empty list initially"
    log.info("GET (empty list) successful.")

    # --- 2. POST (Create Rule) ---
    log.info("Checking POST (create)...")
    rule_payload = TestConfigData.SKILL_RULE_1  # Dùng constant payload
    response_post = await client.post(
        skill_rules_url, json=rule_payload, headers=admin_token_headers
    )

    # --- Assert POST Response ---
    assert response_post.status_code == 201, f"POST Create Resp: {response_post.text}"
    created_rule = response_post.json()
    assert isinstance(created_rule, dict), "Create response should be a dict"
    assert "id" in created_rule, "Create response missing 'id'"
    rule_id = created_rule["id"]  # Lưu lại ID để dùng sau
    assert created_rule["lead_attribute"] == rule_payload["lead_attribute"]
    assert created_rule["attribute_value"] == rule_payload["attribute_value"]
    assert created_rule["required_skill"] == rule_payload["required_skill"]
    log.info(f"POST (create) successful (ID: {rule_id}). Response content verified.")

    # --- Assert DB State after POST ---
    async with AsyncSessionLocal() as session:
        db_rule = await session.get(models.SkillRequirementRule, rule_id)
        assert db_rule is not None, "Rule not found in DB after creation"
        assert db_rule.lead_attribute == rule_payload["lead_attribute"]
        assert db_rule.attribute_value == rule_payload["attribute_value"]
        assert db_rule.required_skill == rule_payload["required_skill"]
    log.info("DB state verified after POST.")

    # --- 3. GET (List with One Item) ---
    log.info("Checking GET (list with one item)...")
    response_get_one = await client.get(skill_rules_url, headers=admin_token_headers)
    assert (
        response_get_one.status_code == 200
    ), f"GET One Item Resp: {response_get_one.text}"
    data_list = response_get_one.json()
    assert isinstance(data_list, list), "GET response should be a list"
    assert len(data_list) == 1, "Expected list with one rule"
    assert data_list[0]["id"] == rule_id, "Rule ID mismatch in GET list"
    assert data_list[0]["attribute_value"] == rule_payload["attribute_value"]
    log.info("GET (list with one item) successful. Response content verified.")

    # --- 4. DELETE (Success) ---
    log.info("Checking DELETE (success)...")
    delete_url = AdminURLs.SKILL_RULE_DETAIL(rule_id)  # Dùng constant URL
    response_delete = await client.delete(delete_url, headers=admin_token_headers)
    assert (
        response_delete.status_code == 204
    ), f"DELETE Resp: {response_delete.text}"  # No Content
    log.info("DELETE (success) successful (204).")

    # --- Assert DB State after DELETE ---
    async with AsyncSessionLocal() as session:
        db_rule_after_delete = await session.get(models.SkillRequirementRule, rule_id)
        assert db_rule_after_delete is None, "Rule still exists in DB after deletion"
    log.info("DB state verified after DELETE.")

    # --- 5. DELETE (Not Found) ---
    log.info("Checking DELETE (not found)...")
    response_delete_404 = await client.delete(
        delete_url, headers=admin_token_headers  # Xóa lại ID cũ
    )
    # --- Assert DELETE Not Found Response ---
    assert (
        response_delete_404.status_code == 404
    ), f"DELETE Not Found Resp: {response_delete_404.text}"
    error_data_delete = response_delete_404.json()
    assert "detail" in error_data_delete
    # config_service:324 raise "...not found" (KHÔNG period — convention file).
    assert error_data_delete["detail"] == f"Skill rule with id {rule_id} not found"
    log.info("DELETE (not found) successful (404) with correct detail message.")

    # --- 6. GET (Empty List Again) ---
    log.info("Checking GET (empty list again)...")
    response_get_empty_again = await client.get(
        skill_rules_url, headers=admin_token_headers
    )
    assert response_get_empty_again.status_code == 200
    assert response_get_empty_again.json() == [], "Expected empty list after deletion"
    log.info("GET (empty list again) successful.")

    # --- Assert Cache State ---
    # Skill rules không dùng cache trong service hiện tại, nên không cần kiểm tra.

    log.info("--- Finished: test_admin_skill_rules_crud_flow ---")


@pytest.mark.asyncio
async def test_admin_create_skill_rule_validation_error(
    client: AsyncClient, admin_token_headers: dict
):
    """Test POST /skill-rules - Lỗi 422 (Thiếu trường bắt buộc)."""
    log.info("--- Running: test_admin_create_skill_rule_validation_error ---")

    # Thiếu 'required_skill'
    invalid_payload = {
        "lead_attribute": "source",
        "attribute_value": "event",
        # "required_skill": "Missing"
    }
    response = await client.post(
        AdminURLs.SKILL_RULES, json=invalid_payload, headers=admin_token_headers
    )

    # --- Assert 422 Validation Error Response ---
    assert response.status_code == 422, f"Response: {response.text}"
    error_data = response.json()
    
    # Convert entire response to string for simple checking
    error_str = str(error_data).lower()
    
    # Verify the error mentions the missing field and that it's required
    assert "required_skill" in error_str, f"Response should mention 'required_skill': {error_data}"
    assert "required" in error_str or "missing" in error_str, f"Response should indicate field is required/missing: {error_data}"

    log.info(
        "Invalid payload (missing field) correctly blocked (422) with detailed error."
    )
    log.info("--- Finished: test_admin_create_skill_rule_validation_error ---")


# ============================================================================
# AUTHORIZATION TESTS (Migrated from test_config.py)
# ============================================================================


@pytest.mark.asyncio
async def test_get_assignment_config_unauthorized(
    client: AsyncClient,
):
    """
    Test: GET /api/admin/assignment-config/{unit_id} - Unauthorized access

    Verifies:
    - Non-admin users cannot access assignment config
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_get_assignment_config_unauthorized ---")

    response = await client.get(
        "/api/admin/assignment-config/1",
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")


@pytest.mark.asyncio
async def test_create_skill_rule_unauthorized(
    client: AsyncClient,
):
    """
    Test: POST /api/admin/skill-rules - Unauthorized access

    Verifies:
    - Non-admin users cannot create skill rules
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_create_skill_rule_unauthorized ---")

    rule_data = {
        "lead_attribute": "source",
        "attribute_value": "test",
        "required_skill": "Testing",
    }

    response = await client.post(
        "/api/admin/skill-rules",
        json=rule_data,
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")


@pytest.mark.asyncio
async def test_delete_skill_rule_unauthorized(
    client: AsyncClient,
):
    """
    Test: DELETE /api/admin/skill-rules/{rule_id} - Unauthorized access

    Verifies:
    - Non-admin users cannot delete skill rules
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_delete_skill_rule_unauthorized ---")

    response = await client.delete(
        "/api/admin/skill-rules/1",
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")


@pytest.mark.asyncio
async def test_update_assignment_config_unauthorized(
    client: AsyncClient,
):
    """
    Test: PUT /api/admin/assignment-config/{unit_id} - Unauthorized access

    Verifies:
    - Non-admin users cannot update assignment config
    - Returns 401 or 403 status
    """
    log.info("--- Running: test_update_assignment_config_unauthorized ---")

    config_data = {
        "params": {
            "strategy": "round_robin",
            "max_concurrent": 5,
        }
    }

    response = await client.put(
        "/api/admin/assignment-config/1",
        json=config_data,
    )

    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    log.info("✅ Unauthorized access rejected as expected")

