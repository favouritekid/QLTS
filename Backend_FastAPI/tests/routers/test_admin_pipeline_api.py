# tests/routers/test_admin_pipeline_api.py
# -*- coding: utf-8 -*-
import json
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select  # <-- Thêm func để kiểm tra count

from app import models
from app.config import settings  # Cần settings để lấy cache TTL

# Import các thành phần app
from app.database import AsyncSessionLocal
from app.services.pipeline_service import (
    PIPELINE_STAGES_CACHE_KEY,
    PIPELINE_STATUSES_CACHE_KEY,
)

# Import constants và NON_EXISTENT_IDs
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from ..fixtures.constants import TestLeadData  # Cần để seed lead
    from ..fixtures.constants import TestOrgData  # Cần để seed lead
    from ..fixtures.constants import (
        NON_EXISTENT_ID,
        NON_EXISTENT_STAGE_ID,
        NON_EXISTENT_STATUS_ID,
        AdminURLs,
        TestPipelineData,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")


log = logging.getLogger(__name__)


# === Fixture để mồi dữ liệu cho test (ví dụ: test conflict) ===
@pytest_asyncio.fixture(scope="function")
async def seed_pipeline_data_with_lead(setup_test_database):
    """
    Tạo dữ liệu mẫu: 3 stages, 2 statuses, 1 unit, 1 major, và 1 lead.
    Sử dụng hằng số từ constants.py.
    """
    log.info("--- [FIXTURE] Seeding pipeline data with lead ---")
    lead_id_to_return = None
    # Lấy data từ constants
    stage_a_data = TestPipelineData.STAGE_A
    stage_b_data = TestPipelineData.STAGE_B
    stage_c_data = TestPipelineData.STAGE_C  # Stage không có status
    status_a1_data = TestPipelineData.STATUS_A1
    status_b1_data = TestPipelineData.STATUS_B1
    unit_data = TestOrgData.UNIT_1
    major_data = TestOrgData.MAJOR_1
    lead_data = TestLeadData.LEAD_1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Org/Major
            unit1 = models.OrganizationUnit(**unit_data)  # Dùng ** để unpack dict
            major1 = models.Major(**major_data)
            session.add_all([unit1, major1])

            # Pipeline Stages
            stage_a = models.PipelineStage(**stage_a_data)
            stage_b = models.PipelineStage(**stage_b_data)
            stage_c = models.PipelineStage(**stage_c_data)
            session.add_all([stage_a, stage_b, stage_c])

            # Pipeline Statuses
            status_a1 = models.ConsultationStatus(**status_a1_data)
            status_b1 = models.ConsultationStatus(**status_b1_data)
            session.add_all([status_a1, status_b1])

            await session.flush()  # Flush để lấy ID nếu cần

            # Lead (Dùng data từ constant, đảm bảo FK khớp)
            lead1 = models.Lead(
                full_name=lead_data["full_name"],
                email=lead_data["email"],
                phone=lead_data["phone"],
                source=lead_data["source"],
                unit_id=unit_data["id"],
                major_id=major_data["id"],
                status=status_a1_data["id"],  # FK
                consultation_status_id=status_a1_data["id"],  # FK
                pipeline_stage_id=stage_a_data["id"],  # FK
            )
            session.add(lead1)
            await session.flush()
            lead_id_to_return = lead1.id

    log.info("--- [FIXTURE] Data seeded ---")
    # Trả về các ID đã tạo để test sử dụng
    return {
        "stage_a_id": stage_a_data["id"],
        "stage_b_id": stage_b_data["id"],
        "stage_c_id": stage_c_data["id"],
        "status_a1_id": status_a1_data["id"],
        "status_b1_id": status_b1_data["id"],
        "lead_id": lead_id_to_return,
    }


# === Helper để kiểm tra cache ===
async def assert_pipeline_cache_invalidated(
    redis_client, message="Cache Invalidation check OK"
):
    """Kiểm tra rằng cả hai cache key của pipeline đều đã bị xóa."""
    stages_exists = await redis_client.exists(PIPELINE_STAGES_CACHE_KEY)
    statuses_exists = await redis_client.exists(PIPELINE_STATUSES_CACHE_KEY)
    assert (
        stages_exists == 0
    ), f"Cache key {PIPELINE_STAGES_CACHE_KEY} should be deleted"
    assert (
        statuses_exists == 0
    ), f"Cache key {PIPELINE_STATUSES_CACHE_KEY} should be deleted"
    log.info(f"{message}: Both pipeline cache keys deleted.")


# === Bắt đầu Tests cho Pipeline Stages ===


@pytest.mark.asyncio
async def test_admin_create_stage_success_and_cache_invalidation(
    client: AsyncClient, admin_token_headers: dict, test_redis_client
):
    """Test POST /pipeline-stages - Tạo thành công, kiểm tra response, DB, cache."""
    log.info("--- Running: test_admin_create_stage_success_and_cache_invalidation ---")
    stages_url = AdminURLs.PIPELINE_STAGES  # Dùng constant

    # "Mồi" cache để đảm bảo nó tồn tại trước khi bị xóa
    await test_redis_client.set(
        PIPELINE_STAGES_CACHE_KEY, json.dumps(["old_stage_data"])
    )
    await test_redis_client.set(
        PIPELINE_STATUSES_CACHE_KEY, json.dumps(["old_status_data"])
    )
    assert await test_redis_client.exists(PIPELINE_STAGES_CACHE_KEY) == 1
    log.info("Cache primed before action.")

    # Payload mẫu
    payload = {"id": "NEW_STAGE", "name": "New Stage", "order": 1}

    # --- Action ---
    response = await client.post(stages_url, json=payload, headers=admin_token_headers)

    # --- Assert Response ---
    assert response.status_code == 201, f"POST Stage Resp: {response.text}"
    data = response.json()
    assert isinstance(data, dict), "Response should be a dictionary"
    assert data.get("id") == payload["id"]
    assert data.get("name") == payload["name"]
    assert data.get("order") == payload["order"]
    log.info("Stage created successfully (201). Response content verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_stage = await session.get(models.PipelineStage, payload["id"])
        assert db_stage is not None, "Stage not found in DB after creation"
        assert db_stage.name == payload["name"]
        assert db_stage.order == payload["order"]
    log.info("DB state verified: Stage exists with correct data.")

    # --- Assert Cache Invalidation ---
    await assert_pipeline_cache_invalidated(test_redis_client)


@pytest.mark.asyncio
async def test_admin_create_stage_conflict_errors(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_pipeline_data_with_lead,  # Dùng fixture có data
):
    """Test POST /pipeline-stages - Lỗi 409 (Trùng ID, Trùng Order)."""
    log.info("--- Running: test_admin_create_stage_conflict_errors ---")
    stages_url = AdminURLs.PIPELINE_STAGES
    existing_stage_id = seed_pipeline_data_with_lead["stage_a_id"]  # ID: STAGE_A
    existing_order = TestPipelineData.STAGE_A["order"]  # Order: 10

    # --- Kịch bản 1: Trùng ID ---
    payload_dupe_id = {"id": existing_stage_id, "name": "Duplicate ID", "order": 99}
    response_dupe_id = await client.post(
        stages_url, json=payload_dupe_id, headers=admin_token_headers
    )
    # --- Assert Lỗi Trùng ID ---
    assert response_dupe_id.status_code == 409, f"Dupe ID Resp: {response_dupe_id.text}"
    error_data_id = response_dupe_id.json()
    assert "detail" in error_data_id
    assert (
        error_data_id["detail"]
        == f"Pipeline Stage ID '{existing_stage_id}' already exists."
    )
    log.info("Duplicate ID correctly blocked (409) with specific message.")

    # --- Kịch bản 2: Trùng Order ---
    payload_dupe_order = {
        "id": "UNIQUE_ID",
        "name": "Duplicate Order",
        "order": existing_order,
    }
    response_dupe_order = await client.post(
        stages_url, json=payload_dupe_order, headers=admin_token_headers
    )
    # --- Assert Lỗi Trùng Order ---
    assert (
        response_dupe_order.status_code == 409
    ), f"Dupe Order Resp: {response_dupe_order.text}"
    error_data_order = response_dupe_order.json()
    assert "detail" in error_data_order
    assert (
        error_data_order["detail"]
        == f"Pipeline Stage order '{existing_order}' already exists."
    )
    log.info("Duplicate order correctly blocked (409) with specific message.")


@pytest.mark.asyncio
async def test_admin_create_stage_validation_error(
    client: AsyncClient, admin_token_headers: dict
):
    """Test POST /pipeline-stages - Lỗi 422 (Payload không hợp lệ - thiếu order)."""
    log.info("--- Running: test_admin_create_stage_validation_error ---")
    stages_url = AdminURLs.PIPELINE_STAGES

    # Thiếu 'order'
    payload_missing_order = {"id": "INVALID", "name": "Invalid Stage"}
    response = await client.post(
        stages_url, json=payload_missing_order, headers=admin_token_headers
    )

    # --- Assert 422 Validation Error ---
    assert response.status_code == 422, f"Validation Resp: {response.text}"
    error_data = response.json()

    # --- SỬA CÁC DÒNG ASSERTION Ở ĐÂY ---
    assert "detail" in error_data, "422 response missing 'detail' string"
    assert (
        error_data["detail"] == "Validation Error"
    ), "Expected detail string 'Validation Error'"  # Kiểm tra chuỗi detail cố định

    assert "errors" in error_data, "422 response missing 'errors' list"
    assert isinstance(
        error_data["errors"], list
    ), "'errors' should be a list for validation details"  # Kiểm tra 'errors' là list

    found_error = False
    # Lặp qua error_data["errors"]
    for error in error_data["errors"]:
        assert isinstance(error, dict)
        # Kiểm tra các key mà handler của bạn trả về ('field', 'message')
        assert "field" in error, "Validation error dict missing 'field' key"
        assert "message" in error, "Validation error dict missing 'message' key"

        # Kiểm tra giá trị cụ thể cho lỗi thiếu 'order'
        if error.get("field") == "body -> order" and "Field required" in error.get(
            "message", ""
        ):
            found_error = True
            break  # Tìm thấy lỗi cần tìm
    # --- KẾT THÚC SỬA ASSERTION ---

    assert (
        found_error
    ), "Validation error for missing 'order' not found in response errors list"
    log.info(
        "Invalid payload (missing 'order') correctly blocked (422) with detailed error."
    )


@pytest.mark.asyncio
async def test_admin_get_stage_detail(
    client: AsyncClient, admin_token_headers: dict, seed_pipeline_data_with_lead
):
    """Test GET /pipeline-stages/{id} - Lấy thành công và Lỗi 404."""
    log.info("--- Running: test_admin_get_stage_detail ---")
    stage_a_id = seed_pipeline_data_with_lead["stage_a_id"]
    stage_a_url = AdminURLs.PIPELINE_STAGE_DETAIL(stage_a_id)
    non_existent_url = AdminURLs.PIPELINE_STAGE_DETAIL(NON_EXISTENT_STAGE_ID)

    # --- Kịch bản 1: Thành công ---
    response_success = await client.get(stage_a_url, headers=admin_token_headers)
    # --- Assert Success Response ---
    assert (
        response_success.status_code == 200
    ), f"GET Success Resp: {response_success.text}"
    data = response_success.json()
    assert isinstance(data, dict)
    assert data.get("id") == stage_a_id
    assert data.get("name") == TestPipelineData.STAGE_A["name"]
    assert data.get("order") == TestPipelineData.STAGE_A["order"]
    log.info("Get stage detail successful (200). Response content verified.")

    # --- Kịch bản 2: Không tìm thấy ---
    response_404 = await client.get(non_existent_url, headers=admin_token_headers)
    # --- Assert Not Found Response ---
    assert response_404.status_code == 404, f"GET 404 Resp: {response_404.text}"
    error_data_404 = response_404.json()
    assert "detail" in error_data_404
    assert (
        error_data_404["detail"]
        == f"Pipeline Stage '{NON_EXISTENT_STAGE_ID}' not found."
    )
    log.info("Get non-existent stage correctly failed (404) with specific message.")


@pytest.mark.asyncio
async def test_admin_update_stage(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_pipeline_data_with_lead,
    test_redis_client,
):
    """Test PUT /pipeline-stages/{id} - Cập nhật thành công, 404, 409 (trùng order), cache."""
    log.info("--- Running: test_admin_update_stage ---")
    stage_b_id = seed_pipeline_data_with_lead["stage_b_id"]  # ID: STAGE_B, Order: 20
    stage_b_url = AdminURLs.PIPELINE_STAGE_DETAIL(stage_b_id)
    stage_a_order = TestPipelineData.STAGE_A["order"]  # Order của STAGE_A (là 10)
    non_existent_url = AdminURLs.PIPELINE_STAGE_DETAIL(NON_EXISTENT_STAGE_ID)

    # "Mồi" cache
    await test_redis_client.set(PIPELINE_STAGES_CACHE_KEY, json.dumps(["old_data"]))
    log.info("Cache primed before update.")

    # --- Kịch bản 1: Cập nhật thành công ---
    update_payload = {"name": "Updated Stage B", "order": 25}
    response_success = await client.put(
        stage_b_url, json=update_payload, headers=admin_token_headers
    )
    # --- Assert Success Response ---
    assert (
        response_success.status_code == 200
    ), f"PUT Success Resp: {response_success.text}"
    data = response_success.json()
    assert data.get("name") == update_payload["name"]
    assert data.get("order") == update_payload["order"]
    log.info("Update stage successful (200). Response content verified.")
    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_stage = await session.get(models.PipelineStage, stage_b_id)
        assert db_stage is not None
        assert db_stage.name == update_payload["name"]
        assert db_stage.order == update_payload["order"]
    log.info("DB state verified after update.")
    # --- Assert Cache Invalidation ---
    await assert_pipeline_cache_invalidated(
        test_redis_client, "Cache Invalidation check after PUT success"
    )

    # --- Kịch bản 2: Lỗi 404 (Stage ID không tồn tại) ---
    response_404 = await client.put(
        non_existent_url, json=update_payload, headers=admin_token_headers
    )
    # --- Assert 404 Response ---
    assert response_404.status_code == 404, f"PUT 404 Resp: {response_404.text}"
    error_data_404 = response_404.json()
    assert "detail" in error_data_404
    assert (
        error_data_404["detail"]
        == f"Pipeline Stage '{NON_EXISTENT_STAGE_ID}' not found."
    )
    log.info("Update non-existent stage correctly failed (404) with specific message.")

    # --- Kịch bản 3: Lỗi 409 (Trùng Order) ---
    # Cố gắng đổi order của STAGE_B (giờ là 25) thành order của STAGE_A (là 10)
    payload_dupe_order = {"order": stage_a_order}
    response_dupe_order = await client.put(
        stage_b_url, json=payload_dupe_order, headers=admin_token_headers
    )
    # --- Assert 409 Response ---
    assert (
        response_dupe_order.status_code == 409
    ), f"PUT Dupe Order Resp: {response_dupe_order.text}"
    error_data_order = response_dupe_order.json()
    assert "detail" in error_data_order
    assert (
        error_data_order["detail"]
        == f"Pipeline Stage order '{stage_a_order}' already in use."
    )
    log.info(
        "Update stage with duplicate order correctly failed (409) with specific message."
    )


@pytest.mark.asyncio
async def test_admin_delete_stage_conflict_in_use(
    client: AsyncClient, admin_token_headers: dict, seed_pipeline_data_with_lead
):
    """Test DELETE /pipeline-stages/{id} - Lỗi 409 (Stage đang được Status sử dụng)."""
    log.info("--- Running: test_admin_delete_stage_conflict_in_use ---")
    stage_a_id = seed_pipeline_data_with_lead[
        "stage_a_id"
    ]  # STAGE_A đang được STATUS_A1 sử dụng
    stage_a_url = AdminURLs.PIPELINE_STAGE_DETAIL(stage_a_id)

    # --- Action ---
    response = await client.delete(stage_a_url, headers=admin_token_headers)

    # --- Assert 409 Response ---
    assert response.status_code == 409, f"DELETE Conflict Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    # Kiểm tra message lỗi cụ thể (số lượng status có thể thay đổi nếu fixture thay đổi)
    assert f"Cannot delete stage '{stage_a_id}'" in error_data["detail"]
    assert "consultation statuses linked to it" in error_data["detail"]
    log.info("Delete stage in use correctly failed (409) with specific message.")


@pytest.mark.asyncio
async def test_admin_delete_stage_success(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_pipeline_data_with_lead,
    test_redis_client,
):
    """Test DELETE /pipeline-stages/{id} - Xóa thành công stage không bị ràng buộc, cache."""
    log.info("--- Running: test_admin_delete_stage_success ---")
    stage_c_id = seed_pipeline_data_with_lead[
        "stage_c_id"
    ]  # STAGE_C không có status nào
    stage_c_url = AdminURLs.PIPELINE_STAGE_DETAIL(stage_c_id)

    # "Mồi" cache
    await test_redis_client.set(PIPELINE_STAGES_CACHE_KEY, json.dumps(["old_data"]))
    log.info("Cache primed before delete.")

    # --- Action ---
    response = await client.delete(stage_c_url, headers=admin_token_headers)

    # --- Assert Success Response ---
    assert (
        response.status_code == 204
    ), f"DELETE Success Resp: Status {response.status_code}, Text: {response.text}"  # Mong đợi 204 No Content
    log.info("Delete stage successful (204).")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_stage = await session.get(models.PipelineStage, stage_c_id)
        assert db_stage is None, "Stage still exists in DB after deletion"
    log.info("DB state verified: Stage deleted.")

    # --- Assert Cache Invalidation ---
    await assert_pipeline_cache_invalidated(
        test_redis_client, "Cache Invalidation check after DELETE success"
    )


@pytest.mark.asyncio
async def test_admin_delete_stage_not_found(
    client: AsyncClient, admin_token_headers: dict
):
    """Test DELETE /pipeline-stages/{id} - Lỗi 404."""
    log.info("--- Running: test_admin_delete_stage_not_found ---")
    non_existent_url = AdminURLs.PIPELINE_STAGE_DETAIL(NON_EXISTENT_STAGE_ID)

    response = await client.delete(non_existent_url, headers=admin_token_headers)

    # --- Assert 404 Response ---
    assert response.status_code == 404, f"DELETE 404 Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert (
        error_data["detail"] == f"Pipeline Stage '{NON_EXISTENT_STAGE_ID}' not found."
    )
    log.info("Delete non-existent stage correctly failed (404) with specific message.")


# === Bắt đầu Tests cho Consultation Statuses ===


@pytest.mark.asyncio
async def test_admin_create_status_success_and_cache_invalidation(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_pipeline_data_with_lead,
    test_redis_client,
):
    """Test POST /consultation-statuses - Tạo thành công, kiểm tra response, DB, cache."""
    log.info("--- Running: test_admin_create_status_success_and_cache_invalidation ---")
    statuses_url = AdminURLs.CONSULTATION_STATUSES  # Dùng constant

    # "Mồi" cache
    await test_redis_client.set(PIPELINE_STATUSES_CACHE_KEY, json.dumps(["old_data"]))
    assert await test_redis_client.exists(PIPELINE_STATUSES_CACHE_KEY) == 1
    log.info("Cache primed before action.")

    # Payload mẫu (dùng stage hợp lệ từ fixture)
    stage_b_id = seed_pipeline_data_with_lead["stage_b_id"]
    payload = {
        "id": "NEW_STATUS_B",
        "name": "New Status for B",
        "color_code": "#123456",
        "stage_id": stage_b_id,
    }

    # --- Action ---
    response = await client.post(
        statuses_url, json=payload, headers=admin_token_headers
    )

    # --- Assert Response ---
    assert response.status_code == 201, f"POST Status Resp: {response.text}"
    data = response.json()
    assert isinstance(data, dict)
    assert data.get("id") == payload["id"]
    assert data.get("name") == payload["name"]
    assert data.get("color_code") == payload["color_code"]
    assert data.get("stage_id") == payload["stage_id"]
    log.info("Status created successfully (201). Response content verified.")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_status = await session.get(models.ConsultationStatus, payload["id"])
        assert db_status is not None, "Status not found in DB after creation"
        assert db_status.name == payload["name"]
        assert db_status.stage_id == payload["stage_id"]
    log.info("DB state verified: Status exists with correct data.")

    # --- Assert Cache Invalidation ---
    await assert_pipeline_cache_invalidated(test_redis_client)


@pytest.mark.asyncio
async def test_admin_create_status_conflict_errors(
    client: AsyncClient, admin_token_headers: dict, seed_pipeline_data_with_lead
):
    """Test POST /consultation-statuses - Lỗi 409 (Trùng ID), 404 (Stage ID không tồn tại)."""
    log.info("--- Running: test_admin_create_status_conflict_errors ---")
    statuses_url = AdminURLs.CONSULTATION_STATUSES
    existing_status_id = seed_pipeline_data_with_lead["status_a1_id"]  # ID: STATUS_A1
    valid_stage_id = seed_pipeline_data_with_lead["stage_a_id"]

    # --- Kịch bản 1: Trùng ID ---
    payload_dupe_id = {
        "id": existing_status_id,
        "name": "Duplicate ID",
        "color_code": "#121212",
        "stage_id": valid_stage_id,
    }
    response_dupe_id = await client.post(
        statuses_url, json=payload_dupe_id, headers=admin_token_headers
    )
    # --- Assert Lỗi Trùng ID ---
    assert response_dupe_id.status_code == 409, f"Dupe ID Resp: {response_dupe_id.text}"
    error_data_id = response_dupe_id.json()
    assert "detail" in error_data_id
    assert (
        error_data_id["detail"]
        == f"Consultation Status ID '{existing_status_id}' already exists."
    )
    log.info("Duplicate Status ID correctly blocked (409) with specific message.")

    # --- Kịch bản 2: Stage ID không tồn tại ---
    payload_invalid_stage = {
        "id": "UNIQUE_STATUS_ID",
        "name": "Invalid Stage",
        "color_code": "#121212",
        "stage_id": NON_EXISTENT_STAGE_ID,  # Stage ID không tồn tại
    }
    response_invalid_stage = await client.post(
        statuses_url, json=payload_invalid_stage, headers=admin_token_headers
    )
    # --- Assert Lỗi Stage Không Tồn Tại ---
    assert (
        response_invalid_stage.status_code == 404
    ), f"Invalid Stage Resp: {response_invalid_stage.text}"
    error_data_stage = response_invalid_stage.json()
    assert "detail" in error_data_stage
    assert (
        error_data_stage["detail"]
        == f"Pipeline Stage '{NON_EXISTENT_STAGE_ID}' not found."
    )
    log.info("Invalid Stage ID correctly blocked (404) with specific message.")


@pytest.mark.asyncio
async def test_admin_create_status_validation_error(
    client: AsyncClient, admin_token_headers: dict, seed_pipeline_data_with_lead
):
    """Test POST /consultation-statuses - Lỗi 422 (Màu không hợp lệ, thiếu trường)."""
    log.info("--- Running: test_admin_create_status_validation_error ---")
    statuses_url = AdminURLs.CONSULTATION_STATUSES
    valid_stage_id = seed_pipeline_data_with_lead["stage_a_id"]

    # --- Kịch bản 1: Màu không hợp lệ ---
    payload_invalid_color = {
        "id": "INVALID_COLOR_S",
        "name": "Invalid Color Status",
        "color_code": "not-a-hex-code",  # Màu sai
        "stage_id": valid_stage_id,
    }
    response_color = await client.post(
        statuses_url, json=payload_invalid_color, headers=admin_token_headers
    )
    # --- Assert Lỗi Màu ---
    assert (
        response_color.status_code == 422
    ), f"Invalid Color Resp: {response_color.text}"
    error_data_color = response_color.json()

    # --- SỬA CÁC DÒNG ASSERTION Ở ĐÂY (Kịch bản 1) ---
    assert (
        "detail" in error_data_color
        and error_data_color["detail"] == "Validation Error"
    )
    assert "errors" in error_data_color and isinstance(error_data_color["errors"], list)

    found_color_error = False
    for error in error_data_color["errors"]:
        assert isinstance(error, dict)
        assert "field" in error and "message" in error
        # Kiểm tra lỗi màu cụ thể
        if error.get(
            "field"
        ) == "body -> color_code" and "String should match pattern" in error.get(
            "message", ""
        ):
            found_color_error = True
            break
    # --- KẾT THÚC SỬA ASSERTION (Kịch bản 1) ---
    assert found_color_error, "Validation error for 'color_code' pattern not found"
    log.info("Invalid color code correctly blocked (422).")

    # --- Kịch bản 2: Thiếu 'name' ---
    payload_missing_name = {
        "id": "MISSING_NAME_S",
        "color_code": "#123456",
        "stage_id": valid_stage_id,
        # Thiếu "name"
    }
    response_name = await client.post(
        statuses_url, json=payload_missing_name, headers=admin_token_headers
    )
    # --- Assert Lỗi Thiếu Name ---
    assert response_name.status_code == 422, f"Missing Name Resp: {response_name.text}"
    error_data_name = response_name.json()

    # --- SỬA CÁC DÒNG ASSERTION Ở ĐÂY (Kịch bản 2) ---
    assert (
        "detail" in error_data_name and error_data_name["detail"] == "Validation Error"
    )
    assert "errors" in error_data_name and isinstance(error_data_name["errors"], list)

    found_name_error = False
    for error in error_data_name["errors"]:
        assert isinstance(error, dict)
        assert "field" in error and "message" in error
        # Kiểm tra lỗi thiếu 'name'
        if error.get("field") == "body -> name" and "Field required" in error.get(
            "message", ""
        ):
            found_name_error = True
            break
    # --- KẾT THÚC SỬA ASSERTION (Kịch bản 2) ---
    assert found_name_error, "Validation error for missing 'name' not found"
    log.info("Invalid payload (missing 'name') correctly blocked (422).")


@pytest.mark.asyncio
async def test_admin_get_status_detail(
    client: AsyncClient, admin_token_headers: dict, seed_pipeline_data_with_lead
):
    """Test GET /consultation-statuses/{id} - Lấy thành công và Lỗi 404."""
    log.info("--- Running: test_admin_get_status_detail ---")
    status_a1_id = seed_pipeline_data_with_lead["status_a1_id"]
    status_a1_url = AdminURLs.CONSULTATION_STATUS_DETAIL(status_a1_id)
    non_existent_url = AdminURLs.CONSULTATION_STATUS_DETAIL(NON_EXISTENT_STATUS_ID)

    # --- Kịch bản 1: Thành công ---
    response_success = await client.get(status_a1_url, headers=admin_token_headers)
    # --- Assert Success Response ---
    assert (
        response_success.status_code == 200
    ), f"GET Success Resp: {response_success.text}"
    data = response_success.json()
    assert isinstance(data, dict)
    assert data.get("id") == status_a1_id
    assert data.get("name") == TestPipelineData.STATUS_A1["name"]
    assert data.get("color_code") == TestPipelineData.STATUS_A1["color_code"]
    assert data.get("stage_id") == TestPipelineData.STATUS_A1["stage_id"]
    log.info("Get status detail successful (200). Response content verified.")

    # --- Kịch bản 2: Không tìm thấy ---
    response_404 = await client.get(non_existent_url, headers=admin_token_headers)
    # --- Assert Not Found Response ---
    assert response_404.status_code == 404, f"GET 404 Resp: {response_404.text}"
    error_data_404 = response_404.json()
    assert "detail" in error_data_404
    assert (
        error_data_404["detail"]
        == f"Consultation Status '{NON_EXISTENT_STATUS_ID}' not found."
    )
    log.info("Get non-existent status correctly failed (404) with specific message.")


@pytest.mark.asyncio
async def test_admin_update_status(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_pipeline_data_with_lead,
    test_redis_client,
):
    """Test PUT /consultation-statuses/{id} - Cập nhật thành công, 404 (status/stage), cache."""
    log.info("--- Running: test_admin_update_status ---")
    status_b1_id = seed_pipeline_data_with_lead[
        "status_b1_id"
    ]  # ID: STATUS_B1, Stage: STAGE_B
    status_b1_url = AdminURLs.CONSULTATION_STATUS_DETAIL(status_b1_id)
    stage_a_id = seed_pipeline_data_with_lead["stage_a_id"]  # Stage hợp lệ khác
    non_existent_status_url = AdminURLs.CONSULTATION_STATUS_DETAIL(
        NON_EXISTENT_STATUS_ID
    )

    # "Mồi" cache
    await test_redis_client.set(PIPELINE_STATUSES_CACHE_KEY, json.dumps(["old_data"]))
    log.info("Cache primed before update.")

    # --- Kịch bản 1: Cập nhật thành công (chuyển sang STAGE_A) ---
    update_payload = {"name": "Updated Status B1", "stage_id": stage_a_id}
    response_success = await client.put(
        status_b1_url, json=update_payload, headers=admin_token_headers
    )
    # --- Assert Success Response ---
    assert (
        response_success.status_code == 200
    ), f"PUT Success Resp: {response_success.text}"
    data = response_success.json()
    assert data.get("name") == update_payload["name"]
    assert data.get("stage_id") == update_payload["stage_id"]
    log.info("Update status successful (200). Response content verified.")
    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_status = await session.get(models.ConsultationStatus, status_b1_id)
        assert db_status is not None
        assert db_status.name == update_payload["name"]
        assert db_status.stage_id == update_payload["stage_id"]
    log.info("DB state verified after update.")
    # --- Assert Cache Invalidation ---
    await assert_pipeline_cache_invalidated(
        test_redis_client, "Cache Invalidation check after PUT success"
    )

    # --- Kịch bản 2: Lỗi 404 (Status ID không tìm thấy) ---
    response_404_status = await client.put(
        non_existent_status_url, json=update_payload, headers=admin_token_headers
    )
    # --- Assert 404 Status Not Found ---
    assert (
        response_404_status.status_code == 404
    ), f"PUT 404 Status Resp: {response_404_status.text}"
    error_data_404s = response_404_status.json()
    assert "detail" in error_data_404s
    assert (
        error_data_404s["detail"]
        == f"Consultation Status '{NON_EXISTENT_STATUS_ID}' not found."
    )
    log.info("Update non-existent status correctly failed (404) with specific message.")

    # --- Kịch bản 3: Lỗi 404 (Stage ID mới không tìm thấy) ---
    payload_invalid_stage = {"stage_id": NON_EXISTENT_STAGE_ID}
    response_invalid_stage = await client.put(
        status_b1_url, json=payload_invalid_stage, headers=admin_token_headers
    )
    # --- Assert 404 Stage Not Found ---
    assert (
        response_invalid_stage.status_code == 404
    ), f"PUT Invalid Stage Resp: {response_invalid_stage.text}"
    error_data_stage = response_invalid_stage.json()
    assert "detail" in error_data_stage
    assert (
        error_data_stage["detail"]
        == f"Pipeline Stage '{NON_EXISTENT_STAGE_ID}' not found."
    )
    log.info(
        "Update status with non-existent Stage ID correctly failed (404) with specific message."
    )


@pytest.mark.asyncio
async def test_admin_delete_status_conflict_in_use_by_lead(
    client: AsyncClient, admin_token_headers: dict, seed_pipeline_data_with_lead
):
    """Test DELETE /consultation-statuses/{id} - Lỗi 409 (Status đang được Lead sử dụng)."""
    log.info("--- Running: test_admin_delete_status_conflict_in_use_by_lead ---")
    status_a1_id = seed_pipeline_data_with_lead[
        "status_a1_id"
    ]  # Đang được LEAD_1 sử dụng
    status_a1_url = AdminURLs.CONSULTATION_STATUS_DETAIL(status_a1_id)

    # --- Action ---
    response = await client.delete(status_a1_url, headers=admin_token_headers)

    # --- Assert 409 Response ---
    assert response.status_code == 409, f"DELETE Conflict Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert f"Cannot delete status '{status_a1_id}'" in error_data["detail"]
    assert "currently used by" in error_data["detail"]
    assert "leads" in error_data["detail"]  # Service trả về "leads"
    log.info(
        "Delete status in use by Lead correctly failed (409) with specific message."
    )


@pytest.mark.asyncio
async def test_admin_delete_status_success(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_pipeline_data_with_lead,
    test_redis_client,
):
    """Test DELETE /consultation-statuses/{id} - Xóa thành công status không bị ràng buộc, cache."""
    log.info("--- Running: test_admin_delete_status_success ---")
    status_b1_id = seed_pipeline_data_with_lead[
        "status_b1_id"
    ]  # STATUS_B1 không bị Lead nào dùng
    status_b1_url = AdminURLs.CONSULTATION_STATUS_DETAIL(status_b1_id)

    # "Mồi" cache
    await test_redis_client.set(PIPELINE_STATUSES_CACHE_KEY, json.dumps(["old_data"]))
    log.info("Cache primed before delete.")

    # --- Action ---
    response = await client.delete(status_b1_url, headers=admin_token_headers)

    # --- Assert Success Response ---
    assert (
        response.status_code == 204
    ), f"DELETE Success Resp: Status {response.status_code}, Text: {response.text}"
    log.info("Delete status successful (204).")

    # --- Assert DB State ---
    async with AsyncSessionLocal() as session:
        db_status = await session.get(models.ConsultationStatus, status_b1_id)
        assert db_status is None, "Status still exists in DB after deletion"
    log.info("DB state verified: Status deleted.")

    # --- Assert Cache Invalidation ---
    await assert_pipeline_cache_invalidated(
        test_redis_client, "Cache Invalidation check after DELETE success"
    )


@pytest.mark.asyncio
async def test_admin_delete_status_not_found(
    client: AsyncClient, admin_token_headers: dict
):
    """Test DELETE /consultation-statuses/{id} - Lỗi 404."""
    log.info("--- Running: test_admin_delete_status_not_found ---")
    non_existent_url = AdminURLs.CONSULTATION_STATUS_DETAIL(NON_EXISTENT_STATUS_ID)

    response = await client.delete(non_existent_url, headers=admin_token_headers)

    # --- Assert 404 Response ---
    assert response.status_code == 404, f"DELETE 404 Resp: {response.text}"
    error_data = response.json()
    assert "detail" in error_data
    assert (
        error_data["detail"]
        == f"Consultation Status '{NON_EXISTENT_STATUS_ID}' not found."
    )
    log.info("Delete non-existent status correctly failed (404) with specific message.")
