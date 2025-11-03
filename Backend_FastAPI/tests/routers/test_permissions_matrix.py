# tests/routers/test_permissions_matrix.py
# -*- coding: utf-8 -*-
import pytest
import pytest_asyncio
from httpx import AsyncClient
import logging
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

# Import các thành phần app
from app.database import AsyncSessionLocal
from app import models, schemas
from app.main import app as imported_app_instance
# from app.security import get_password_hash # <<< KHÔNG CẦN NỮA
# from casbin_async_sqlalchemy_adapter import CasbinRule # <<< KHÔNG CẦN NỮA

# Import constants
try:
    from ..fixtures.constants import (
        AdminURLs,
        LeadsURLs,
        ProfileURLs,
        PipelineURLs,
        TestUsers, # Cần cho MOCK_PAYLOADS
        TestLeadData,
        TestOrgData,
        TestPipelineData,
        AuthURLs
    )
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)

# ==================================
# === Fixture Tạo Dữ Liệu Phụ Thuộc ===
# (KHÔNG TẠO USER Ở ĐÂY)
# ==================================
@pytest_asyncio.fixture(scope="function")
async def test_data_for_matrix(
    setup_test_database,
    admin_user_in_db: dict,
    officer_user_in_db: dict,
    manager_user_in_db: dict,
    regular_user_in_db: dict
):
    # ... (code fixture giữ nguyên) ...
    log.info("--- [FIXTURE] Seeding DEPENDENT data for matrix (Function Scope) ---")
    admin_id = admin_user_in_db["id"]
    officer_id = officer_user_in_db["id"]
    manager_id = manager_user_in_db["id"]
    regular_id = regular_user_in_db["id"]
    log.debug(f"Using auto-generated IDs - Admin: {admin_id}, Officer: {officer_id}, Manager: {manager_id}, Regular: {regular_id}")
    unit1 = models.OrganizationUnit(**TestOrgData.UNIT_1)
    major1 = models.Major(**TestOrgData.MAJOR_1)
    stage_a = models.PipelineStage(**TestPipelineData.STAGE_A)
    status_a1_data = TestPipelineData.STATUS_A1.copy()
    status_a1_data["stage_id"] = stage_a.id
    status_a1 = models.ConsultationStatus(**status_a1_data)
    lead_data = TestLeadData.LEAD_1
    lead1 = models.Lead(
        id=1, # ID cố định cho Lead
        full_name=lead_data["full_name"], email=lead_data["email"], phone=lead_data["phone"],
        source=lead_data["source"], unit_id=unit1.id, major_id=major1.id, status=status_a1.id,
        consultation_status_id=status_a1.id, pipeline_stage_id=stage_a.id,
        assigned_officer_id=officer_id
    )
    lead_db_id = None
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add_all([unit1, major1, stage_a, status_a1, lead1])
            await session.flush()
            lead_db_id = lead1.id
            if not lead_db_id:
                raise Exception("Failed to get auto-generated ID for Lead")
    log.info(f"--- [FIXTURE] Matrix DEPENDENT data seeded (Lead ID: {lead_db_id}) ---")
    return {
        "lead_id": lead_db_id,
        "lead_id_str": str(lead_db_id),
        "consultation_id_str": "1",
        "unit_id_str": str(unit1.id),
        "major_id_str": str(major1.id),
        "stage_id_str": stage_a.id,
        "status_id_str": status_a1.id,
        "admin_id": admin_id,
        "officer_id": officer_id,
        "manager_id": manager_id,
        "regular_id": regular_id,
    }


# === SỬA PERMISSION_MATRIX ===
# (Giữ nguyên như lần sửa 8 - dùng string key)
PERMISSION_MATRIX = [
    # --- Admin (Toàn quyền) ---
    ("admin", "GET", AdminURLs.USERS, 200),
    ("admin", "GET", AdminURLs.PIPELINE_STAGES, 200),
    ("admin", "DELETE", lambda d: AdminURLs.PIPELINE_STAGE_DETAIL(d["stage_id_str"]), 409),
    ("admin", "GET", LeadsURLs.LEADS, 200),
    ("admin", "PUT", lambda d: LeadsURLs.LEAD_DETAIL(d["lead_id_str"]), 200),
    ("admin", "GET", ProfileURLs.PROFILE, 200),

    # --- Manager ---
    ("manager", "GET", AdminURLs.USERS, 200),
    ("manager", "GET", LeadsURLs.LEADS, 200),
    ("manager", "PUT", lambda d: LeadsURLs.LEAD_DETAIL(d["lead_id_str"]), 200),
    ("manager", "GET", AdminURLs.PIPELINE_STAGES, 403),
    ("manager", "POST", AdminURLs.PIPELINE_STAGES, 403),
    ("manager", "GET", lambda d: AdminURLs.ASSIGNMENT_CONFIG_DETAIL(d["unit_id_str"]), 403),
    ("manager", "DELETE", AdminURLs.POLICIES, 403),

    # --- Officer ---
    ("officer", "GET", LeadsURLs.LEADS, 200),
    ("officer", "GET", lambda d: LeadsURLs.LEAD_DETAIL(d["lead_id_str"]), 200),
    ("officer", "POST", lambda d: LeadsURLs.CONSULTATIONS(d["lead_id_str"]), 201),
    ("officer", "POST", lambda d: LeadsURLs.ACTION(d["lead_id_str"]), 200),
    ("officer", "PUT", lambda d: LeadsURLs.LEAD_DETAIL(d["lead_id_str"]), 403),
    ("officer", "POST", lambda d: LeadsURLs.ASSIGN(d["lead_id_str"]), 403),
    ("officer", "GET", AdminURLs.USERS, 403),
    ("officer", "GET", ProfileURLs.PROFILE, 200),

    # --- Regular User ---
    ("regular", "GET", ProfileURLs.PROFILE, 200),
    ("regular", "PUT", ProfileURLs.PROFILE, 200),
    ("regular", "GET", LeadsURLs.LEADS, 403),
    ("regular", "GET", lambda d: LeadsURLs.LEAD_DETAIL(d["lead_id_str"]), 403),
    ("regular", "GET", AdminURLs.USERS, 403),
    ("regular", "GET", PipelineURLs.ALL, 403),
]

