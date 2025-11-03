# tests/routers/test_celery_worker_integration.py
# -*- coding: utf-8 -*-
import pytest
import pytest_asyncio
from httpx import AsyncClient
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func # Import func

# Import các thành phần app
from app.database import AsyncSessionLocal
from app import models, schemas
from app.config import settings
from app.celery_utils import process_automatic_lead_assignment_task

# Import constants và URLs
try:
    from ..fixtures.constants import (
        LeadsURLs, TestUsers, TestOrgData, TestPipelineData, AuthURLs
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)

# === Fixture Chuẩn Bị Dữ Liệu ===

@pytest_asyncio.fixture(scope="function")
async def seed_worker_test_data(setup_test_database, admin_user_in_db):
    """ Tạo dữ liệu nền tảng cho các bài test worker... (Sửa color_code) """
    log.info("--- [FIXTURE] Seeding data for Celery worker tests ---")
    unit1_data = {"id": 1, "name": "Worker Test Unit 1", "type": "Faculty"}
    unit2_data = {"id": 2, "name": "Worker Test Unit 2", "type": "Faculty"}
    major1_data = {"id": 1, "name": "Worker Test Major 1", "code": "WTM1", "unit_id": unit1_data["id"]}

    initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID
    assigned_status_id = settings.DEFAULT_ASSIGNED_LEAD_STATUS
    # QUAN TRỌNG: Cần status unassigned_pending để test trường hợp lỗi
    unassigned_pending_status_id = settings.DEFAULT_UNASSIGNED_LEAD_STATUS
    lost_status_id = settings.DEFAULT_LOST_LEAD_STATUS_ID

    stage_a_id = "STAGE_A_W"
    stage_lost_id = "STAGE_L_W"

    stage_a = {"id": stage_a_id, "name": "Worker Stage A", "order": 10}
    stage_lost = {"id": stage_lost_id, "name": "Worker Stage Lost", "order": 99}

    # --- SỬA color_code thành 6 ký tự hexa ---
    statuses_to_create = [
        {"id": initial_status_id, "name": "Initial Worker", "color_code": "#AAAAAA", "stage_id": stage_a_id},
        {"id": assigned_status_id, "name": "Assigned Worker", "color_code": "#BBBBBB", "stage_id": stage_a_id},
        {"id": unassigned_pending_status_id, "name": "Unassigned Worker", "color_code": "#CCCCCC", "stage_id": stage_a_id},
        {"id": lost_status_id, "name": "Lost Worker", "color_code": "#DDDDDD", "stage_id": stage_lost_id},
    ]
    # --- KẾT THÚC SỬA color_code ---

    valid_password_hash = admin_user_in_db.get("password_hash", "$2b$12$placeholderhashforworker")

    officer_idle_data = {"id": 101, "username": "worker_idle", "email": "idle@worker.com", "unit_id": unit1_data["id"], "max_capacity": 5, "last_assigned_at": None}
    officer_busy_data = {"id": 102, "username": "worker_busy", "email": "busy@worker.com", "unit_id": unit1_data["id"], "max_capacity": 3, "last_assigned_at": datetime.now(timezone.utc) - timedelta(days=1)}
    officer_recent_data = {"id": 103, "username": "worker_recent", "email": "recent@worker.com", "unit_id": unit1_data["id"], "max_capacity": 5, "last_assigned_at": datetime.now(timezone.utc) - timedelta(hours=1)}
    officer_other_unit_data = {"id": 104, "username": "worker_other", "email": "other@worker.com", "unit_id": unit2_data["id"], "max_capacity": 5, "last_assigned_at": None}

    officer_ids = { "idle": 101, "busy": 102, "recent": 103, "other_unit": 104 }

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add_all([models.OrganizationUnit(**unit1_data), models.OrganizationUnit(**unit2_data)])
            session.add(models.Major(**major1_data))
            session.add_all([models.PipelineStage(**stage_a), models.PipelineStage(**stage_lost)])
            session.add_all([models.ConsultationStatus(**s) for s in statuses_to_create])
            officers = [
                models.User(**officer_idle_data, role="officer", status="active", availability_status="available", password_hash=valid_password_hash),
                models.User(**officer_busy_data, role="officer", status="active", availability_status="available", password_hash=valid_password_hash),
                models.User(**officer_recent_data, role="officer", status="active", availability_status="available", password_hash=valid_password_hash),
                models.User(**officer_other_unit_data, role="officer", status="active", availability_status="available", password_hash=valid_password_hash),
            ]
            session.add_all(officers)
            busy_officer_leads = []
            for i in range(officer_busy_data["max_capacity"]):
                busy_officer_leads.append(models.Lead(
                    full_name=f"Busy Lead {i+1}", email=f"busy{i}@lead.com", phone=f"000{i}", source="test", # Phone ngắn
                    unit_id=unit1_data["id"], status=assigned_status_id, assigned_officer_id=officer_busy_data["id"]
                ))
            session.add_all(busy_officer_leads)

    log.info("--- [FIXTURE] Worker test data seeded ---")
    # Trả về ID status unassigned
    return {
        "unit1_id": unit1_data["id"],
        "major1_id": major1_data["id"],
        "officer_ids": officer_ids,
        "initial_status_id": initial_status_id,
        "assigned_status_id": assigned_status_id,
        "unassigned_status_id": unassigned_pending_status_id # Đổi tên key cho rõ
    }

