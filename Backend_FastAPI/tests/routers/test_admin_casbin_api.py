# tests/routers/test_admin_casbin_api.py
# -*- coding: utf-8 -*-
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
    from ..fixtures.constants import NON_EXISTENT_ID, AdminURLs, TestUsers
except ImportError:
    pytest.fail("Could not import constants from tests.fixtures.constants.")

log = logging.getLogger(__name__)


# === Helper kiểm tra DB Casbin ===
async def get_casbin_rule_from_db(ptype: str, v0: str, v1: str, v2: str = None):
    """Helper kiểm tra sự tồn tại của rule trong DB."""
    async with AsyncSessionLocal() as session:
        query = select(CasbinRule).where(
            CasbinRule.ptype == ptype, CasbinRule.v0 == v0, CasbinRule.v1 == v1
        )
        if v2:
            query = query.where(CasbinRule.v2 == v2)

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
    Test 7.2: Flow CRUD hoàn chỉnh cho /admin/policies.
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
    log.info("Testing POST /admin/policies (Create)...")
    response_post = await client.post(
        AdminURLs.POLICIES, json=policy_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_post.status_code == 201, f"POST Policy Resp: {response_post.text}"
    assert response_post.json()["message"] == "Policy added successfully."
    # Assert DB
    db_rule_post = await get_casbin_rule_from_db(
        "p", policy_schema.subject, policy_schema.object, policy_schema.action
    )
    assert db_rule_post is not None, "Policy not found in DB after creation"
    log.info("POST /policies (Create) successful.")

    # --- 2. POST (Duplicate) ---
    log.info("Testing POST /admin/policies (Duplicate)...")
    response_dupe = await client.post(
        AdminURLs.POLICIES, json=policy_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_dupe.status_code == 409, f"POST Dupe Resp: {response_dupe.text}"
    assert "Policy already exists" in response_dupe.json()["detail"]
    log.info("POST /policies (Duplicate) correctly blocked (409).")

    # --- 3. GET (List) ---
    log.info("Testing GET /admin/policies (List)...")
    response_get = await client.get(AdminURLs.POLICIES, headers=admin_token_headers)
    assert response_get.status_code == 200
    policy_list = response_get.json()
    assert isinstance(policy_list, list)
    # Tìm policy đã tạo (và các policy mặc định)
    found_policy = False
    for p in policy_list:
        if p == [policy_schema.subject, policy_schema.object, policy_schema.action]:
            found_policy = True
            break
    assert found_policy, "Created policy not found in GET list"
    log.info("GET /policies successful, created policy found.")

    # --- 4. DELETE (Success) ---
    log.info("Testing DELETE /admin/policies (Success)...")
    response_del = await client.request(  # Dùng .request() vì DELETE có body
        "DELETE", AdminURLs.POLICIES, json=policy_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_del.status_code == 200, f"DELETE Resp: {response_del.text}"
    assert response_del.json()["message"] == "Policy removed successfully."
    # Assert DB
    db_rule_del = await get_casbin_rule_from_db(
        "p", policy_schema.subject, policy_schema.object, policy_schema.action
    )
    assert db_rule_del is None, "Policy still found in DB after deletion"
    log.info("DELETE /policies (Success) successful.")

    # --- 5. DELETE (Not Found) ---
    log.info("Testing DELETE /admin/policies (Not Found)...")
    response_del_404 = await client.request(
        "DELETE",
        AdminURLs.POLICIES,
        json=policy_payload,  # Xóa lại policy cũ
        headers=admin_token_headers,
    )
    # Assert Response
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
    Test 7.2: Flow CRUD hoàn chỉnh cho /admin/assign-role.
    Kiểm tra: POST (201), POST (409), DELETE (200), DELETE (404).
    """
    log.info("--- Running: test_admin_casbin_role_crud_flow ---")
    user_id = regular_user_in_db["id"]

    role_payload = {
        "user_id": user_id,
        "role": "role:manager",  # Gán vai trò manager cho user thường
    }
    role_schema = RoleAssignment(**role_payload)

    # --- 1. POST (Assign Role) ---
    log.info("Testing POST /admin/assign-role (Create)...")
    response_post = await client.post(
        AdminURLs.ASSIGN_ROLE, json=role_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_post.status_code == 201, f"POST Role Resp: {response_post.text}"
    assert response_post.json()["message"] == "Role assigned."
    # Assert DB
    db_rule_post = await get_casbin_rule_from_db(
        "g", f"user:{user_id}", role_schema.role
    )
    assert (
        db_rule_post is not None
    ), "Role assignment (g rule) not found in DB after creation"
    log.info("POST /assign-role (Create) successful.")

    # --- 2. POST (Duplicate) ---
    log.info("Testing POST /admin/assign-role (Duplicate)...")
    response_dupe = await client.post(
        AdminURLs.ASSIGN_ROLE, json=role_payload, headers=admin_token_headers
    )
    # Assert Response
    assert (
        response_dupe.status_code == 409
    ), f"POST Dupe Role Resp: {response_dupe.text}"
    assert "User already has this role" in response_dupe.json()["detail"]
    log.info("POST /assign-role (Duplicate) correctly blocked (409).")

    # --- 3. DELETE (Success) ---
    log.info("Testing DELETE /admin/assign-role (Success)...")
    response_del = await client.request(  # Dùng .request() vì DELETE có body
        "DELETE", AdminURLs.ASSIGN_ROLE, json=role_payload, headers=admin_token_headers
    )
    # Assert Response
    assert response_del.status_code == 200, f"DELETE Role Resp: {response_del.text}"
    assert response_del.json()["message"] == "Role removed from user."
    # Assert DB
    db_rule_del = await get_casbin_rule_from_db(
        "g", f"user:{user_id}", role_schema.role
    )
    assert (
        db_rule_del is None
    ), "Role assignment (g rule) still found in DB after deletion"
    log.info("DELETE /assign-role (Success) successful.")

    # --- 4. DELETE (Not Found) ---
    log.info("Testing DELETE /admin/assign-role (Not Found)...")
    response_del_404 = await client.request(
        "DELETE",
        AdminURLs.ASSIGN_ROLE,
        json=role_payload,  # Xóa lại role cũ
        headers=admin_token_headers,
    )
    # Assert Response
    assert (
        response_del_404.status_code == 404
    ), f"DELETE Role 404 Resp: {response_del_404.text}"
    assert "Role assignment not found" in response_del_404.json()["detail"]
    log.info("DELETE /assign-role (Not Found) correctly failed (404).")
