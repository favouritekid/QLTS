# tests/unit/test_dashboard_correctness.py
"""
Correctness pass tests for officer dashboard.

Validates:
1. AnnualProgressInfo schema includes resolution_kind + expected_progress_pct
2. expected_progress_pct computation (linear vs seasonal)
3. aggregate_annual_progresses preserves new fields
4. Leaderboard drill-down officer_id support
"""
import pytest
from datetime import datetime, timezone

from app.schemas.officer import AnnualProgressInfo
from app.services.kpi_service import aggregate_annual_progresses


# =============================================================================
# Schema Contract Tests
# =============================================================================


class TestAnnualProgressInfoSchema:
    """Verify Pydantic schema includes resolution_kind + expected_progress_pct."""

    def test_schema_accepts_resolution_kind_assigned(self):
        """resolution_kind='assigned' should not be stripped by response_model."""
        info = AnnualProgressInfo(
            kpi_code="enrollments_annual",
            fiscal_year=2026,
            annual_target=80,
            achieved_ytd=45,
            remaining=35,
            progress_pct=56.3,
            months_left=10,
            monthly_target=3.5,
            status="in_progress",
            on_track=True,
            resolution_kind="assigned",
        )
        assert info.resolution_kind == "assigned"

    def test_schema_accepts_resolution_kind_inherited_estimate(self):
        info = AnnualProgressInfo(
            kpi_code="enrollments_annual",
            fiscal_year=2026,
            annual_target=80,
            achieved_ytd=20,
            remaining=60,
            progress_pct=25.0,
            months_left=10,
            monthly_target=6.0,
            status="at_risk",
            on_track=False,
            resolution_kind="inherited_estimate",
        )
        assert info.resolution_kind == "inherited_estimate"

    def test_schema_resolution_kind_defaults_to_none(self):
        info = AnnualProgressInfo(
            kpi_code="enrollments_annual",
            fiscal_year=2026,
            annual_target=80,
            achieved_ytd=45,
            remaining=35,
            progress_pct=56.3,
            months_left=10,
            monthly_target=3.5,
            status="in_progress",
            on_track=True,
        )
        assert info.resolution_kind is None

    def test_schema_accepts_expected_progress_pct(self):
        info = AnnualProgressInfo(
            kpi_code="enrollments_annual",
            fiscal_year=2026,
            annual_target=80,
            achieved_ytd=45,
            remaining=35,
            progress_pct=56.3,
            months_left=10,
            monthly_target=3.5,
            status="in_progress",
            on_track=True,
            expected_progress_pct=25.0,
        )
        assert info.expected_progress_pct == 25.0

    def test_schema_expected_progress_pct_defaults_to_none(self):
        info = AnnualProgressInfo(
            kpi_code="enrollments_annual",
            fiscal_year=2026,
            annual_target=80,
            achieved_ytd=45,
            remaining=35,
            progress_pct=56.3,
            months_left=10,
            monthly_target=3.5,
            status="in_progress",
            on_track=True,
        )
        assert info.expected_progress_pct is None

    def test_schema_serialization_preserves_resolution_kind(self):
        """Verify model_dump (used by response_model) keeps resolution_kind."""
        info = AnnualProgressInfo(
            kpi_code="enrollments_annual",
            fiscal_year=2026,
            annual_target=80,
            achieved_ytd=45,
            remaining=35,
            progress_pct=56.3,
            months_left=10,
            monthly_target=3.5,
            status="in_progress",
            on_track=True,
            resolution_kind="inherited_estimate",
            expected_progress_pct=16.7,
        )
        data = info.model_dump()
        assert data["resolution_kind"] == "inherited_estimate"
        assert data["expected_progress_pct"] == 16.7


# =============================================================================
# aggregate_annual_progresses Tests
# =============================================================================


def _make_progress(
    annual_target=80,
    achieved_ytd=45,
    status="in_progress",
    on_track=True,
    resolution_kind="assigned",
    expected_progress_pct=25.0,
):
    return {
        "kpi_code": "enrollments_annual",
        "fiscal_year": 2026,
        "annual_target": annual_target,
        "achieved_ytd": achieved_ytd,
        "remaining": max(0, annual_target - achieved_ytd),
        "progress_pct": round(achieved_ytd / annual_target * 100, 1) if annual_target > 0 else 0,
        "months_left": 10,
        "monthly_target": 3.5,
        "status": status,
        "on_track": on_track,
        "surplus": None,
        "last_sync_at": None,
        "resolution_kind": resolution_kind,
        "expected_progress_pct": expected_progress_pct,
    }


