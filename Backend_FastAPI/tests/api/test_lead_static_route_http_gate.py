"""PR1 Commit 3 anchor: lead static routes carry an HTTP-layer role hard gate
in front of CasbinAuth (A01).

The Casbin keyMatch4 matcher collides the static paths (/export,
/distribution-preview, /bulk-assign, /bulk-delete) with /api/leads/{id},
which let officers reach the two GETs by direct API call (see the
Casbin-layer matrix in
tests/integration/test_casbin_lead_static_route_collision.py — kept as the
policy-table contract). These tests pin that the actual HTTP endpoints now:
  * 403 officers on ALL four static routes (require_admin_or_manager /
    require_admin gate runs before/independent of Casbin), and
  * 403 managers on bulk-delete (ADMIN-only), while allowing them the other
    three, and admins on bulk-delete.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

LEADS = "/api/leads"


async def _bearer(client: AsyncClient, user: dict) -> dict:
    r = await client.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest.mark.asyncio
async def test_officer_blocked_from_all_lead_static_routes(
    client: AsyncClient, officer_user_in_db: dict
):
    oh = await _bearer(client, officer_user_in_db)
    # The two GETs used to leak to officers via the keyMatch4 collision; the
    # hard gate now 403s all four static routes.
    assert (await client.get(f"{LEADS}/export", headers=oh)).status_code == 403
    assert (
        await client.get(
            f"{LEADS}/distribution-preview?offering_id=1", headers=oh
        )
    ).status_code == 403
    assert (
        await client.post(
            f"{LEADS}/bulk-assign?officer_id=1", headers=oh, json={"lead_ids": [1]}
        )
    ).status_code == 403
    assert (
        await client.post(f"{LEADS}/bulk-delete", headers=oh, json={"lead_ids": [1]})
    ).status_code == 403


@pytest.mark.asyncio
async def test_manager_allowed_except_bulk_delete(
    client: AsyncClient, manager_user_in_db: dict
):
    mh = await _bearer(client, manager_user_in_db)
    # Manager is admin-or-manager → passes the gate on export (not 403).
    export = await client.get(f"{LEADS}/export", headers=mh)
    assert export.status_code != 403, f"manager must pass the export gate: {export.text}"
    # bulk-delete is ADMIN-only → manager 403 even though Casbin has no
    # manager bulk-delete allow either.
    rev = await client.post(
        f"{LEADS}/bulk-delete", headers=mh, json={"lead_ids": [999999]}
    )
    assert rev.status_code == 403, f"manager must be blocked from bulk-delete: {rev.text}"


@pytest.mark.asyncio
async def test_admin_passes_bulk_delete_gate(
    client: AsyncClient, admin_token_headers: dict
):
    # Admin clears the require_admin gate (not 403); the body runs and deletes
    # nothing for a non-existent id.
    r = await client.post(
        f"{LEADS}/bulk-delete", headers=admin_token_headers, json={"lead_ids": [999999]}
    )
    assert r.status_code != 403, f"admin must pass the bulk-delete gate: {r.text}"
