# tests/test_resilience.py
# -*- coding: utf-8 -*-
import asyncio
import logging
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.exceptions import ConnectionError, TimeoutError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from tests.fixtures.users import get_auth_headers
from app.config import settings

# Import các thành phần app
from app.database import AsyncSessionLocal
from app.services import organization_service, pipeline_service

# Import constants
from tests.fixtures.constants import (  # Sửa import này nếu cần
    NON_EXISTENT_ID,
    AdminURLs,
    AuthURLs,
    PipelineURLs,
    ProfileURLs,
    TestOrgData,
    TestPipelineData,
    TestUsers,
)

log = logging.getLogger(__name__)


# (Fixture seed_basic_pipeline_data giữ nguyên)
@pytest_asyncio.fixture(scope="function")
async def seed_basic_pipeline_data(setup_test_database):
    log.info(
        "--- [FIXTURE] Seeding basic pipeline data (unit, major, stage, status) ---"
    )
    unit_data = TestOrgData.UNIT_1
    major_data = TestOrgData.MAJOR_1
    stage_data = TestPipelineData.STAGE_A
    status_data = TestPipelineData.STATUS_A1
    status_data_fixed = status_data.copy()
    status_data_fixed["stage_id"] = stage_data["id"]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit1 = models.OrganizationUnit(**unit_data)
            # `Major` đã bị gỡ sau migration 3 tầng; `MajorProgram` là Level 1.
            major1 = models.MajorProgram(**major_data)
            stage_a = models.PipelineStage(**stage_data)
            status_a1 = models.ConsultationStatus(**status_data_fixed)
            session.add_all([unit1, major1, stage_a, status_a1])
    log.info("--- [FIXTURE] Basic pipeline data seeded ---")
    yield {
        "unit_id": unit_data["id"],
        "major_id": major_data["id"],
        "stage_a_id": stage_data["id"],
        "status_a1_id": status_data_fixed["id"],
    }


# ==================================
# === Test Resilience DB (Module 6)
# ==================================


