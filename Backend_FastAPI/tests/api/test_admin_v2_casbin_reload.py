# tests/api/test_admin_v2_casbin_reload.py
"""T0-5 — coverage for ``POST /api/v2/admin/casbin/reload``.

Required surface (per RUNBOOK §3.5 T0-5):

* admin can trigger a reload (200, response carries success/reloaded_at/
  policy_count/actor_id),
* every non-admin role is denied,
* unauthenticated callers are denied,
* a reload failure is surfaced as 500 with a structured body and does NOT
  crash the worker / API.

Out of scope: ``auth_model.conf`` content, deny-block presence, policy
templates — those belong to the B1 RBAC refactor wave.
"""
from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient


log = logging.getLogger(__name__)

RELOAD_URL = "/api/v2/admin/casbin/reload"


# ---------------------------------------------------------------------------
# Happy path: admin succeeds, response shape locked.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_reload_casbin_policy(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
):
    response = await client.post(RELOAD_URL, headers=admin_token_headers)

    assert response.status_code == 200, f"Admin reload should succeed; got: {response.text}"
    body = response.json()
    assert body["success"] is True, f"Expected success=True; got: {body}"
    # Required keys (load-bearing for staging dashboards / log greps).
    assert "reloaded_at" in body
    assert "policy_count" in body  # may be int or None — informational only.
    assert body["actor_id"] is not None and body["actor_id"] > 0
    # `reloaded_at` is an ISO-8601 timestamp; cheap shape check (not full parse).
    assert "T" in body["reloaded_at"], f"reloaded_at not ISO-shaped: {body['reloaded_at']!r}"


@pytest.mark.asyncio
async def test_admin_reload_returns_non_negative_policy_count_when_present(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
):
    response = await client.post(RELOAD_URL, headers=admin_token_headers)
    assert response.status_code == 200
    body = response.json()
    if body["policy_count"] is not None:
        assert isinstance(body["policy_count"], int)
        assert body["policy_count"] >= 0


# ---------------------------------------------------------------------------
# Authorization: every non-admin role is denied; no auth is denied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_caller_denied(
    client: AsyncClient, setup_test_database
):
    response = await client.post(RELOAD_URL)
    # Auth chain raises 401 for missing/bad credentials.
    assert response.status_code == 401, (
        f"Unauthenticated POST should be 401; got {response.status_code} {response.text}"
    )


@pytest.mark.asyncio
async def test_manager_caller_denied(
    client: AsyncClient, manager_token_headers: dict, setup_test_database
):
    response = await client.post(RELOAD_URL, headers=manager_token_headers)
    assert response.status_code == 403, (
        f"Manager should be denied (admin-only); got {response.status_code} {response.text}"
    )


@pytest.mark.asyncio
async def test_officer_caller_denied(
    client: AsyncClient, officer_token_headers: dict, setup_test_database
):
    response = await client.post(RELOAD_URL, headers=officer_token_headers)
    assert response.status_code == 403, (
        f"Officer should be denied (admin-only); got {response.status_code} {response.text}"
    )


@pytest.mark.asyncio
async def test_regular_user_caller_denied(
    client: AsyncClient, regular_user_token_headers: dict, setup_test_database
):
    response = await client.post(RELOAD_URL, headers=regular_user_token_headers)
    assert response.status_code == 403, (
        f"Regular user should be denied (admin-only); got {response.status_code} {response.text}"
    )


# ---------------------------------------------------------------------------
# Failure path: reload throws — endpoint returns 500 with structured body
# and does NOT propagate as an unhandled crash.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_failure_surfaces_500_without_crashing(
    client: AsyncClient,
    admin_token_headers: dict,
    setup_test_database,
    monkeypatch,
):
    """Stub ``enforcer.load_policy`` to raise; assert structured 500."""
    from app.main import fastapi_app

    enforcer = fastapi_app.state.enforcer
    original_load = enforcer.load_policy

    async def _boom():
        raise RuntimeError("simulated DB unreachable")

    monkeypatch.setattr(enforcer, "load_policy", _boom)
    try:
        response = await client.post(RELOAD_URL, headers=admin_token_headers)
    finally:
        # Defensive restore — pytest's monkeypatch teardown does this too,
        # but we want to make sure subsequent tests on the same session do
        # not see the broken stub if teardown runs late.
        monkeypatch.setattr(enforcer, "load_policy", original_load)

    assert response.status_code == 500, (
        f"Reload failure should be a structured 500; got "
        f"{response.status_code} {response.text}"
    )
    body = response.json()
    assert body["success"] is False
    assert "simulated DB unreachable" in body["error"]
    assert body["actor_id"] is not None and body["actor_id"] > 0
    assert "reloaded_at" in body


@pytest.mark.asyncio
async def test_subsequent_reload_after_failure_recovers(
    client: AsyncClient,
    admin_token_headers: dict,
    setup_test_database,
    monkeypatch,
):
    """One bad reload must not poison the enforcer — the very next admin
    call (without the stub) must succeed. This is what guards against the
    "worker stuck on stale enforcer" failure mode the runbook calls out.
    """
    from app.main import fastapi_app

    enforcer = fastapi_app.state.enforcer
    original_load = enforcer.load_policy

    async def _boom():
        raise RuntimeError("simulated DB unreachable")

    monkeypatch.setattr(enforcer, "load_policy", _boom)
    bad = await client.post(RELOAD_URL, headers=admin_token_headers)
    assert bad.status_code == 500
    monkeypatch.setattr(enforcer, "load_policy", original_load)

    good = await client.post(RELOAD_URL, headers=admin_token_headers)
    assert good.status_code == 200, (
        f"Recovery reload should succeed; got {good.status_code} {good.text}"
    )
    assert good.json()["success"] is True


# ---------------------------------------------------------------------------
# Endpoint registration: the route exists at the documented path + method.
# ---------------------------------------------------------------------------


def test_reload_endpoint_registered_at_documented_path():
    """Lock the URL contract — the runbook references this exact string."""
    from app.main import fastapi_app

    matched = [
        route
        for route in fastapi_app.routes
        if getattr(route, "path", "") == RELOAD_URL
        and "POST" in (getattr(route, "methods", None) or set())
    ]
    assert matched, (
        f"POST {RELOAD_URL} not registered on the FastAPI app. "
        "Check `app/main.py` include_router for `admin_v2_casbin`."
    )
