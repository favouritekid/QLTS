"""Smoke test for the ``manager_other_unit_user_in_db`` conftest fixture.

Closes admission audit follow-up #5 (memory
``project_admission_audit_followups``). Lifts the cross-unit manager
pattern (previously inlined in test_commission_api / test_collaborator_api
/ test_admission_idor) into a reusable conftest fixture so admission
tests can DI it instead of re-seeding the unit + manager rows per file.

Verifies fixture wiring (distinct unit + login round-trip). The
concrete cross-unit IDOR contracts (404 on profile GET, etc.) are
covered by ``tests/integration/test_admission_idor.py`` and the
upcoming admission test files that DI this fixture — duplicating
that here would only buy fixture-cost without new coverage.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.database import AsyncSessionLocal
from app import models
from tests.fixtures.constants import AuthURLs, TestUsers


ADMISSIONS = "/api/admissions"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    """Mirror of the login helper used by the surrounding admission test
    files — duplicated locally to keep this fixture-smoke file
    self-contained."""
    r = await client.post(
        AuthURLs.LOGIN, data={"username": username, "password": password}
    )
    assert r.status_code == 200, f"Login {username}: {r.text}"
    return {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


@pytest.mark.asyncio
async def test_fixture_manager_other_unit_uses_distinct_unit(
    manager_other_unit_user_in_db: dict,
    manager_user_in_db: dict,
):
    """Both manager fixtures coexist in the same test DB and live in
    different units. The default ``manager_user_in_db`` lives in the
    seed_lead_dependencies unit; ``manager_other_unit_user_in_db``
    lives in ``TestOrgData.UNIT_2``.
    """
    assert manager_other_unit_user_in_db["id"] != manager_user_in_db["id"]
    # Verify the persisted unit_id matches what the fixture promises.
    async with AsyncSessionLocal() as s:
        other = await s.get(models.User, manager_other_unit_user_in_db["id"])
        default = await s.get(models.User, manager_user_in_db["id"])
        assert other.unit_id != default.unit_id, (
            "Cross-unit fixture must seed a manager outside the default unit"
        )


@pytest.mark.asyncio
async def test_fixture_manager_other_unit_can_authenticate(
    client: AsyncClient,
    manager_other_unit_user_in_db: dict,
):
    """Login round-trip surfaces fixture wiring bugs early (Casbin role
    assignment, password hash, etc.). A list endpoint check confirms
    the token also resolves Casbin enforcement for the manager role."""
    headers = await _login(
        client,
        TestUsers.MANAGER_OTHER_UNIT["username"],
        TestUsers.MANAGER_OTHER_UNIT["password"],
    )
    assert "Authorization" in headers
    r = await client.get(ADMISSIONS, headers=headers)
    assert r.status_code == 200, r.text
