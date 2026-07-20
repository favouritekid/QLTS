# tests/api/test_officer_dashboard_scope.py
# -*- coding: utf-8 -*-
"""
Integration tests for officer dashboard scope/IDOR and widget drill-down behavior.

Tests real HTTP requests through the full stack (router → deps.py → service → DB)
to verify:
1. /api/officer/dashboard IDOR (scope, officer_id, role-based access)
2. /api/officer/leaderboard IDOR via resolve_drill_down_officer_id
3. /api/officer/upcoming-activities IDOR + drill-down behavior
4. Leaderboard is_focus_officer / is_current_user semantics
5. /api/officer/my-kpi-plan response shape (consultations_actual_avg field)
"""
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.database import AsyncSessionLocal
from app import models
from app.security import get_password_hash

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
DASHBOARD_URL = "/api/officer/dashboard"
LEADERBOARD_URL = "/api/officer/leaderboard"
UPCOMING_URL = "/api/officer/upcoming-activities"
KPI_PLAN_URL = "/api/officer/my-kpi-plan"

# ---------------------------------------------------------------------------
# Extra user data (beyond what conftest provides)
# ---------------------------------------------------------------------------
OFFICER_2_DATA = {
    "username": "officer_scope2",
    "email": "officer_scope2@example.com",
    "password": "OfficerScope2!999",
    "role": "officer",
    "status": "active",
}

OFFICER_CHILD_DATA = {
    "username": "officer_child_unit",
    "email": "officer_child@example.com",
    "password": "OfficerChild!777",
    "role": "officer",
    "status": "active",
}