# === Helper Functions ===

async def _create_lead_via_api(client: AsyncClient, headers: dict, unit_id: int, major_id: int, email_suffix: str = "") -> int:
    """Helper tạo lead mới qua API và trả về ID. (Đã sửa phone number)"""
    phone_number = f"090TEST{email_suffix[:10]}" # Đảm bảo < 20 ký tự
    payload = {
        "full_name": f"Worker Test Lead {email_suffix}",
        "email": f"worker_test{email_suffix}@example.com",
        "phone": phone_number,
        "source": "api_test",
        "unit_id": unit_id,
        "major_id": major_id
    }
    response = await client.post(LeadsURLs.LEADS, json=payload, headers=headers)
    if response.status_code != 201:
        pytest.fail(f"Failed to create lead via API (Status: {response.status_code}): {response.text}")
    lead_id = response.json().get("id")
    assert lead_id is not None
    log.info(f"Helper created lead via API (ID: {lead_id}) with phone: {phone_number}")
    return lead_id

async def _wait_for_lead_assignment(lead_id: int, expected_officer_id: int = None, expected_status: str = None, timeout: int = 20) -> models.Lead | None: # TĂNG TIMEOUT LÊN 20S
    """ Chờ đợi (poll DB) cho đến khi Lead đạt trạng thái mong đợi. """
    start_time = asyncio.get_event_loop().time()
    log.info(f"Polling DB for Lead ID {lead_id} (Timeout: {timeout}s). Expecting Officer: {expected_officer_id}, Status: {expected_status}")
    last_status = None
    last_officer_id = None
    while asyncio.get_event_loop().time() - start_time < timeout:
        await asyncio.sleep(0.5) # Chờ 0.5s trước mỗi lần check
        async with AsyncSessionLocal() as session:
            db_lead = await session.get(models.Lead, lead_id)
            if db_lead:
                last_status = db_lead.status
                last_officer_id = db_lead.assigned_officer_id
                
                # Check điều kiện mong đợi
                # Dùng 'is' để so sánh None
                officer_matches = (expected_officer_id is db_lead.assigned_officer_id) if expected_officer_id is None else (db_lead.assigned_officer_id == expected_officer_id)
                status_matches = (expected_status is db_lead.status) if expected_status is None else (db_lead.status == expected_status)
                
                if officer_matches and status_matches:
                    log.info(f"Lead ID {lead_id} reached expected state (Officer: {db_lead.assigned_officer_id}, Status: {db_lead.status}).")
                    return db_lead
            else:
                log.warning(f"Lead ID {lead_id} not found during polling.") # Có thể xảy ra nếu poll quá nhanh

    log.error(f"Timeout waiting for Lead ID {lead_id}. Last seen state: Officer={last_officer_id}, Status='{last_status}'. Expected: Officer={expected_officer_id}, Status='{expected_status}'.")
    return None