# Định nghĩa ID cố định mà fixture `test_data_for_matrix` SẼ sử dụng
FIXED_LEAD_ID_FOR_MATRIX = 1
FIXED_OFFICER_ID_FOR_MATRIX = 2 # Giả sử ID officer là 2 (từ fixture conftest)
MOCK_PAYLOADS = {
    "PUT": {"full_name": "Matrix Test Update"}, # Payload chung cho PUT
    "POST": {
        # Key cụ thể cho từng URL động
        f"/api/leads/{FIXED_LEAD_ID_FOR_MATRIX}/consultations": {"method": "call", "notes": "Matrix test", "status_id": TestPipelineData.STATUS_A1["id"]},
        f"/api/leads/{FIXED_LEAD_ID_FOR_MATRIX}/action": {"action": "reassign", "reason": "Matrix Test"},

        # <<< THÊM PAYLOAD CHO ASSIGN >>>
        f"/api/leads/{FIXED_LEAD_ID_FOR_MATRIX}/assign": {"officer_id": FIXED_OFFICER_ID_FOR_MATRIX},

        # Key tĩnh
        AdminURLs.PIPELINE_STAGES: {"id": "dummy", "name": "Dummy", "order": 999},
    }
}

# === Sửa TEST FUNCTION ===
@pytest.mark.asyncio
@pytest.mark.parametrize("user_role_key, http_method, endpoint_func, expected_status", PERMISSION_MATRIX)
async def test_permission_matrix(
    user_role_key: str,
    http_method: str,
    endpoint_func,
    expected_status: int,
    client: AsyncClient,
    test_data_for_matrix: dict,
    admin_token_headers: dict,
    manager_token_headers: dict,
    officer_token_headers: dict,
    regular_user_token_headers: dict
    # <<< KHÔNG CẦN app_instance VÌ ĐÃ IMPORT TRỰC TIẾP >>>
):
    """
    Test 7.1: Tự động kiểm tra ma trận phân quyền.
    """
    # 1. Chọn đúng token headers (giữ nguyên)
    token_headers = None
    if user_role_key == "admin":
        token_headers = admin_token_headers
    elif user_role_key == "manager":
        token_headers = manager_token_headers
    elif user_role_key == "officer":
        token_headers = officer_token_headers
    elif user_role_key == "regular":
        token_headers = regular_user_token_headers
    else:
        pytest.fail(f"Invalid user_role_key '{user_role_key}' in PERMISSION_MATRIX")
    user_role = user_role_key

    # 2. Xây dựng URL (giữ nguyên)
    if callable(endpoint_func):
        endpoint_url = endpoint_func(test_data_for_matrix)
    else:
        endpoint_url = str(endpoint_func)

    log.info(f"--- Testing Matrix: [{user_role}] -> {http_method} {endpoint_url} (Expect: {expected_status}) ---")

    # 3. Lấy payload giả lập (SỬA LẠI LOGIC NÀY)
    json_payload = None
    if http_method in ["POST", "PUT"]:

        # Lấy payload chung cho method (ví dụ: PUT)
        json_payload = MOCK_PAYLOADS.get(http_method, {})

        # Nếu là POST, kiểm tra xem có payload cụ thể cho URL không
        if http_method == "POST":
            # endpoint_url đã được build (ví dụ: /api/leads/1/assign)
            specific_post_payload = json_payload.get(endpoint_url)
            if specific_post_payload:
                json_payload = specific_post_payload # Dùng payload cụ thể
            else:
                # Nếu không có payload cụ thể cho URL động, kiểm tra URL tĩnh
                if not callable(endpoint_func): 
                     specific_post_payload = json_payload.get(str(endpoint_func))
                     if specific_post_payload:
                         json_payload = specific_post_payload
                     else:
                         json_payload = {} # Dùng dict rỗng nếu không tìm thấy
                else:
                     json_payload = {} # Dùng dict rỗng cho URL động không có mock

        # Đảm bảo json_payload là dict
        if json_payload is None or not isinstance(json_payload, dict):
             json_payload = {}

        log.debug(f"Using payload for {http_method} {endpoint_url}: {json_payload}")


    # 4. Action (SỬA LỖI Ở ĐÂY)
    # <<< SỬA: Dùng 'imported_app_instance' đã import trực tiếp >>>
    if hasattr(imported_app_instance.state, 'enforcer') and imported_app_instance.state.enforcer:
        await imported_app_instance.state.enforcer.load_policy()
        log.debug("Reloaded Casbin policies before request")
    # <<< KẾT THÚC SỬA >>>

    response = await client.request(
        method=http_method,
        url=endpoint_url,
        headers=token_headers,
        json=json_payload
    )

    # 5. Assert (giữ nguyên)
    assert response.status_code == expected_status, \
        f"FAIL: [{user_role}] -> {http_method} {endpoint_url}. Expected {expected_status}, Got {response.status_code}. Resp: {response.text}"

    log.info(f"--- PASS: [{user_role}] -> {http_method} {endpoint_url} == {response.status_code} ---")