OFFICER_UNRELATED_DATA = {
    "username": "officer_unrelated",
    "email": "officer_unrelated@example.com",
    "password": "OfficerUnrelated!555",
    "role": "officer",
    "status": "active",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
from tests.conftest import _create_user_and_role, _get_token_headers


async def _create_child_unit(parent_id: int, unit_id: int = 100, name: str = "Child Unit") -> int:
    """Create a child OrganizationUnit under parent_id."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit = models.OrganizationUnit(
                id=unit_id,
                name=name,
                type="Department",
                parent_id=parent_id,
            )
            session.add(unit)
    return unit_id


async def _create_unrelated_unit(unit_id: int = 200, name: str = "Unrelated Unit") -> int:
    """Create a top-level unit with no parent (unrelated to UNIT_1)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unit = models.OrganizationUnit(
                id=unit_id,
                name=name,
                type="Faculty",
                parent_id=None,
            )
            session.add(unit)
    return unit_id


async def _create_lead_with_activity(
    officer_id: int,
    unit_id: int,
    lead_name: str,
    activity_dt: datetime,
    status_id: str = "status_a1",
    stage_id: str = "STAGE_A",
) -> int:
    """Create a Lead assigned to officer with next_activity_at set."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=lead_name,
                phone=f"090{officer_id:04d}{activity_dt.day:02d}",
                source="website",
                status="assigned",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                consultation_status_id=status_id,
                pipeline_stage_id=stage_id,
                next_activity_at=activity_dt,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id


async def _create_consultation(
    lead_id: int,
    officer_id: int,
    consultation_date: datetime | None = None,
) -> int:
    """Create a Consultation record for leaderboard ranking."""
    if consultation_date is None:
        consultation_date = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            consultation = models.Consultation(
                lead_id=lead_id,
                officer_id=officer_id,
                method="phone",
                notes="Test consultation",
                consultation_date=consultation_date,
            )
            session.add(consultation)
            await session.flush()
            cid = consultation.id
    return cid


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest_asyncio.fixture
async def child_unit(seed_lead_dependencies):
    """Create a child unit under UNIT_1 (id=1)."""
    return await _create_child_unit(parent_id=1, unit_id=100)


@pytest_asyncio.fixture
async def unrelated_unit(seed_lead_dependencies):
    """Create a top-level unit unrelated to UNIT_1."""
    return await _create_unrelated_unit(unit_id=200)


@pytest_asyncio.fixture
async def officer2_in_unit1(seed_lead_dependencies):
    """Second officer in UNIT_1 (same unit as default officer)."""
    return await _create_user_and_role(OFFICER_2_DATA, "role:officer", unit_id=1)


@pytest_asyncio.fixture
async def officer_in_child_unit(child_unit):
    """Officer in the child unit (descendant of UNIT_1)."""
    return await _create_user_and_role(OFFICER_CHILD_DATA, "role:officer", unit_id=child_unit)


@pytest_asyncio.fixture
async def officer_in_unrelated_unit(unrelated_unit):
    """Officer in a completely unrelated unit."""
    return await _create_user_and_role(OFFICER_UNRELATED_DATA, "role:officer", unit_id=unrelated_unit)


# ===========================================================================
# === /api/officer/dashboard IDOR Tests ===
# ===========================================================================

class TestDashboardIDOR:
    """IDOR tests for GET /api/officer/dashboard."""

    @pytest.mark.asyncio
    async def test_officer_self_ok(self, client: AsyncClient, officer_user_in_db, officer_token_headers):
        """Officer viewing own dashboard (no officer_id param) → 200."""
        resp = await client.get(DASHBOARD_URL, headers=officer_token_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_officer_self_explicit_ok(self, client: AsyncClient, officer_user_in_db, officer_token_headers):
        """Officer explicitly passing own ID → 200."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": officer_user_in_db["id"]},
            headers=officer_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_officer_other_404(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers, officer2_in_unit1
    ):
        """Officer viewing another officer → 404 (IDOR blocked)."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": officer2_in_unit1["id"]},
            headers=officer_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_same_unit_officer_ok(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_user_in_db
    ):
        """Manager viewing officer in own unit → 200."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": officer_user_in_db["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_manager_descendant_unit_officer_ok(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_in_child_unit
    ):
        """Manager viewing officer in child unit (descendant) → 200."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": officer_in_child_unit["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_manager_out_of_scope_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_in_unrelated_unit
    ):
        """Manager viewing officer in unrelated unit → 404."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": officer_in_unrelated_unit["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_non_officer_target_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, regular_user_in_db
    ):
        """Manager viewing non-officer user → 404 (role check)."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": regular_user_in_db["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_officer_ok(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers, officer_user_in_db
    ):
        """Admin viewing any officer → 200."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": officer_user_in_db["id"], "scope": "personal"},
            headers=admin_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_non_officer_target_404(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers, regular_user_in_db
    ):
        """Admin viewing non-officer user → 404."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": regular_user_in_db["id"], "scope": "personal"},
            headers=admin_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_nonexistent_officer_404(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers
    ):
        """Admin viewing nonexistent user → 404."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": 99999, "scope": "personal"},
            headers=admin_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_self_id_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers
    ):
        """Manager passing own ID as officer_id → 404 (manager is not an officer)."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"officer_id": manager_user_in_db["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    # --- V12 scope validation tests ---

    @pytest.mark.asyncio
    async def test_manager_personal_scope_rejected(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers
    ):
        """V12: Manager requesting scope=personal → 400."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"scope": "personal"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_unit_scope_rejected(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers
    ):
        """V12: Admin requesting scope=unit → 400."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"scope": "unit"},
            headers=admin_token_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_personal_no_officer_rejected(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers
    ):
        """V12: Admin requesting scope=personal without officer_id → 400."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"scope": "personal"},
            headers=admin_token_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_scope_team_normalized_to_unit(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers
    ):
        """V12: Legacy scope=team is normalized to unit → 200."""
        resp = await client.get(
            DASHBOARD_URL,
            params={"scope": "team"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_manager_default_scope_rejected(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers
    ):
        """V12: Manager with no scope param (default 'personal') → 400."""
        resp = await client.get(
            DASHBOARD_URL,
            headers=manager_token_headers,
        )
        assert resp.status_code == 400


# ===========================================================================
# === /api/officer/leaderboard IDOR Tests ===
# ===========================================================================

class TestLeaderboardIDOR:
    """IDOR tests for GET /api/officer/leaderboard (uses resolve_drill_down_officer_id)."""

    @pytest.mark.asyncio
    async def test_officer_self_ok(self, client: AsyncClient, officer_user_in_db, officer_token_headers):
        """Officer with no officer_id → 200 (default self)."""
        resp = await client.get(LEADERBOARD_URL, headers=officer_token_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_officer_explicit_self_ok(self, client: AsyncClient, officer_user_in_db, officer_token_headers):
        """Officer explicitly passing own ID → 200."""
        resp = await client.get(
            LEADERBOARD_URL,
            params={"officer_id": officer_user_in_db["id"]},
            headers=officer_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_officer_other_404(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers, officer2_in_unit1
    ):
        """Officer drilling into another officer → 404."""
        resp = await client.get(
            LEADERBOARD_URL,
            params={"officer_id": officer2_in_unit1["id"]},
            headers=officer_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_descendant_ok(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_in_child_unit
    ):
        """Manager drilling into officer in child unit → 200."""
        resp = await client.get(
            LEADERBOARD_URL,
            params={"officer_id": officer_in_child_unit["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_manager_out_of_scope_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_in_unrelated_unit
    ):
        """Manager drilling into officer outside scope → 404."""
        resp = await client.get(
            LEADERBOARD_URL,
            params={"officer_id": officer_in_unrelated_unit["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_non_officer_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, regular_user_in_db
    ):
        """Manager drilling into non-officer → 404."""
        resp = await client.get(
            LEADERBOARD_URL,
            params={"officer_id": regular_user_in_db["id"], "scope": "unit"},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_any_officer_ok(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers, officer_in_unrelated_unit
    ):
        """Admin can drill into any officer regardless of unit → 200."""
        resp = await client.get(
            LEADERBOARD_URL,
            params={"officer_id": officer_in_unrelated_unit["id"]},
            headers=admin_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_non_officer_404(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers, regular_user_in_db
    ):
        """Admin drilling into non-officer → 404."""
        resp = await client.get(
            LEADERBOARD_URL,
            params={"officer_id": regular_user_in_db["id"]},
            headers=admin_token_headers,
        )
        assert resp.status_code == 404


# ===========================================================================
# === /api/officer/upcoming-activities IDOR Tests ===
# ===========================================================================

class TestUpcomingActivitiesIDOR:
    """IDOR tests for GET /api/officer/upcoming-activities."""

    @pytest.mark.asyncio
    async def test_officer_self_ok(self, client: AsyncClient, officer_user_in_db, officer_token_headers):
        """Officer default → 200."""
        now = datetime.now(timezone.utc)
        resp = await client.get(
            UPCOMING_URL,
            params={"month": now.month, "year": now.year},
            headers=officer_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_officer_other_404(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers, officer2_in_unit1
    ):
        """Officer trying to view another officer's activities → 404."""
        now = datetime.now(timezone.utc)
        resp = await client.get(
            UPCOMING_URL,
            params={"officer_id": officer2_in_unit1["id"], "month": now.month, "year": now.year},
            headers=officer_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_descendant_ok(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_in_child_unit
    ):
        """Manager drilling into descendant officer → 200."""
        now = datetime.now(timezone.utc)
        resp = await client.get(
            UPCOMING_URL,
            params={"officer_id": officer_in_child_unit["id"], "scope": "unit", "month": now.month, "year": now.year},
            headers=manager_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_manager_out_of_scope_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_in_unrelated_unit
    ):
        """Manager drilling into unrelated officer → 404."""
        now = datetime.now(timezone.utc)
        resp = await client.get(
            UPCOMING_URL,
            params={"officer_id": officer_in_unrelated_unit["id"], "scope": "unit", "month": now.month, "year": now.year},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_any_officer_ok(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers, officer_in_unrelated_unit
    ):
        """Admin can drill into any officer → 200."""
        now = datetime.now(timezone.utc)
        resp = await client.get(
            UPCOMING_URL,
            params={"officer_id": officer_in_unrelated_unit["id"], "month": now.month, "year": now.year},
            headers=admin_token_headers,
        )
        assert resp.status_code == 200


# ===========================================================================
# === Runtime Behavior: TodaySchedule drill-down ===
# ===========================================================================

class TestUpcomingActivitiesDrillDown:
    """
    Verify that manager drill-down into a specific officer returns ONLY that
    officer's activities, not the whole team's.
    """

    @pytest.mark.asyncio
    async def test_drilldown_returns_only_target_officer_activities(
        self,
        client: AsyncClient,
        seed_lead_dependencies,
        officer_user_in_db,
        officer2_in_unit1,
        manager_user_in_db,
        manager_token_headers,
    ):
        """
        Setup: officer1 has 2 leads with activities, officer2 has 1 lead.
        Manager drills into officer1 → sees only officer1's 2 activities.
        Manager drills into officer2 → sees only officer2's 1 activity.
        """
        now = datetime.now(timezone.utc)
        # Activities in current month
        activity_time = now.replace(day=15, hour=10, minute=0, second=0, microsecond=0)
        if activity_time < now:
            # If day 15 already passed, use a future day
            activity_time = now.replace(day=min(28, now.day + 5), hour=10, minute=0, second=0, microsecond=0)

        # Officer 1: 2 leads
        await _create_lead_with_activity(
            officer_user_in_db["id"], 1, "Lead A (officer1)", activity_time
        )
        await _create_lead_with_activity(
            officer_user_in_db["id"], 1, "Lead B (officer1)",
            activity_time + timedelta(hours=2),
        )
        # Officer 2: 1 lead
        await _create_lead_with_activity(
            officer2_in_unit1["id"], 1, "Lead C (officer2)",
            activity_time + timedelta(hours=1),
        )

        # Manager drills into officer1 (V12: scope=unit required for manager)
        resp1 = await client.get(
            UPCOMING_URL,
            params={
                "officer_id": officer_user_in_db["id"],
                "scope": "unit",
                "month": now.month,
                "year": now.year,
            },
            headers=manager_token_headers,
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        names1 = {a["lead_name"] for a in data1["activities"]}
        assert "Lead A (officer1)" in names1
        assert "Lead B (officer1)" in names1
        assert "Lead C (officer2)" not in names1, (
            "Drill-down into officer1 must NOT include officer2's leads"
        )

        # Manager drills into officer2
        resp2 = await client.get(
            UPCOMING_URL,
            params={
                "officer_id": officer2_in_unit1["id"],
                "scope": "unit",
                "month": now.month,
                "year": now.year,
            },
            headers=manager_token_headers,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        names2 = {a["lead_name"] for a in data2["activities"]}
        assert "Lead C (officer2)" in names2
        assert "Lead A (officer1)" not in names2
        assert "Lead B (officer1)" not in names2


# ===========================================================================
# === Runtime Behavior: Leaderboard is_focus_officer / is_current_user ===
# ===========================================================================

class TestLeaderboardHighlightSemantics:
    """
    Verify leaderboard response correctly distinguishes is_current_user
    (the actual requester) from is_focus_officer (drill-down target).
    """

    @pytest.mark.asyncio
    async def test_officer_self_both_flags_true(
        self,
        client: AsyncClient,
        seed_lead_dependencies,
        officer_user_in_db,
        officer_token_headers,
    ):
        """
        Officer viewing own leaderboard (no drill-down):
        Their entry should have is_current_user=True AND is_focus_officer=True.
        """
        # Create a lead + consultation so officer appears in leaderboard
        now = datetime.now(timezone.utc)
        lead_id = await _create_lead_with_activity(
            officer_user_in_db["id"], 1, "Lead for ranking", now
        )
        await _create_consultation(lead_id, officer_user_in_db["id"], now)

        today = now.strftime("%Y-%m-%d")
        resp = await client.get(
            LEADERBOARD_URL,
            params={"start_date": today, "end_date": today},
            headers=officer_token_headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # Find officer's entry
        my_entry = next(
            (e for e in data["leaderboard"] if e["user_id"] == officer_user_in_db["id"]),
            None,
        )
        assert my_entry is not None, "Officer should appear in leaderboard"
        assert my_entry["is_current_user"] is True
        assert my_entry["is_focus_officer"] is True

    @pytest.mark.asyncio
    async def test_manager_drilldown_focus_not_current(
        self,
        client: AsyncClient,
        seed_lead_dependencies,
        officer_user_in_db,
        officer2_in_unit1,
        manager_user_in_db,
        manager_token_headers,
    ):
        """
        Manager drills into officer1. Leaderboard should show:
        - officer1: is_focus_officer=True, is_current_user=False
        - officer2: is_focus_officer=False, is_current_user=False
        - No entry should have is_current_user=True (manager is not an officer)

        current_user_rank should be null (manager not in officer population).
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # Officer1: 3 consultations
        lead1 = await _create_lead_with_activity(
            officer_user_in_db["id"], 1, "Lead R1", now
        )
        for _ in range(3):
            await _create_consultation(lead1, officer_user_in_db["id"], now)

        # Officer2: 1 consultation
        lead2 = await _create_lead_with_activity(
            officer2_in_unit1["id"], 1, "Lead R2", now
        )
        await _create_consultation(lead2, officer2_in_unit1["id"], now)

        resp = await client.get(
            LEADERBOARD_URL,
            params={
                "officer_id": officer_user_in_db["id"],
                "scope": "unit",
                "start_date": today,
                "end_date": today,
            },
            headers=manager_token_headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # current_user_rank should reflect drill-down target's rank
        assert data["current_user_rank"] is not None, (
            "current_user_rank should reflect the drill-down target's rank"
        )

        # Check entries
        entries_by_id = {e["user_id"]: e for e in data["leaderboard"]}

        officer1_entry = entries_by_id.get(officer_user_in_db["id"])
        assert officer1_entry is not None
        assert officer1_entry["is_focus_officer"] is True, (
            "Drill-down target must have is_focus_officer=True"
        )
        assert officer1_entry["is_current_user"] is False, (
            "Drill-down target must NOT have is_current_user=True when requester is manager"
        )

        officer2_entry = entries_by_id.get(officer2_in_unit1["id"])
        assert officer2_entry is not None
        assert officer2_entry["is_focus_officer"] is False
        assert officer2_entry["is_current_user"] is False

        # No entry should have is_current_user=True
        assert not any(e["is_current_user"] for e in data["leaderboard"]), (
            "No leaderboard entry should have is_current_user=True when requester is a manager"
        )

    @pytest.mark.asyncio
    async def test_admin_drilldown_current_user_rank_reflects_target(
        self,
        client: AsyncClient,
        seed_lead_dependencies,
        officer_user_in_db,
        admin_user_in_db,
        admin_token_headers,
    ):
        """
        Admin drills into officer. current_user_rank should be the officer's rank,
        not null (because the drill-down target IS an officer).
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        lead = await _create_lead_with_activity(
            officer_user_in_db["id"], 1, "Lead Admin Test", now
        )
        await _create_consultation(lead, officer_user_in_db["id"], now)

        resp = await client.get(
            LEADERBOARD_URL,
            params={
                "officer_id": officer_user_in_db["id"],
                "start_date": today,
                "end_date": today,
            },
            headers=admin_token_headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        # current_user_rank should reflect the drilled officer's rank
        assert data["current_user_rank"] is not None
        assert data["current_user_rank"] >= 1


# ===========================================================================
# === /api/officer/my-kpi-plan Route Wiring Tests ===
# ===========================================================================

class TestMyKpiPlanRouteWiring:
    """
    Route-level tests for GET /api/officer/my-kpi-plan.

    Proves that resolve_kpi_plan_officer_id is wired correctly through
    FastAPI middleware, returning the right HTTP status codes:
    - 200 + null: valid officer, no plan
    - 200 + body: valid officer, plan exists
    - 400: manager/admin without officer_id
    - 404: IDOR failure (out-of-scope, non-officer, nonexistent)
    """

    @pytest.mark.asyncio
    async def test_officer_self_200_null_no_plan(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers
    ):
        """Officer viewing own plan (no plan exists) → 200 + null body."""
        resp = await client.get(
            KPI_PLAN_URL,
            params={"fiscal_year": 2099},  # Far future → no plan
            headers=officer_token_headers,
        )
        assert resp.status_code == 200
        assert resp.json() is None

    @pytest.mark.asyncio
    async def test_officer_other_404(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers, officer2_in_unit1
    ):
        """Officer viewing another officer's plan → 404 (IDOR)."""
        resp = await client.get(
            KPI_PLAN_URL,
            params={"officer_id": officer2_in_unit1["id"]},
            headers=officer_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_without_officer_id_400(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers
    ):
        """Manager without officer_id → 400 (BusinessRuleViolation)."""
        resp = await client.get(KPI_PLAN_URL, headers=manager_token_headers)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_without_officer_id_400(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers
    ):
        """Admin without officer_id → 400 (BusinessRuleViolation)."""
        resp = await client.get(KPI_PLAN_URL, headers=admin_token_headers)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_manager_valid_officer_200(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_user_in_db
    ):
        """Manager + valid officer_id in scope → 200 (null or plan data)."""
        resp = await client.get(
            KPI_PLAN_URL,
            params={"officer_id": officer_user_in_db["id"]},
            headers=manager_token_headers,
        )
        assert resp.status_code == 200
        # Body is null (no plan) or plan dict — either is valid 200

    @pytest.mark.asyncio
    async def test_manager_out_of_scope_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, officer_in_unrelated_unit
    ):
        """Manager + officer in unrelated unit → 404 (IDOR)."""
        resp = await client.get(
            KPI_PLAN_URL,
            params={"officer_id": officer_in_unrelated_unit["id"]},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_manager_non_officer_target_404(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers, regular_user_in_db
    ):
        """Manager + non-officer user → 404."""
        resp = await client.get(
            KPI_PLAN_URL,
            params={"officer_id": regular_user_in_db["id"]},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_valid_officer_200(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers, officer_user_in_db
    ):
        """Admin + valid officer_id → 200."""
        resp = await client.get(
            KPI_PLAN_URL,
            params={"officer_id": officer_user_in_db["id"]},
            headers=admin_token_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_non_officer_target_404(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers, regular_user_in_db
    ):
        """Admin + non-officer target → 404."""
        resp = await client.get(
            KPI_PLAN_URL,
            params={"officer_id": regular_user_in_db["id"]},
            headers=admin_token_headers,
        )
        assert resp.status_code == 404


# ===========================================================================
# === /api/officer/my-kpi-plan Response Shape Tests ===
# ===========================================================================

async def _create_kpi_plan_with_months(
    unit_id: int,
    officer_id: int,
    fiscal_year: int,
    actual_consultations_avgs: dict[int, Decimal] | None = None,
) -> int:
    """Create a KpiPlan with 12 KpiPlanMonth rows.

    actual_consultations_avgs: {month: Decimal} for months that have actuals.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            plan = models.KpiPlan(
                unit_id=unit_id,
                officer_id=officer_id,
                fiscal_year=fiscal_year,
                annual_enrollment_target=84,
                sla_target=Decimal("85.00"),
                response_time_target=Decimal("2.00"),
                is_active=True,
            )
            session.add(plan)
            await session.flush()

            for m in range(1, 13):
                avg = (actual_consultations_avgs or {}).get(m)
                pm = models.KpiPlanMonth(
                    plan_id=plan.id,
                    month=m,
                    enrollment_target=7,
                    working_days=22,
                    weight=Decimal("0.0833"),
                    consultations_daily=10,
                    conversion_rate=Decimal("15.00"),
                    win_rate=Decimal("33.00"),
                    actual_consultations_avg=avg,
                )
                session.add(pm)
            plan_id = plan.id
    return plan_id


class TestMyKpiPlanResponseShape:
    """
    Verify that /api/officer/my-kpi-plan response includes
    consultations_actual_avg field (Gap 3) with correct values.
    """

    @pytest.mark.asyncio
    async def test_response_includes_consultations_actual_avg(
        self,
        client: AsyncClient,
        seed_lead_dependencies,
        officer_user_in_db,
        officer_token_headers,
    ):
        """Plan with actual_consultations_avg on months 1-2 → response reflects values."""
        unit_id = seed_lead_dependencies["unit_id"]
        await _create_kpi_plan_with_months(
            unit_id=unit_id,
            officer_id=officer_user_in_db["id"],
            fiscal_year=2077,
            actual_consultations_avgs={
                1: Decimal("12.50"),
                2: Decimal("8.00"),
            },
        )

        resp = await client.get(
            KPI_PLAN_URL,
            params={"fiscal_year": 2077},
            headers=officer_token_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert len(data["months"]) == 12

        # Month 1: actual_consultations_avg = 12.5
        m1 = data["months"][0]
        assert m1["month"] == 1
        assert m1["consultations_actual_avg"] == 12.5

        # Month 2: actual_consultations_avg = 8.0
        m2 = data["months"][1]
        assert m2["consultations_actual_avg"] == 8.0

        # Month 3: no actual → null
        m3 = data["months"][2]
        assert m3["consultations_actual_avg"] is None

        # Months 4-12: all null
        expected = {1: 12.5, 2: 8.0}
        for m in data["months"]:
            assert m["consultations_actual_avg"] == expected.get(m["month"])


# ===========================================================================
# Distribution Panel ("Điểm bận") — scope / IDOR / privacy
# ===========================================================================
DISTRIBUTION_URL = "/api/officer/distribution-panel"


class TestDistributionPanelScope:
    """Endpoint này CỐ Ý rộng hơn dashboard: officer xem được CẢ ĐƠN VỊ mình.

    Vì thế phải ghim chặt: không rò sang đơn vị khác, không nhận tham số trỏ
    người/đơn vị khác, và lời khuyên cá nhân chỉ hiện trên dòng của chính mình.
    """

    @pytest.mark.asyncio
    async def test_officer_sees_own_unit_including_colleagues(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers,
        officer2_in_unit1,
    ):
        """Officer xem được cả đơn vị — thấy CẢ đồng nghiệp cùng unit."""
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        body = resp.json()

        ids = {e["user_id"] for e in body["entries"]}
        assert officer_user_in_db["id"] in ids
        assert officer2_in_unit1["id"] in ids, "phải thấy đồng nghiệp cùng đơn vị"
        assert body["total_officers"] == len(body["entries"])

    @pytest.mark.asyncio
    async def test_officer_does_not_see_other_unit(
        self, client: AsyncClient, officer_token_headers, officer_in_unrelated_unit,
    ):
        """Officer KHÔNG thấy người ở đơn vị khác."""
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        ids = {e["user_id"] for e in resp.json()["entries"]}
        assert officer_in_unrelated_unit["id"] not in ids

    @pytest.mark.asyncio
    async def test_officer_other_officer_id_404(
        self, client: AsyncClient, officer_token_headers, officer2_in_unit1,
    ):
        """Trỏ officer_id người khác ⇒ 404 (không lộ tồn tại)."""
        resp = await client.get(
            DISTRIBUTION_URL,
            params={"officer_id": officer2_in_unit1["id"]},
            headers=officer_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_officer_other_unit_id_404(
        self, client: AsyncClient, officer_token_headers, unrelated_unit,
    ):
        """Trỏ unit_id đơn vị khác ⇒ 404."""
        resp = await client.get(
            DISTRIBUTION_URL,
            params={"unit_id": unrelated_unit},
            headers=officer_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_boost_only_on_own_row(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers,
        officer2_in_unit1,
    ):
        """🔒 Lời khuyên CHỈ hiện trên dòng của chính người xem."""
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        entries = resp.json()["entries"]

        mine = [e for e in entries if e["user_id"] == officer_user_in_db["id"]]
        others = [e for e in entries if e["user_id"] != officer_user_in_db["id"]]
        assert len(mine) == 1
        assert mine[0]["is_current_user"] is True
        assert mine[0]["boost"], "dòng của mình phải có lời khuyên"
        for e in others:
            assert e["is_current_user"] is False
            assert e["boost"] is None, "KHÔNG được lộ lời khuyên của người khác"
            # nhưng số liệu + chẩn đoán vẫn công khai (minh bạch)
            assert e["diagnosis"]
            assert "eff_util_pct" in e

    @pytest.mark.asyncio
    async def test_manager_ok(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers,
    ):
        resp = await client.get(DISTRIBUTION_URL, headers=manager_token_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_ok(
        self, client: AsyncClient, admin_user_in_db, admin_token_headers,
    ):
        resp = await client.get(DISTRIBUTION_URL, headers=admin_token_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_regular_user_blocked(
        self, client: AsyncClient, regular_user_token_headers,
    ):
        """Role ngoài officer/manager/admin bị chặn (fail-close)."""
        resp = await client.get(DISTRIBUTION_URL, headers=regular_user_token_headers)
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_numbers_are_engine_numbers(
        self, client: AsyncClient, officer_token_headers,
    ):
        """Bất biến số liệu: deducted = workload - dist_load, và điểm bận
        = dist_load/(capacity*weight)*100 — đúng công thức engine."""
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        for e in resp.json()["entries"]:
            assert e["deducted"] == e["workload"] - e["dist_load"]
            expected_eff = round(
                e["dist_load"] / (e["max_capacity"] * e["weight"]) * 100, 1
            )
            assert e["eff_util_pct"] == expected_eff


# --- Bổ sung sau review: accountant deny + manager ngoài scope + scoring_mode ---
ACCOUNTANT_DIST_DATA = {
    "username": "accountant_dist",
    "email": "accountant_dist@example.com",
    "password": "AccountantDist!321",
    "role": "accountant",
    "status": "active",
}


@pytest_asyncio.fixture
async def accountant_in_unit1(seed_lead_dependencies):
    """Accountant cùng UNIT_1 — dùng để ghim Casbin DENY của endpoint này."""
    return await _create_user_and_role(
        ACCOUNTANT_DIST_DATA, "role:accountant", unit_id=1
    )


class TestDistributionPanelDenies:
    """Các nhánh CHẶN + ngữ nghĩa scoring_mode (bổ sung sau review)."""

    @pytest.mark.asyncio
    async def test_accountant_denied(
        self, client: AsyncClient, accountant_in_unit1,
    ):
        """Accountant kế thừa role:officer nhưng PHẢI bị DENY tường minh.

        Endpoint lộ tên + tải của cả phòng tư vấn ⇒ ngoài phạm vi kế toán.
        Nếu row deny trong ACCOUNTANT_TEMPLATE bị mất, test này đỏ.
        """
        headers = await _get_token_headers(client, ACCOUNTANT_DIST_DATA)
        resp = await client.get(DISTRIBUTION_URL, headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_other_unit_denied(
        self, client: AsyncClient, manager_user_in_db, manager_token_headers,
        unrelated_unit,
    ):
        """Manager trỏ unit ngoài phạm vi ⇒ CHẶN.

        ⚠️ Ghi nhận hành vi THẬT: nhánh manager/admin ủy quyền nguyên vẹn cho
        ``get_officer_dashboard_scope`` nên trả **403** (PermissionDeniedError),
        khác nhánh officer (404). Cố ý giữ nguyên để một nguồn sự thật cho cả họ
        endpoint dashboard — test ghim đúng hành vi này, không ghim theo mong muốn.
        """
        resp = await client.get(
            DISTRIBUTION_URL,
            params={"unit_id": unrelated_unit},
            headers=manager_token_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_out_of_scope_officer_404(
        self, client: AsyncClient, manager_token_headers, officer_in_unrelated_unit,
    ):
        """Drill-down sang officer ngoài phạm vi manager ⇒ 404 (không lộ tồn tại)."""
        resp = await client.get(
            DISTRIBUTION_URL,
            params={"officer_id": officer_in_unrelated_unit["id"]},
            headers=manager_token_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_scoring_mode_is_per_unit_not_first_unit(
        self, client: AsyncClient, officer_token_headers, officer2_in_unit1,
    ):
        """scoring_mode top-level PHẢI là tóm tắt đúng của các entry.

        Chấm điểm chạy per-unit; lấy mode của đơn vị ĐẦU TIÊN làm đại diện sẽ
        giải thích sai cho phần entries còn lại khi phạm vi trải nhiều đơn vị.
        Ghim: mọi entry có trường riêng, và top-level = mode chung / "mixed" / None.
        """
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        body = resp.json()
        entries = body["entries"]

        for e in entries:
            assert "scoring_mode" in e

        real_modes = {e["scoring_mode"] for e in entries if e["scoring_mode"]}
        if len(real_modes) > 1:
            assert body["scoring_mode"] == "mixed"
        elif len(real_modes) == 1:
            assert body["scoring_mode"] == next(iter(real_modes))
        else:
            assert body["scoring_mode"] is None


# ===========================================================================
# Distribution Panel — CHẾ ĐỘ ĐANG CHẠY PROD (cờ BẬT)
# ===========================================================================
# ⚠️ `.env.test` không set cờ nào ⇒ mặc định TẮT HẾT. Khi tắt thì
# self_sourced = tuition_hold = deducted = 0, dist_load == workload, weight == 1,
# và eff_util_pct == real_util_pct == fill_pct — nghĩa là mọi assert về số liệu
# trở thành hằng đúng (0 == 0, x == x) và TOÀN BỘ chủ đề của tính năng (giảm
# trừ, trọng số, "điểm bận vs chỗ đầy") KHÔNG được test. Prod unit 14 đang chạy
# member + exclude-self + finance ⇒ phải test đúng cấu hình đó.


@pytest.fixture
def prod_flags(monkeypatch):
    """Bật đúng bộ cờ đang chạy prod cho các test dưới đây."""
    from app.config import settings

    monkeypatch.setattr(settings, "ENABLE_MEMBER_WEIGHTED_ASSIGNMENT", True)
    monkeypatch.setattr(settings, "ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED", True)
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    monkeypatch.setattr(settings, "ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT", False)
    return settings


class TestDistributionPanelProdFlags:
    """Ghim bộ số ở ĐÚNG cấu hình prod — nơi các phép trừ/trọng số mới có tác dụng."""

    @pytest.mark.asyncio
    async def test_scoring_mode_is_member_when_flags_on(
        self, client: AsyncClient, officer_token_headers, prod_flags,
    ):
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Với cờ TẮT giá trị này là "legacy" — assert dưới đây chỉ đúng khi cờ BẬT,
        # nên nó cũng là canary phát hiện test lại rơi về chế độ mặc định.
        assert body["scoring_mode"] == "member"
        for e in body["entries"]:
            assert e["scoring_mode"] == "member"

    @pytest.mark.asyncio
    async def test_deducted_equals_self_plus_tuition_minus_overlap(
        self, client: AsyncClient, officer_token_headers, prod_flags,
    ):
        """Bất biến then chốt: overlap PHẢI có trên wire và khớp phép trừ.

        Thiếu `overlap`, client sẽ trình bày `self + tuition` như một phép cộng
        không bằng `deducted` (phần giao bị trừ hai lần trong đầu người đọc).
        """
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        for e in resp.json()["entries"]:
            assert "overlap" in e
            assert e["deducted"] == e["self_sourced"] + e["tuition_hold"] - e["overlap"]
            assert e["overlap"] <= min(e["self_sourced"], e["tuition_hold"])
            assert e["dist_load"] == e["workload"] - e["deducted"]

    @pytest.mark.asyncio
    async def test_weight_actually_divides_eff_util(
        self, client: AsyncClient, officer_token_headers, prod_flags,
    ):
        """Với cờ TẮT thì weight luôn = 1 nên phép chia này vô nghĩa."""
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        for e in resp.json()["entries"]:
            expected = round(
                e["dist_load"] / (e["max_capacity"] * e["weight"]) * 100, 1
            )
            assert e["eff_util_pct"] == expected
            # real_util_pct KHÔNG chia trọng số
            assert e["real_util_pct"] == round(
                e["dist_load"] / e["max_capacity"] * 100, 1
            )

    @pytest.mark.asyncio
    async def test_username_not_exposed(
        self, client: AsyncClient, officer_token_headers, prod_flags,
    ):
        """Endpoint trả cả roster đơn vị ⇒ không được kèm login-id đồng nghiệp."""
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        for e in resp.json()["entries"]:
            assert "username" not in e
            assert "email" not in e

    @pytest.mark.asyncio
    async def test_diagnosis_never_addresses_reader_on_peer_rows(
        self, client: AsyncClient, officer_user_in_db, officer_token_headers,
        officer2_in_unit1, prod_flags,
    ):
        """`diagnosis` render ở MỌI dòng nên không được xưng "bạn"."""
        resp = await client.get(DISTRIBUTION_URL, headers=officer_token_headers)
        assert resp.status_code == 200
        for e in resp.json()["entries"]:
            if e["user_id"] != officer_user_in_db["id"]:
                assert "bạn" not in e["diagnosis"].lower(), e["diagnosis"]