async def _check_assignment_log(lead_id: int, officer_id: int, method: str = "automatic"):
    """Kiểm tra sự tồn tại của AssignmentLog."""
    async with AsyncSessionLocal() as session:
        log_entry = await session.scalar(
            select(models.AssignmentLog).where(
                models.AssignmentLog.lead_id == lead_id,
                models.AssignmentLog.officer_id == officer_id,
                models.AssignmentLog.method == method
            ).limit(1) # Thêm limit(1) cho chắc chắn
        )
        assert log_entry is not None, f"AssignmentLog not found for lead {lead_id}, officer {officer_id}, method {method}"
    log.info(f"AssignmentLog verified for lead {lead_id}, officer {officer_id}.")

async def _check_officer_last_assigned(officer_id: int, check_is_recent: bool = True):
    """Kiểm tra last_assigned_at của Officer."""
    async with AsyncSessionLocal() as session:
        officer = await session.get(models.User, officer_id)
        assert officer is not None, f"Officer {officer_id} not found"
        assert officer.last_assigned_at is not None, f"Officer {officer_id} last_assigned_at should not be None"
        if check_is_recent:
            time_diff = datetime.now(timezone.utc) - officer.last_assigned_at
            # Tăng khoảng thời gian chấp nhận được lên, ví dụ 120 giây
            assert time_diff.total_seconds() < 120, f"Officer {officer_id} last_assigned_at is not recent (diff: {time_diff.total_seconds()}s)"
    log.info(f"Officer {officer_id} last_assigned_at verified.")


# === Các Bài Test (Giữ nguyên cấu trúc) ===

