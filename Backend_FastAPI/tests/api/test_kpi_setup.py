# tests/api/test_kpi_setup.py
"""
KPI Setup Coverage endpoint — auth, IDOR, and response shape tests.
"""
import pytest
from httpx import AsyncClient

KPI_SETUP_COVERAGE = "/api/admin/kpi-setup/coverage"


# =====================================================================
# AUTH TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_coverage_unauthenticated(client: AsyncClient):
    """Unauthenticated request → 401."""
    response = await client.get(KPI_SETUP_COVERAGE, params={"fiscal_year": 2026})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_coverage_regular_user_forbidden(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    """Regular user (role=user) → 403 from require_admin_or_manager."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=regular_user_token_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_coverage_officer_forbidden(
    client: AsyncClient,
    officer_token_headers: dict,
):
    """Officer role → 403 from require_admin_or_manager."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=officer_token_headers,
    )
    assert response.status_code == 403


# =====================================================================
# ADMIN — FULL ACCESS
# =====================================================================

@pytest.mark.asyncio
async def test_coverage_admin_success(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """Admin gets full coverage report with correct shape."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=admin_token_headers,
    )
    assert response.status_code == 200

    data = response.json()
    assert data["fiscal_year"] == 2026

    # Top-level shape
    assert "holiday_status" in data
    assert "units" in data
    assert "warnings" in data
    assert "summary" in data

    # Holiday status shape
    hs = data["holiday_status"]
    assert "total_holidays" in hs
    assert "is_complete" in hs
    assert "reason_code" in hs

    # Summary shape
    s = data["summary"]
    for key in [
        "total_units", "units_with_plan", "total_officers",
        "officers_with_target", "total_annual_target",
        "total_achieved_ytd", "progress_pct",
    ]:
        assert key in s, f"Missing summary key: {key}"


@pytest.mark.asyncio
async def test_coverage_admin_sees_all_units(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """Admin (no unit_id) → response includes the seeded unit."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=admin_token_headers,
    )
    assert response.status_code == 200
    data = response.json()

    unit_ids = [u["unit_id"] for u in data["units"]]
    seeded_unit_id = seed_lead_dependencies["unit_id"]
    assert seeded_unit_id in unit_ids, (
        f"Admin should see seeded unit {seeded_unit_id}, got units: {unit_ids}"
    )


# =====================================================================
# MANAGER — SCOPED ACCESS
# =====================================================================

@pytest.mark.asyncio
async def test_coverage_manager_sees_own_unit_only(
    client: AsyncClient,
    manager_token_headers: dict,
    manager_user_in_db: dict,
    seed_lead_dependencies: dict,
):
    """Manager with unit_id → only sees own unit's data."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=manager_token_headers,
    )
    assert response.status_code == 200
    data = response.json()

    manager_unit_id = seed_lead_dependencies["unit_id"]
    unit_ids = [u["unit_id"] for u in data["units"]]

    # Manager should only see their own unit
    assert all(
        uid == manager_unit_id for uid in unit_ids
    ), f"Manager should only see unit {manager_unit_id}, got: {unit_ids}"


@pytest.mark.asyncio
async def test_coverage_manager_no_unit_gets_403(
    client: AsyncClient,
    setup_test_database,
):
    """Manager without unit_id → 403 Forbidden (not silent data leak)."""
    from tests.conftest import _create_user_and_role, _get_token_headers
    from tests.fixtures.constants import TestUsers

    # Create a manager with NO unit_id
    manager_no_unit_data = {
        "username": "manager_no_unit",
        "email": "manager_nounit@example.com",
        "password": "ManagerNoUnit!123",
        "role": "manager",
        "status": "active",
    }
    await _create_user_and_role(manager_no_unit_data, "role:manager", unit_id=None)

    headers = await _get_token_headers(client, manager_no_unit_data)

    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=headers,
    )
    assert response.status_code == 403, (
        f"Manager without unit_id should get 403, got {response.status_code}: {response.text}"
    )


# =====================================================================
# VALIDATION
# =====================================================================

@pytest.mark.asyncio
async def test_coverage_invalid_fiscal_year(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """fiscal_year out of range → 422."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 1900},
        headers=admin_token_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_coverage_missing_fiscal_year(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """Missing fiscal_year → 422."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        headers=admin_token_headers,
    )
    assert response.status_code == 422


# =====================================================================
# RESPONSE STRUCTURE — UNIT & OFFICER COVERAGE
# =====================================================================

@pytest.mark.asyncio
async def test_coverage_unit_shape(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """Each unit in response has correct shape."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=admin_token_headers,
    )
    assert response.status_code == 200
    data = response.json()

    if data["units"]:
        unit = data["units"][0]
        for key in [
            "unit_id", "unit_name", "plan_id", "plan_status",
            "annual_target", "officers", "total_officer_target", "target_gap",
        ]:
            assert key in unit, f"Missing unit key: {key}"


@pytest.mark.asyncio
async def test_coverage_warning_shape(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """Each warning has stable reason_code + action_hint."""
    response = await client.get(
        KPI_SETUP_COVERAGE,
        params={"fiscal_year": 2026},
        headers=admin_token_headers,
    )
    assert response.status_code == 200
    data = response.json()

    valid_reason_codes = {
        "missing_holiday", "missing_unit_plan", "officer_no_target",
        "officer_target_mismatch", "stale_sync",
    }
    valid_action_hints = {
        "seed_holidays", "create_plan", "assign_target",
        "review_targets", "sync_ytd",
    }

    for w in data["warnings"]:
        assert "reason_code" in w
        assert "action_hint" in w
        assert "section" in w
        assert "detail" in w
        assert w["reason_code"] in valid_reason_codes, (
            f"Unknown reason_code: {w['reason_code']}"
        )
        assert w["action_hint"] in valid_action_hints, (
            f"Unknown action_hint: {w['action_hint']}"
        )
        assert 0 <= w["section"] <= 3
