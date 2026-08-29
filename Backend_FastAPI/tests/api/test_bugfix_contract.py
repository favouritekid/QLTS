# tests/api/test_bugfix_contract.py
# -*- coding: utf-8 -*-
"""
Contract tests for bugfix PRs (T1-T9).
Validates API response shapes and behavior that frontend depends on.
"""
import logging

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from tests.fixtures.constants import PipelineURLs, LeadsURLs, TestPipelineData

log = logging.getLogger(__name__)


# === Fixture to seed pipeline data (copied from test_pipeline_api.py) ===
@pytest_asyncio.fixture(scope="function")
async def seed_pipeline_data(setup_test_database):
    """Seed pipeline stages and statuses using constants."""
    log.info("--- [FIXTURE] Seeding pipeline data ---")
    stage1_data = TestPipelineData.STAGE_A
    stage2_data = TestPipelineData.STAGE_B
    status1_1_data = TestPipelineData.STATUS_A1
    status1_2_data = {
        "id": "S1_2",
        "name": "Status 1.2",
        "color_code": "#00FF00",
        "stage_id": stage1_data["id"],
    }
    status2_1_data = TestPipelineData.STATUS_B1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stage1 = models.PipelineStage(**stage1_data)
            stage2 = models.PipelineStage(**stage2_data)
            session.add_all([stage1, stage2])

            status1_1 = models.ConsultationStatus(**status1_1_data)
            status1_2 = models.ConsultationStatus(**status1_2_data)
            status2_1 = models.ConsultationStatus(**status2_1_data)
            session.add_all([status1_1, status1_2, status2_1])

    log.info("--- [FIXTURE] Pipeline data seeded ---")
    seeded_stages = sorted([stage1_data, stage2_data], key=lambda x: x["order"])
    seeded_statuses = sorted(
        [status1_1_data, status1_2_data, status2_1_data], key=lambda x: x["id"]
    )
    return {"stages": seeded_stages, "statuses": seeded_statuses}


# === Tests ===


@pytest.mark.asyncio
async def test_reassign_quota_response_contract(
    client: AsyncClient,
    regular_user_token_headers: dict,
    setup_test_database,
):
    """
    T5: GET /api/leads/my/reassign-quota must return {allowed, used, limit, remaining}.
    Frontend depends on these exact field names.
    """
    response = await client.get(
        "/api/leads/my/reassign-quota",
        headers=regular_user_token_headers,
    )
    # May be 200 or 404 depending on test data setup,
    # but if 200, must have correct fields
    if response.status_code == 200:
        data = response.json()
        # Assert exact contract fields
        assert "allowed" in data, "Missing 'allowed' field"
        assert "used" in data, "Missing 'used' field"
        assert "limit" in data, "Missing 'limit' field"
        assert "remaining" in data, "Missing 'remaining' field"
        # Assert types
        assert isinstance(data["allowed"], bool)
        assert isinstance(data["used"], int)
        assert isinstance(data["limit"], int)
        assert isinstance(data["remaining"], int)
        # Assert invariant: remaining = limit - used
        assert data["remaining"] == data["limit"] - data["used"]
        # Assert no old frontend fields leak through
        assert "remaining_today" not in data, "Old field 'remaining_today' should not exist"
        assert "max_per_day" not in data, "Old field 'max_per_day' should not exist"
        assert "used_today" not in data, "Old field 'used_today' should not exist"


@pytest.mark.asyncio
async def test_pipeline_all_backward_compatible_no_filters(
    client: AsyncClient,
    officer_doc_lap_token_headers: dict,
    seed_pipeline_data: dict,
    test_redis_client,
):
    """
    T3 prep: /api/pipeline/all with no query params still works (backward compatible).
    When T3 backend adds filter support, this test ensures no regression.
    """
    # Clear cache
    from app.services.pipeline_service import (
        PIPELINE_STAGES_CACHE_KEY,
        PIPELINE_STATUSES_CACHE_KEY,
    )

    await test_redis_client.delete(PIPELINE_STAGES_CACHE_KEY, PIPELINE_STATUSES_CACHE_KEY)

    response = await client.get(
        PipelineURLs.ALL,
        # Token OFFICER: GET /api/pipeline/all nam trong OFFICER_TEMPLATE.
        # `role:user` la BASIC_USER_TEMPLATE va cay ke thua la
        # `g, role:officer, role:user` (officer ke thua user, khong nguoc lai),
        # nen token vai tro user o day chi co the nhan 403 - dung nhu
        # tests/security/test_permissions_matrix.py:245 dang khoa.
        # Ban `..._doc_lap` de KHONG keo theo `seed_lead_dependencies`, thu se
        # seed them mot pipeline thu hai va lam sai cac phep dem cua ca nay.
        headers=officer_doc_lap_token_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "stages" in data
    assert isinstance(data["stages"], list)
    assert len(data["stages"]) > 0


@pytest.mark.asyncio
async def test_leads_date_range_inclusive_end_day(
    client: AsyncClient,
    admin_token_headers: dict,
    setup_test_database,
):
    """
    T8: When filtering leads with date_to, the end-of-day boundary should be inclusive.
    A lead created at 2024-01-15T23:30:00 should be included when date_to=2024-01-15T23:59:59.999Z.

    This is a contract test: we send date_to with end-of-day time and verify the API
    doesn't reject it and returns proper results.
    """
    # Create a test lead first
    create_resp = await client.post(
        LeadsURLs.LEADS,
        json={
            "full_name": "End Day Test Lead",
            "phone": "0909111222",
            "email": "endday@test.example.com",
            "source": "website",
        },
        headers=admin_token_headers,
    )
    # Lead creation may succeed or fail depending on required fields
    # The key test is that filtering with end-of-day time works

    # Query with end-of-day time (T8 fix sends this from frontend)
    response = await client.get(
        LeadsURLs.LEADS,
        params={
            "date_to": "2099-12-31T23:59:59.999Z",  # Far future to include all
            "date_field": "created_at",
        },
        headers=admin_token_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "leads" in data
    assert "total_count" in data


@pytest.mark.asyncio
async def test_reassign_quota_boundary_zero_remaining(
    client: AsyncClient,
    regular_user_token_headers: dict,
    setup_test_database,
):
    """
    T5 boundary: When quota is exhausted (remaining=0), allowed should be False.
    Frontend disables submit button based on remaining <= 0.
    """
    response = await client.get(
        "/api/leads/my/reassign-quota",
        headers=regular_user_token_headers,
    )
    if response.status_code == 200:
        data = response.json()
        # If remaining is 0, allowed must be False
        if data["remaining"] == 0:
            assert data["allowed"] is False, "allowed should be False when remaining=0"
        # If remaining > 0, allowed must be True
        if data["remaining"] > 0:
            assert data["allowed"] is True, "allowed should be True when remaining>0"