@pytest.mark.integration
@pytest.mark.asyncio
async def test_celery_assign_success_least_busy(client: AsyncClient, admin_token_headers: dict, seed_worker_test_data: dict, test_redis_client):
    """ (Giữ nguyên) """
    log.info("--- Running: test_celery_assign_success_least_busy ---")
    unit_id = seed_worker_test_data["unit1_id"]
    major_id = seed_worker_test_data["major1_id"]
    expected_officer_id = seed_worker_test_data["officer_ids"]["idle"]
    expected_status = seed_worker_test_data["assigned_status_id"]
    lead_id = await _create_lead_via_api(client, admin_token_headers, unit_id, major_id, "_leastbusy")
    assigned_lead = await _wait_for_lead_assignment(lead_id, expected_officer_id=expected_officer_id, expected_status=expected_status)
    assert assigned_lead is not None, f"Lead {lead_id} assignment timed out or failed"
    assert assigned_lead.assigned_officer_id == expected_officer_id
    assert assigned_lead.status == expected_status
    assert assigned_lead.assigned_at is not None
    await _check_assignment_log(lead_id, expected_officer_id)
    await _check_officer_last_assigned(expected_officer_id)
    log.info("--- Finished: test_celery_assign_success_least_busy ---")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_celery_assign_success_fairness(client: AsyncClient, admin_token_headers: dict, seed_worker_test_data: dict, test_redis_client):
    """ (GiGữ nguyên) """
    log.info("--- Running: test_celery_assign_success_fairness ---")
    unit_id = seed_worker_test_data["unit1_id"]
    major_id = seed_worker_test_data["major1_id"]
    expected_officer_id = seed_worker_test_data["officer_ids"]["idle"]
    expected_status = seed_worker_test_data["assigned_status_id"]
    lead_id = await _create_lead_via_api(client, admin_token_headers, unit_id, major_id, "_fairness")
    assigned_lead = await _wait_for_lead_assignment(lead_id, expected_officer_id=expected_officer_id, expected_status=expected_status)
    assert assigned_lead is not None, f"Lead {lead_id} assignment timed out or failed"
    assert assigned_lead.assigned_officer_id == expected_officer_id
    assert assigned_lead.status == expected_status
    await _check_assignment_log(lead_id, expected_officer_id)
    await _check_officer_last_assigned(expected_officer_id)
    log.info("--- Finished: test_celery_assign_success_fairness ---")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_celery_assign_officer_in_other_unit(client: AsyncClient, admin_token_headers: dict, seed_worker_test_data: dict, test_redis_client):
    """
    SỬA LẠI TEST NÀY: Kiểm tra Unit 2 được gán cho officer 104.
    (Thay thế test_celery_assign_no_available_officers_in_unit)
    """
    log.info("--- Running: test_celery_assign_officer_in_other_unit ---")
    unit_id = 2 # Unit 2
    major_id = seed_worker_test_data["major1_id"]
    # Mong đợi được gán cho officer 104 (thuộc Unit 2)
    expected_officer_id = seed_worker_test_data["officer_ids"]["other_unit"] 
    expected_status = seed_worker_test_data["assigned_status_id"]

    lead_id = await _create_lead_via_api(client, admin_token_headers, unit_id, major_id, "_unit2officer")
    
    # Wait & Verify
    updated_lead = await _wait_for_lead_assignment(lead_id, expected_officer_id=expected_officer_id, expected_status=expected_status)
    
    assert updated_lead is not None, f"Lead {lead_id} assignment timed out or failed"
    assert updated_lead.assigned_officer_id == expected_officer_id
    assert updated_lead.status == expected_status
    await _check_assignment_log(lead_id, expected_officer_id)
    await _check_officer_last_assigned(expected_officer_id)
    log.info(f"--- Finished: test_celery_assign_officer_in_other_unit (Assigned to {expected_officer_id}) ---")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_celery_assign_all_officers_full_capacity(client: AsyncClient, admin_token_headers: dict, seed_worker_test_data: dict, test_redis_client):
    """ (Giữ nguyên) """
    log.info("--- Running: test_celery_assign_all_officers_full_capacity ---")
    unit_id = seed_worker_test_data["unit1_id"]
    major_id = seed_worker_test_data["major1_id"]
    expected_status = seed_worker_test_data["unassigned_status_id"]
    idle_officer_id = seed_worker_test_data["officer_ids"]["idle"]
    recent_officer_id = seed_worker_test_data["officer_ids"]["recent"]
    idle_capacity = 5; recent_capacity = 5

    log.info(f"Filling capacity for officers {idle_officer_id} and {recent_officer_id}...")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            leads_to_add = []
            for i in range(idle_capacity): leads_to_add.append(models.Lead(full_name=f"IF{i}", email=f"if{i}@l.co", phone=f"11{i}", source="fill", unit_id=unit_id, status="assigned", assigned_officer_id=idle_officer_id))
            for i in range(recent_capacity): leads_to_add.append(models.Lead(full_name=f"RF{i}", email=f"rf{i}@l.co", phone=f"22{i}", source="fill", unit_id=unit_id, status="assigned", assigned_officer_id=recent_officer_id))
            session.add_all(leads_to_add)
    log.info("Capacity filled.")

    lead_id = await _create_lead_via_api(client, admin_token_headers, unit_id, major_id, "_fullcapacity")
    updated_lead = await _wait_for_lead_assignment(lead_id, expected_status=expected_status)
    assert updated_lead is not None, f"Lead {lead_id} status change timed out or failed"
    assert updated_lead.assigned_officer_id is None
    assert updated_lead.status == expected_status
    async with AsyncSessionLocal() as session:
        log_count = await session.scalar(select(func.count(models.AssignmentLog.id)).where(models.AssignmentLog.lead_id == lead_id))
        assert log_count == 0
    log.info("--- Finished: test_celery_assign_all_officers_full_capacity ---")