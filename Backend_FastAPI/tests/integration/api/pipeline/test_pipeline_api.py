# tests/routers/test_pipeline_api.py
# -*- coding: utf-8 -*-
import json  # Cần để làm việc với cache Redis
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func  # Cần để kiểm tra DB (mặc dù fixture đã seed)
from sqlalchemy import select

from app import models  # Cần để tạo dữ liệu mẫu
from app.config import settings  # Cần settings để lấy cache TTL

# Import các thành phần app
from app.database import AsyncSessionLocal
from app.services.pipeline_service import (  # Import cache keys
    PIPELINE_STAGES_CACHE_KEY,
    PIPELINE_STATUSES_CACHE_KEY,
)

# Import constants
try:
    # Đảm bảo bạn đã tạo file tests/fixtures/constants.py
    from ..fixtures.constants import (  # Không cần các constants khác cho file này
        PipelineURLs,
        TestPipelineData,
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# === Fixture để tạo dữ liệu pipeline mẫu ===
@pytest_asyncio.fixture(scope="function")
async def seed_pipeline_data(setup_test_database):
    """Tạo dữ liệu mẫu cho pipeline stages và statuses dùng constants."""
    log.info("--- [FIXTURE] Seeding pipeline data ---")
    # Lấy data từ constants
    stage1_data = TestPipelineData.STAGE_A
    stage2_data = TestPipelineData.STAGE_B
    status1_1_data = TestPipelineData.STATUS_A1
    status1_2_data = {
        "id": "S1_2",
        "name": "Status 1.2",
        "color_code": "#00FF00",
        "stage_id": stage1_data["id"],
    }  # Thêm status thứ 2 cho stage A
    status2_1_data = TestPipelineData.STATUS_B1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Tạo Stages
            stage1 = models.PipelineStage(**stage1_data)
            stage2 = models.PipelineStage(**stage2_data)
            session.add_all([stage1, stage2])

            # Tạo Statuses
            status1_1 = models.ConsultationStatus(**status1_1_data)
            status1_2 = models.ConsultationStatus(**status1_2_data)
            status2_1 = models.ConsultationStatus(**status2_1_data)
            session.add_all([status1_1, status1_2, status2_1])
    log.info("--- [FIXTURE] Pipeline data seeded ---")
    # Trả về dữ liệu đã tạo để test có thể sử dụng nếu cần
    # Sắp xếp sẵn để dễ so sánh
    seeded_stages = sorted([stage1_data, stage2_data], key=lambda x: x["order"])
    seeded_statuses = sorted(
        [status1_1_data, status1_2_data, status2_1_data], key=lambda x: x["id"]
    )
    return {"stages": seeded_stages, "statuses": seeded_statuses}


# === Tests ===


@pytest.mark.asyncio
async def test_get_pipeline_all_success_cache_miss(
    client: AsyncClient,
    regular_user_token_headers: dict,  # Endpoint này cần user thường là đủ
    seed_pipeline_data: dict,  # Sử dụng fixture seed data
    test_redis_client,  # Cần để kiểm tra cache
):
    """
    Test GET /pipeline/all thành công (Cache Miss).
    Kiểm tra response structure, content, và cache creation.
    """
    log.info("--- Running: test_get_pipeline_all_success_cache_miss ---")
    pipeline_url = PipelineURLs.ALL  # Dùng constant URL

    # --- Bước 1: Đảm bảo cache trống ---
    await test_redis_client.delete(
        PIPELINE_STAGES_CACHE_KEY, PIPELINE_STATUSES_CACHE_KEY
    )
    assert await test_redis_client.exists(PIPELINE_STAGES_CACHE_KEY) == 0
    assert await test_redis_client.exists(PIPELINE_STATUSES_CACHE_KEY) == 0
    log.info("Initial cache check OK: Cache keys do not exist.")

    # --- Bước 2: Gọi API lần đầu (Cache Miss) ---
    log.info("Calling API for the first time (expecting cache miss)...")
    response = await client.get(pipeline_url, headers=regular_user_token_headers)

    # --- Assert Response ---
    assert response.status_code == 200, f"GET Pipeline Resp: {response.text}"
    data = response.json()

    # 1. Kiểm tra cấu trúc JSON đúng
    assert isinstance(data, dict), "Response body should be a dictionary"
    assert "stages" in data, "Response missing 'stages' key"
    assert "statuses" in data, "Response missing 'statuses' key"
    assert isinstance(data["stages"], list), "'stages' should be a list"
    assert isinstance(data["statuses"], list), "'statuses' should be a list"

    # 2. Kiểm tra số lượng phần tử
    expected_stages = seed_pipeline_data["stages"]
    expected_statuses = seed_pipeline_data["statuses"]
    assert len(data["stages"]) == len(
        expected_stages
    ), f"Expected {len(expected_stages)} stages, got {len(data['stages'])}"
    assert len(data["statuses"]) == len(
        expected_statuses
    ), f"Expected {len(expected_statuses)} statuses, got {len(data['statuses'])}"

    # 3. Kiểm tra nội dung (so sánh list đã sắp xếp từ fixture và response)
    # Sắp xếp response để đảm bảo thứ tự khi so sánh
    response_stages_sorted = sorted(data["stages"], key=lambda x: x.get("order", 0))
    response_statuses_sorted = sorted(data["statuses"], key=lambda x: x.get("id", ""))

    assert response_stages_sorted == expected_stages, "Stages content mismatch"
    assert response_statuses_sorted == expected_statuses, "Statuses content mismatch"
    log.info("Response structure and content verified against seeded data.")

    # --- Assert Database State ---
    # Fixture `seed_pipeline_data` đã tạo dữ liệu, ở đây chỉ kiểm tra lại số lượng cho chắc chắn
    async with AsyncSessionLocal() as session:
        stage_count = await session.scalar(select(func.count(models.PipelineStage.id)))
        status_count = await session.scalar(
            select(func.count(models.ConsultationStatus.id))
        )
        assert stage_count == len(expected_stages), "DB stage count mismatch"
        assert status_count == len(expected_statuses), "DB status count mismatch"
    log.info("DB state briefly verified (counts match seeded data).")

    # --- Assert Cache Creation ---
    log.info("Verifying that data is now cached in Redis...")
    cached_stages_str = await test_redis_client.get(PIPELINE_STAGES_CACHE_KEY)
    cached_statuses_str = await test_redis_client.get(PIPELINE_STATUSES_CACHE_KEY)

    assert (
        cached_stages_str is not None
    ), f"Cache key '{PIPELINE_STAGES_CACHE_KEY}' not found after GET"
    assert (
        cached_statuses_str is not None
    ), f"Cache key '{PIPELINE_STATUSES_CACHE_KEY}' not found after GET"

    # Giải mã JSON từ cache và kiểm tra nội dung
    try:
        cached_stages = json.loads(cached_stages_str)
        cached_statuses = json.loads(cached_statuses_str)
        # Sắp xếp cache data để so sánh
        cached_stages_sorted = sorted(cached_stages, key=lambda x: x.get("order", 0))
        cached_statuses_sorted = sorted(cached_statuses, key=lambda x: x.get("id", ""))

        assert cached_stages_sorted == expected_stages, "Cached stages content mismatch"
        assert (
            cached_statuses_sorted == expected_statuses
        ), "Cached statuses content mismatch"

        # Kiểm tra TTL (xấp xỉ)
        stages_ttl = await test_redis_client.ttl(PIPELINE_STAGES_CACHE_KEY)
        statuses_ttl = await test_redis_client.ttl(PIPELINE_STATUSES_CACHE_KEY)
        expected_ttl = settings.CONFIG_CACHE_TTL_SECONDS
        assert (
            stages_ttl > 0 and stages_ttl <= expected_ttl
        ), f"Unexpected stages cache TTL: {stages_ttl}"
        assert (
            statuses_ttl > 0 and statuses_ttl <= expected_ttl
        ), f"Unexpected statuses cache TTL: {statuses_ttl}"
    except json.JSONDecodeError:
        pytest.fail("Cache data is not valid JSON")
    log.info("Redis cache correctly populated with correct content and TTL.")

    # --- Assert Side Effects Khác ---
    # Không có side effect nào khác (như Celery) cho endpoint này.

    log.info("--- Finished: test_get_pipeline_all_success_cache_miss ---")


@pytest.mark.asyncio
async def test_get_pipeline_all_success_cache_hit(
    client: AsyncClient,
    regular_user_token_headers: dict,
    seed_pipeline_data: dict,  # Cần fixture này để DB có dữ liệu thật
    test_redis_client,
):
    """Test GET /pipeline/all thành công (Cache Hit), trả về dữ liệu từ cache."""
    log.info("--- Running: test_get_pipeline_all_success_cache_hit ---")
    pipeline_url = PipelineURLs.ALL

    # --- Bước 1: "Mồi" cache bằng dữ liệu giả ---
    # Dữ liệu này khác với dữ liệu thật trong DB (từ seed_pipeline_data)
    fake_stages_data = [{"id": "FAKE_S", "name": "Fake Stage CACHED", "order": 999}]
    fake_statuses_data = [
        {
            "id": "FAKE_T",
            "name": "Fake Status CACHED",
            "color_code": "#111111",
            "stage_id": "FAKE_S",
        }
    ]

    await test_redis_client.set(PIPELINE_STAGES_CACHE_KEY, json.dumps(fake_stages_data))
    await test_redis_client.set(
        PIPELINE_STATUSES_CACHE_KEY, json.dumps(fake_statuses_data)
    )
    log.info("Populated Redis cache with FAKE data.")

    # --- Bước 2: Gọi API (nên trả về dữ liệu FAKE từ cache) ---
    log.info("Calling API (expecting cache hit with FAKE data)...")
    response = await client.get(pipeline_url, headers=regular_user_token_headers)

    # --- Assert Response (phải khớp FAKE data) ---
    assert response.status_code == 200, f"Cache Hit Resp: {response.text}"
    data = response.json()

    assert "stages" in data
    assert "statuses" in data
    # So sánh với fake data (không cần sắp xếp vì chỉ có 1 phần tử)
    assert (
        data["stages"] == fake_stages_data
    ), "Response stages should match FAKE cached data"
    assert (
        data["statuses"] == fake_statuses_data
    ), "Response statuses should match FAKE cached data"
    log.info("Response matches FAKE cached data. Cache hit confirmed.")

    # --- Assert Database State ---
    # Đảm bảo DB vẫn chứa dữ liệu thật từ fixture (không bị ảnh hưởng bởi cache hit)
    async with AsyncSessionLocal() as session:
        stage_count = await session.scalar(select(func.count(models.PipelineStage.id)))
        status_count = await session.scalar(
            select(func.count(models.ConsultationStatus.id))
        )
        assert stage_count == len(
            seed_pipeline_data["stages"]
        ), "DB stage count should remain unchanged"
        assert status_count == len(
            seed_pipeline_data["statuses"]
        ), "DB status count should remain unchanged"
    log.info("DB state verified: Data remains unchanged after cache hit.")

    log.info("--- Finished: test_get_pipeline_all_success_cache_hit ---")


@pytest.mark.asyncio
async def test_get_pipeline_all_unauthenticated(client: AsyncClient):
    """Test GET /pipeline/all khi chưa đăng nhập (401)."""
    log.info("--- Running: test_get_pipeline_all_unauthenticated ---")
    pipeline_url = PipelineURLs.ALL
    response = await client.get(pipeline_url)  # Không có headers

    # --- Assert Error Response ---
    assert response.status_code == 401, f"Unauth Resp: {response.text}"  # Unauthorized
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Not authenticated"  # Message mặc định
    log.info("Unauthenticated access correctly blocked (401) with default message.")
    log.info("--- Finished: test_get_pipeline_all_unauthenticated ---")
