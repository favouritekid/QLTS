"""W8-F.1 anchor — PUT /api/admin/users/{id} reliably 500 MissingGreenlet.

QA Wave 8 (2026-05-16) — Admin không thể edit user qua chuẩn endpoint
PUT /api/admin/users/{id} vì SQLAlchemy MissingGreenlet bombing trên
ORM attribute access in middleware-level async context.

Root cause: handler did `await db.commit()` → `expire_on_commit=True`
expires all attrs on `updated_user` and `current_admin`. Subsequent
lazy access (notification dispatch, audit log, response serialization)
triggers SELECT-on-checkout that requires a greenlet not available in
the response middleware path → MissingGreenlet → 500.

Fix: capture ALL identifier attrs into plain Python vars BEFORE commit
chain. Use captured vars throughout downstream notification + audit
logic. `db.refresh(updated_user)` immediately before `return` so
FastAPI response serialization (UserAdminResponse `from_attributes=True`)
can read fresh attrs without lazy-fetch.

Anchor verifies: PUT minimal field-only update → 200 OK + response body
contains updated value. Pre-fix: 500 INTERNAL_ERROR. Multiple commits
+ multiple notifications all execute without raising MissingGreenlet.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_admin_put_user_full_name_returns_200_not_500(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
):
    """PUT /api/admin/users/{id} với full_name update → 200 (was 500 W8-F.1).

    Triggers commit + audit log + USER_PROFILE_UPDATED notification dispatch
    chain. Pre-fix any of those steps lazy-loaded `updated_user.id` or
    `current_admin.id` from expired session → MissingGreenlet → 500.
    """
    target_user_id = officer_user_in_db["id"]
    # Form-data upload (not JSON) because endpoint uses Form() params
    response = await client.put(
        f"/api/admin/users/{target_user_id}",
        headers=admin_token_headers,
        data={"full_name": "W8-F.1 Anchor Test"},
    )
    assert response.status_code == 200, (
        f"PUT user full_name expected 200 (W8-F.1 fix); "
        f"got {response.status_code}: {response.text[:300]}"
    )
    body = response.json()
    assert body["id"] == target_user_id
    assert body["full_name"] == "W8-F.1 Anchor Test"


async def test_admin_put_user_role_change_triggers_dispatch_no_500(
    client: AsyncClient,
    admin_token_headers: dict,
    officer_user_in_db: dict,
):
    """PUT với role change → 200, USER_ROLE_CHANGED dispatch fires
    without MissingGreenlet. Tests the deeper code path that hits multiple
    `safe_dispatch` calls + audit log all in same request.
    """
    target_user_id = officer_user_in_db["id"]
    response = await client.put(
        f"/api/admin/users/{target_user_id}",
        headers=admin_token_headers,
        data={
            "full_name": "W8-F.1 Role Change Test",
            "role": "manager",
        },
    )
    assert response.status_code == 200, (
        f"PUT user role-change expected 200; got {response.status_code}: "
        f"{response.text[:300]}"
    )
    body = response.json()
    assert body["id"] == target_user_id
    assert body["role"] == "manager"
