# tests/api/test_admin_casbin.py
# -*- coding: utf-8 -*-
"""Flow CRUD của policy (`p`) và role assignment (`g`) qua HTTP thật.

Hai ca ở đây đỏ ổn định trong nightly (3 lượt độc lập trên `ffb45291`, tái lập
trên `ff78b45f`) với:

    AssertionError: POST Policy Resp: {"detail":"Not Found","error_code":"HTTP_404"}
    AssertionError: POST Role Resp:   {"detail":"Not Found","error_code":"HTTP_404"}

Đó là 404 của FastAPI cho **route không tồn tại**, KHÔNG phải 404-thay-403 của
hợp đồng IDOR. Hằng trong `tests/fixtures/constants.py` trỏ `/api/admin/policies`
và `/api/admin/assign-role`; đường THẬT là `/api/admin/roles/...` (ghép từ
`roles.py:61` prefix `/roles` + `admin/__init__.py:54` prefix `/admin` +
`main.py:957` prefix `/api`). Hạ kỳ vọng xuống 404 sẽ khoá vĩnh viễn hai ca
không hề chạm tới endpoint nào.

Sau khi xuyên qua 404, tệp còn ba lệch hợp đồng nữa, đều được sửa ở đây:

1. Khoá phản hồi là **`detail`**, không phải `message`. Router trả
   `{"detail": ...}` (roles.py:256/347/388/426) và
   `base_app_exception_handler` (middleware/exception_handlers.py:125-126) cũng
   dựng `detail` + `error_code`. `message` chưa bao giờ tồn tại.
2. Hàng policy có **BỐN** trường. `auth_model.conf:5` khai
   `p = sub, obj, act, eft`, nên `GET /policies` trả `[sub, obj, act, eft]`;
   phép so tuple ba trường không bao giờ khớp.
3. Policy tạo qua API luôn `eft="allow"` — payload API chỉ có ba trường và
   `chuan_hoa_rule` (casbin_service.py:137) chuẩn hoá về `"allow"`. Đây là
   SEMANTICS của đường này, không phải giá trị điền cho đủ: nếu mai kia POST
   dựng ra `deny` mà không ai nhận ra, các ca dưới phải đỏ.

⚠️ Hai đường gán/thu hồi dùng HAI hằng RIÊNG (`ASSIGN_ROLE` ↔ `REVOKE_ROLE`).
Một hằng chung cho hai hành động rồi phân biệt bằng HTTP method chính là hình
dạng đã đẻ ra lỗi ở frontend.
"""
import logging

import pytest
import pytest_asyncio
from casbin_async_sqlalchemy_adapter import CasbinRule  # Cần model CasbinRule
from httpx import AsyncClient
from sqlalchemy import select

# Import các thành phần app
from app.database import AsyncSessionLocal
from app.schemas.permissions import PolicyCreate, RoleAssignment  # Cần schemas

# Import constants
try:
    from tests.fixtures.constants import NON_EXISTENT_ID, AdminURLs, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)

# `eft` mà mọi policy tạo qua API mang. Xem `casbin_service.EFT_MAC_DINH`.
EFT_ALLOW = "allow"


# === Helper kiểm tra DB Casbin ===
async def get_casbin_rule_from_db(
    ptype: str, v0: str, v1: str, v2: str = None, v3: str = None
):
    """Helper kiểm tra sự tồn tại của rule trong DB (NGUỒN BỀN VỮNG).

    ``v3`` (tức ``eft``) là tham số RIÊNG chứ không mặc định ``"allow"``: hàng
    ``g`` chỉ có hai trường, nên ép ``v3`` cho mọi lời gọi sẽ làm ca role không
    bao giờ tìm thấy gì.

    Vì sao phải lọc được ``v3``: sau B1 một cặp ``(sub, obj, act)`` có thể tồn
    tại ĐỒNG THỜI ở hai bản ``allow`` và ``deny``. Không lọc thì
    ``scalar_one_or_none()`` ném ``MultipleResultsFound`` — một lỗi trông như
    hạ tầng chứ không như lệch hợp đồng.
    """
    async with AsyncSessionLocal() as session:
        query = select(CasbinRule).where(
            CasbinRule.ptype == ptype, CasbinRule.v0 == v0, CasbinRule.v1 == v1
        )
        if v2:
            query = query.where(CasbinRule.v2 == v2)
        if v3:
            query = query.where(CasbinRule.v3 == v3)

        result = await session.execute(query)
        return result.scalar_one_or_none()