@pytest.mark.asyncio
# <<< XÓA DÒNG @patch CHO db.rollback >>>
# @patch('app.services.organization_service.db.rollback', new_callable=AsyncMock)
@patch(
    "app.services.organization_service.create_major_program",
    new_callable=AsyncMock,
)
async def test_resilience_db_commit_failure_rolls_back(
    # <<< XÓA THAM SỐ mock_db_rollback >>>
    # mock_db_rollback: AsyncMock,
    mock_create_major: AsyncMock,
    client: AsyncClient,
    admin_token_headers: dict,
    setup_test_database,
    seed_basic_pipeline_data,
):
    """
    Test 6.1: Mô phỏng lỗi DB khi GHI bằng cách patch service.
    Kiểm tra: Ném đúng exception, DB không thay đổi (rollback).
    """
    log.info("--- Running: test_resilience_db_commit_failure_rolls_back ---")

    major_payload = {
        "name": "Fail Major",
        "code": "FM1",
        # `degree_level` là trường BẮT BUỘC của `MajorProgramCreate`; thiếu nó
        # thì request dừng ở 422 và không bao giờ chạm service — ca này sẽ xanh
        # vì lý do sai, không phải vì rollback hoạt động.
        "degree_level": "Cao đẳng",
        "unit_id": seed_basic_pipeline_data["unit_id"],
    }

    db_error_simulation = SQLAlchemyError(
        "Simulated Database Commit Error from Service"
    )

    # ⚠️ Mock KHÔNG được ném lỗi ngay. Nếu nó ném trước khi ghi gì, thì không có
    # INSERT nào xảy ra, và khẳng định "không tìm thấy hàng" ở dưới chỉ chứng
    # minh CHƯA TỪNG GHI — chứ không chứng minh transaction đã rollback. Ca sẽ
    # xanh kể cả khi cơ chế rollback bị gỡ sạch.
    #
    # Nên side effect phải: ghi thật vào session -> flush (hàng đã nằm trong
    # transaction) -> RỒI mới nổ. Khi ấy "không tìm thấy hàng ở session khác"
    # mới là bằng chứng của rollback.
    da_flush = {"xong": False}

    async def _ghi_roi_no(db, program_in, *args, **kwargs):
        db.add(
            models.MajorProgram(
                # id TƯỜNG MINH: fixture chèn MAJOR_1 với id=1 cố định, và một
                # INSERT có id tường minh KHÔNG làm nhích sequence của Postgres.
                # Để id tự sinh ở đây sẽ đụng `major_program_pkey` ngay từ 1 và
                # ca đỏ bằng IntegrityError — một lỗi khác hẳn thứ đang kiểm.
                id=9001,
                name=program_in.name,
                code=program_in.code,
                degree_level=program_in.degree_level,
                unit_id=program_in.unit_id,
            )
        )
        await db.flush()  # hàng đã tồn tại TRONG transaction
        da_flush["xong"] = True
        raise db_error_simulation

    mock_create_major.side_effect = _ghi_roi_no

    # Action và Assert Exception
    with pytest.raises(SQLAlchemyError) as exc_info:
        await client.post(
            AdminURLs.PROGRAMS, json=major_payload, headers=admin_token_headers
        )

    assert exc_info.value == db_error_simulation
    log.info(
        f"Correct exception ({type(db_error_simulation).__name__}) was raised by client call."
    )

    # 0. Bằng chứng hàng ĐÃ được ghi trước khi lỗi nổ — thiếu khẳng định này,
    #    phép kiểm bên dưới không phân biệt được "rollback đúng" với "chưa từng
    #    ghi".
    assert da_flush["xong"] is True, (
        "Mock chưa flush được hàng nào; phép kiểm rollback bên dưới sẽ vô nghĩa."
    )

    # 1. Assert DB State (Rollback)
    async with AsyncSessionLocal() as session:
        db_major = await session.scalar(
            select(models.MajorProgram).where(
                models.MajorProgram.code == major_payload["code"]
            )
        )
        assert (
            db_major is None
        ), "Data should not have been committed to DB after error (rollback failed)"
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
@patch("app.services.pipeline_service.safe_redis_get", new_callable=AsyncMock)
async def test_resilience_redis_cache_fallback(
    mock_safe_get: AsyncMock,
    client: AsyncClient,
    officer_doc_lap_token_headers: dict,
    seed_basic_pipeline_data: dict,
):
    log.info("--- Running: test_resilience_redis_cache_fallback ---")
    mock_safe_get.side_effect = ConnectionError("Simulated Redis Connection Error")
    pipeline_url = PipelineURLs.ALL
    # Dung token OFFICER, khong dung token vai tro `user`:
    # GET /api/pipeline/all nam trong OFFICER_TEMPLATE, con `role:user` la
    # BASIC_USER_TEMPLATE (chi profile/notification/session/security). Cay ke
    # thua la `g, role:officer, role:user` - officer ke thua user, khong nguoc
    # lai. tests/security/test_permissions_matrix.py:245 da khoa san bo ba
    # ("regular", "GET", PipelineURLs.ALL, 403), nen dung token vai tro user o
    # day la mau thuan voi chinh hop dong RBAC dang duoc canh.
    response = await client.get(pipeline_url, headers=officer_doc_lap_token_headers)
    assert response.status_code == 200
    data = response.json()
    assert "stages" in data
    assert "statuses" in data
    assert len(data["stages"]) == 1
    assert data["stages"][0]["id"] == seed_basic_pipeline_data["stage_a_id"]
    assert len(data["statuses"]) == 1
    assert data["statuses"][0]["id"] == seed_basic_pipeline_data["status_a1_id"]
    log.info("API correctly returned 200 OK by falling back to DB.")
    # BON luot, khong phai hai. Moi ham `get_all_*` doc cache HAI lan cho
    # cung mot khoa: mot lan truoc khi giu `redis_distributed_lock`, mot lan
    # nua NGAY SAU khi giu duoc (double-check chong cache stampede - worker
    # khac co the da nap lai cache trong luc minh cho lock). Hai ham x hai
    # luot = 4. Khang dinh "== 2" la di tich cua ban truoc khi co lock.
    #
    # Doi chieu ca BO KHOA chu khong chi con so: chi dem so luot thi mot ban
    # va lam doc nham cung mot khoa bon lan van xanh, trong khi khoa con lai
    # khong he duoc thu.
    assert mock_safe_get.await_count == 4
    cac_khoa_da_thu = {c.args[0] for c in mock_safe_get.await_args_list}
    assert cac_khoa_da_thu == {
        pipeline_service.PIPELINE_STAGES_CACHE_KEY,
        pipeline_service.PIPELINE_STATUSES_CACHE_KEY,
    }, f"Bo khoa da thu: {sorted(cac_khoa_da_thu)}"
    log.info("Cache (safe_redis_get) was called for both keys, twice each.")


@pytest.mark.asyncio
@patch("app.core.deps.safe_redis_exists", new_callable=AsyncMock)
async def test_resilience_redis_auth_fail_open(
    mock_safe_exists: AsyncMock,
    client: AsyncClient,
    regular_user_in_db: dict,
    test_redis_client,
):
    log.info("--- Running: test_resilience_redis_auth_fail_open ---")
    log.info("--- Testing fail-open on ACTIVE token ---")
    # Dung HELPER CHUNG thay vi tu doc `login_res.json()["access_token"]`:
    # 46cc9633 chuyen sang httpOnly cookie, login van tra 200 nhung KHONG con
    # dat access_token trong THAN phan hoi -> ban cu chet bang KeyError. Helper
    # `get_auth_headers` la duong ma moi fixture token khac dang di (doc tu
    # `res.cookies`), nen giu mot nguon chuan duy nhat cho viec lay token.
    #
    # Van dang nhap TRONG than test (khong dung fixture token) de lan login
    # nam trong cua so `@patch` giong ban goc, gia nguyen phep dem
    # `mock_safe_exists.await_count` o cuoi ca.
    active_headers = await get_auth_headers(
        client, regular_user_in_db, AuthURLs.LOGIN
    )
    log.info("Logged in with new active token.")
    mock_safe_exists.side_effect = ConnectionError(
        "Simulated Redis Connection Error during blacklist check"
    )
    log.info("Calling /profile with ACTIVE token while Redis check is failing...")
    response_fail_open = await client.get(ProfileURLs.PROFILE, headers=active_headers)
    assert response_fail_open.status_code == 200
    data = response_fail_open.json()
    assert data["id"] == regular_user_in_db["id"]
    log.info("API correctly returned 200 OK (fail-open) on active token.")
    assert mock_safe_exists.await_count == 2
    log.info("Auth dependency (safe_redis_exists) was called twice as expected.")