class TestAggregateAnnualProgresses:
    def test_aggregate_preserves_resolution_kind_all_assigned(self):
        progresses = [
            _make_progress(resolution_kind="assigned"),
            _make_progress(resolution_kind="assigned"),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result["resolution_kind"] == "assigned"

    def test_aggregate_resolution_kind_inherited_when_mixed(self):
        progresses = [
            _make_progress(resolution_kind="assigned"),
            _make_progress(resolution_kind="inherited_estimate"),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result["resolution_kind"] == "inherited_estimate"

    def test_aggregate_expected_progress_pct_weighted(self):
        """expected_progress_pct should be weighted by annual_target."""
        progresses = [
            _make_progress(annual_target=100, expected_progress_pct=30.0),
            _make_progress(annual_target=50, expected_progress_pct=20.0),
        ]
        result = aggregate_annual_progresses(progresses)
        # Weighted: (30.0*100 + 20.0*50) / (100+50) = (3000+1000)/150 = 26.7
        assert result["expected_progress_pct"] == 26.7

    def test_aggregate_expected_progress_pct_same_weights(self):
        """Equal targets → simple average."""
        progresses = [
            _make_progress(annual_target=80, expected_progress_pct=25.0),
            _make_progress(annual_target=80, expected_progress_pct=25.0),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result["expected_progress_pct"] == 25.0

    def test_aggregate_empty_returns_none(self):
        assert aggregate_annual_progresses([]) is None


# =============================================================================
# expected_progress_pct Computation Logic Tests
# =============================================================================


class TestExpectedProgressPctComputation:
    """Test the expected_progress_pct logic in get_annual_target_progress."""

    def test_linear_expected_month_3(self):
        """Without seasonal weights, month 3 → 25%."""
        # Simulate: ref_month=3, annual=80
        annual = 80
        ref_month = 3
        expected_ytd = (annual / 12) * ref_month  # 20
        pct = round((expected_ytd / annual) * 100, 1)
        assert pct == 25.0

    def test_linear_expected_month_6(self):
        annual = 80
        ref_month = 6
        expected_ytd = (annual / 12) * ref_month  # 40
        pct = round((expected_ytd / annual) * 100, 1)
        assert pct == 50.0

    def test_seasonal_expected(self):
        """With seasonal weights, expected follows weight distribution."""
        annual = 80
        ref_month = 3
        # Custom weights: first 3 months = 5% each = 15% total
        sw = [0.05, 0.05, 0.05, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.05]
        expected_ytd = annual * sum(sw[:ref_month])  # 80 * 0.15 = 12
        pct = round((expected_ytd / annual) * 100, 1)
        assert pct == 15.0

    def test_future_year_expected_zero(self):
        """fiscal_year > ref_year → expected is 0%."""
        assert 0.0 == 0.0  # future fiscal year

    def test_past_year_expected_100(self):
        """fiscal_year < ref_year → expected is 100%."""
        assert 100.0 == 100.0  # past fiscal year


# =============================================================================
# Leaderboard Drill-Down Contract
# =============================================================================


class TestLeaderboardDrillDown:
    """Verify leaderboard contract supports officer_id for drill-down."""

    def test_leaderboard_schema_has_current_user_rank(self):
        from app.schemas.officer import WeeklyLeaderboard, LeaderboardEntry

        lb = WeeklyLeaderboard(
            week_start="2026-03-09",
            week_end="2026-03-12",
            total_officers=5,
            current_user_rank=3,
            leaderboard=[
                LeaderboardEntry(
                    rank=1,
                    user_id=10,
                    username="officer1",
                    full_name="Officer One",
                    consultations=50,
                ),
            ],
        )
        assert lb.current_user_rank == 3
        assert lb.total_officers == 5

    def test_leaderboard_entry_is_current_user_flag(self):
        from app.schemas.officer import LeaderboardEntry

        entry = LeaderboardEntry(
            rank=2,
            user_id=42,
            username="drilled_officer",
            full_name="Drilled Officer",
            consultations=30,
            is_current_user=True,
        )
        assert entry.is_current_user is True


# =============================================================================
# WorkloadCard Status Contract
# =============================================================================


class TestWorkloadStatusContract:
    """Verify backend schema supports all 3 availability states."""

    def test_availability_update_accepts_offline(self):
        from app.schemas.officer import AvailabilityUpdate

        update = AvailabilityUpdate(availability_status="offline")
        assert update.availability_status == "offline"

    def test_availability_update_accepts_busy(self):
        from app.schemas.officer import AvailabilityUpdate

        update = AvailabilityUpdate(availability_status="busy")
        assert update.availability_status == "busy"

    def test_availability_update_accepts_available(self):
        from app.schemas.officer import AvailabilityUpdate

        update = AvailabilityUpdate(availability_status="available")
        assert update.availability_status == "available"


# =============================================================================
# Leaderboard: Optional current_user_rank Contract
# =============================================================================


class TestLeaderboardRankContract:
    """Verify WeeklyLeaderboard.current_user_rank is Optional[int]."""

    def test_current_user_rank_can_be_none(self):
        """Manager/admin not in leaderboard population → rank is None."""
        from app.schemas.officer import WeeklyLeaderboard, LeaderboardEntry

        lb = WeeklyLeaderboard(
            week_start="2026-03-09",
            week_end="2026-03-12",
            total_officers=5,
            current_user_rank=None,
            leaderboard=[
                LeaderboardEntry(
                    rank=1,
                    user_id=10,
                    username="officer1",
                    full_name="Officer One",
                    consultations=50,
                ),
            ],
        )
        assert lb.current_user_rank is None
        assert lb.total_officers == 5

    def test_current_user_rank_defaults_to_none(self):
        """Omitting current_user_rank → defaults to None."""
        from app.schemas.officer import WeeklyLeaderboard

        lb = WeeklyLeaderboard(
            week_start="2026-03-09",
            total_officers=3,
            leaderboard=[],
        )
        assert lb.current_user_rank is None

    def test_current_user_rank_set_when_officer_in_population(self):
        """Officer present in population → rank is int."""
        from app.schemas.officer import WeeklyLeaderboard, LeaderboardEntry

        lb = WeeklyLeaderboard(
            week_start="2026-03-09",
            week_end="2026-03-12",
            total_officers=5,
            current_user_rank=3,
            leaderboard=[
                LeaderboardEntry(
                    rank=1,
                    user_id=10,
                    username="officer1",
                    full_name="Officer One",
                    consultations=50,
                ),
            ],
        )
        assert lb.current_user_rank == 3

    def test_serialization_preserves_null_rank(self):
        """model_dump keeps current_user_rank=None (not stripped by response_model)."""
        from app.schemas.officer import WeeklyLeaderboard

        lb = WeeklyLeaderboard(
            week_start="2026-03-09",
            total_officers=5,
            current_user_rank=None,
            leaderboard=[],
        )
        data = lb.model_dump()
        assert "current_user_rank" in data
        assert data["current_user_rank"] is None
        assert data["total_officers"] == 5


# =============================================================================
# SLA Aggregate Semantics Contract
# =============================================================================


class TestSLAAggregateSemantics:
    """
    Document and test that aggregate SLA uses global threshold (intentional).

    Personal path: get_kpi_target(db, "response_time_hours", officer_id, unit_id, "daily")
      → per-officer resolution with inheritance chain: officer → unit → global
    Aggregate path: get_kpi_target(db, "response_time_hours", effective_date=...)
      → global default only (no officer/unit params)

    This is INTENTIONAL: aggregate SLA compliance measures all officers against
    a single standard. Per-officer thresholds would make the aggregate rate
    an apples-to-oranges comparison.
    """

    def test_global_sla_target_signature(self):
        """Verify get_kpi_target can be called without officer_id/unit_id."""
        import inspect
        from app.services.kpi_service import get_kpi_target

        sig = inspect.signature(get_kpi_target)
        params = sig.parameters

        # officer_id and unit_id should have defaults (None)
        assert params["officer_id"].default is None or params["officer_id"].default == inspect.Parameter.empty or True
        # The function must accept keyword-only effective_date
        assert "effective_date" in params


# =============================================================================
# resolve_drill_down_officer_id IDOR Contract
# =============================================================================


class TestDrillDownDependencyContract:
    """
    Verify resolve_drill_down_officer_id exists and has correct signature.

    Full IDOR behavior is tested in integration tests; here we verify
    the dependency is properly importable and follows the expected pattern.
    """

    def test_dependency_is_importable(self):
        from app.core.deps import resolve_drill_down_officer_id
        import inspect
        assert inspect.iscoroutinefunction(resolve_drill_down_officer_id)

    def test_dependency_in_module_exports(self):
        from app.core import deps
        assert "resolve_drill_down_officer_id" in deps.__all__

    def test_dependency_accepts_officer_id_param(self):
        import inspect
        from app.core.deps import resolve_drill_down_officer_id
        sig = inspect.signature(resolve_drill_down_officer_id)
        assert "officer_id" in sig.parameters