# ==================================
# === Tests API Quản lý Policy (p)
# ==================================


@pytest.mark.asyncio
async def test_admin_casbin_policy_crud_flow(
    client: AsyncClient, admin_token_headers: dict, setup_test_database  # Cần DB sạch
):
    """
    Flow CRUD hoàn chỉnh cho ``/api/admin/roles/policies``.
    Kiểm tra: POST (201), POST (409), GET, DELETE (200), DELETE (404).
    """
    log.info("--- Running: test_admin_casbin_policy_crud_flow ---")

    policy_payload = {
        "subject": "role:test_policy",
        "object": "/api/test/policy",
        "action": "GET",
    }
    policy_schema = PolicyCreate(**policy_payload)

    # --- 1. POST (Create) ---
    log.info("Testing POST /api/admin/roles/policies (Create)...")
    response_post = await client.post(
        AdminURLs.POLICIES, json=policy_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_post.status_code == 201, f"POST Policy Resp: {response_post.text}"
    assert response_post.json()["detail"] == "Policy added successfully."
    # Assert DB (nguồn bền vững, ĐỦ bốn trường — `eft` phải là "allow")
    db_rule_post = await get_casbin_rule_from_db(
        "p",
        policy_schema.subject,
        policy_schema.object,
        policy_schema.action,
        EFT_ALLOW,
    )
    assert db_rule_post is not None, "Policy not found in DB after creation"
    log.info("POST /policies (Create) successful.")

    # --- 2. POST (Duplicate) ---
    log.info("Testing POST /api/admin/roles/policies (Duplicate)...")
    response_dupe = await client.post(
        AdminURLs.POLICIES, json=policy_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_dupe.status_code == 409, f"POST Dupe Resp: {response_dupe.text}"
    assert "Policy already exists" in response_dupe.json()["detail"]
    log.info("POST /policies (Duplicate) correctly blocked (409).")

    # --- 3. GET (List) ---
    log.info("Testing GET /api/admin/roles/policies (List)...")
    response_get = await client.get(AdminURLs.POLICIES, headers=admin_token_headers)
    assert response_get.status_code == 200
    policy_list = response_get.json()
    assert isinstance(policy_list, list)
    # Hàng policy có BỐN trường (`auth_model.conf:5`: p = sub, obj, act, eft).
    # Khẳng định RÕ trường thứ tư là "allow" thay vì chỉ so ba trường đầu: đường
    # POST này chỉ dựng được policy allow, nên một hàng `deny` xuất hiện ở đây
    # là đổi ngữ nghĩa, và ca phải đỏ.
    expected_policy = [
        policy_schema.subject,
        policy_schema.object,
        policy_schema.action,
        EFT_ALLOW,
    ]
    assert expected_policy in policy_list, (
        "Created policy not found in GET list; hàng có prefix (sub, obj, act) "
        f"khớp: {[p for p in policy_list if p[:3] == expected_policy[:3]]}"
    )
    log.info("GET /policies successful, created policy found.")

    # --- 4. DELETE (Success) ---
    log.info("Testing DELETE /api/admin/roles/policies (Success)...")
    response_del = await client.request(  # Dùng .request() vì DELETE có body
        "DELETE", AdminURLs.POLICIES, json=policy_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_del.status_code == 200, f"DELETE Resp: {response_del.text}"
    assert response_del.json()["detail"] == "Policy removed successfully."
    # Assert DB
    db_rule_del = await get_casbin_rule_from_db(
        "p",
        policy_schema.subject,
        policy_schema.object,
        policy_schema.action,
        EFT_ALLOW,
    )
    assert db_rule_del is None, "Policy still found in DB after deletion"
    log.info("DELETE /policies (Success) successful.")

    # --- 5. DELETE (Not Found) ---
    log.info("Testing DELETE /api/admin/roles/policies (Not Found)...")
    response_del_404 = await client.request(
        "DELETE",
        AdminURLs.POLICIES,
        json=policy_payload,  # Xóa lại policy cũ
        headers=admin_token_headers,
    )
    # Assert Response — 404 này là hợp đồng THẬT của endpoint (
    # `ResourceNotFoundError` ở roles.py:315), khác hẳn 404 "route không tồn
    # tại" mà bản cũ nhận. Chuỗi `detail` phân biệt được hai loại.
    assert (
        response_del_404.status_code == 404
    ), f"DELETE 404 Resp: {response_del_404.text}"
    assert "Policy not found" in response_del_404.json()["detail"]
    log.info("DELETE /policies (Not Found) correctly failed (404).")


# ==================================
# === Tests API Quản lý Role (g)
# ==================================


@pytest.mark.asyncio
async def test_admin_casbin_role_crud_flow(
    client: AsyncClient,
    admin_token_headers: dict,
    regular_user_in_db: dict,  # Cần user ID
):
    """
    Flow CRUD hoàn chỉnh cho gán/thu hồi vai trò.

    HAI đường RIÊNG, hai hằng RIÊNG:
        POST   ``/api/admin/roles/assign``  (roles.py:358)
        DELETE ``/api/admin/roles/revoke``  (roles.py:394)

    Kiểm tra: POST (201), POST (409), DELETE (200), DELETE (404).
    """
    log.info("--- Running: test_admin_casbin_role_crud_flow ---")
    user_id = regular_user_in_db["id"]

    role_payload = {
        "user_id": user_id,
        "role": "role:manager",  # Gán vai trò manager cho user thường
    }
    role_schema = RoleAssignment(**role_payload)

    # Hai đường phải THẬT SỰ khác nhau. Nếu ai đó gộp lại thành một hằng, ca này
    # đỏ NGAY tại đây thay vì đỏ mù mờ ở một assertion trạng thái phía dưới.
    assert AdminURLs.ASSIGN_ROLE != AdminURLs.REVOKE_ROLE, (
        "Gán và thu hồi là hai endpoint khác nhau; đừng dùng chung một hằng rồi "
        "phân biệt bằng HTTP method."
    )

    # --- 1. POST (Assign Role) ---
    log.info("Testing POST /api/admin/roles/assign (Create)...")
    response_post = await client.post(
        AdminURLs.ASSIGN_ROLE, json=role_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_post.status_code == 201, f"POST Role Resp: {response_post.text}"
    assert response_post.json()["detail"] == "Role assigned."
    # Assert DB — hàng `g` chỉ có hai trường (`auth_model.conf:8`: g = _, _),
    # nên KHÔNG lọc theo `eft` ở đây.
    db_rule_post = await get_casbin_rule_from_db(
        "g", f"user:{user_id}", role_schema.role
    )
    assert (
        db_rule_post is not None
    ), "Role assignment (g rule) not found in DB after creation"
    log.info("POST /roles/assign (Create) successful.")

    # --- 2. POST (Duplicate) ---
    log.info("Testing POST /api/admin/roles/assign (Duplicate)...")
    response_dupe = await client.post(
        AdminURLs.ASSIGN_ROLE, json=role_payload, headers=admin_token_headers
    )
    # Assert Response
    assert (
        response_dupe.status_code == 409
    ), f"POST Dupe Role Resp: {response_dupe.text}"
    assert "User already has this role" in response_dupe.json()["detail"]
    log.info("POST /roles/assign (Duplicate) correctly blocked (409).")

    # --- 3. DELETE (Success) — đường THU HỒI RIÊNG ---
    log.info("Testing DELETE /api/admin/roles/revoke (Success)...")
    response_del = await client.request(  # Dùng .request() vì DELETE có body
        "DELETE", AdminURLs.REVOKE_ROLE, json=role_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_del.status_code == 200, f"DELETE Role Resp: {response_del.text}"
    assert response_del.json()["detail"] == "Role removed from user."
    # Assert DB
    db_rule_del = await get_casbin_rule_from_db(
        "g", f"user:{user_id}", role_schema.role
    )
    assert (
        db_rule_del is None
    ), "Role assignment (g rule) still found in DB after deletion"
    log.info("DELETE /roles/revoke (Success) successful.")

    # --- 4. DELETE (Not Found) ---
    log.info("Testing DELETE /api/admin/roles/revoke (Not Found)...")
    response_del_404 = await client.request(
        "DELETE",
        AdminURLs.REVOKE_ROLE,
        json=role_payload,  # Xóa lại role cũ
        headers=admin_token_headers,
    )
    # Assert Response — 404 hợp đồng của endpoint (`ResourceNotFoundError` ở
    # roles.py:411), phân biệt với 404 route-không-tồn-tại bằng chuỗi `detail`.
    assert (
        response_del_404.status_code == 404
    ), f"DELETE Role 404 Resp: {response_del_404.text}"
    assert "Role assignment not found" in response_del_404.json()["detail"]
    log.info("DELETE /roles/revoke (Not Found) correctly failed (404).")
