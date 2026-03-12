# tests/unit/test_kpi_resolver.py
"""
Unit tests for kpi_resolver.py invariants and kpi_service.py wrappers.

Tests resolver behavior that can be verified without DB:
- period_type auto-derivation from catalog
- aggregate_annual_progresses() resolution_kind forwarding
- TargetResolution / AnnualProgressResolution shape

DB-dependent tests (actual resolution chain) belong in integration tests.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.kpi_resolver import TargetResolution, AnnualProgressResolution
from app.services.kpi_service import aggregate_annual_progresses


# =============================================================================
# DATACLASS SHAPE TESTS
# =============================================================================


@pytest.mark.unit
class TestTargetResolutionShape:

    def test_target_resolution_fields(self):
        tr = TargetResolution(
            value=10.0,
            source_type="officer",
            source_plan_id=42,
            is_unit_target=False,
            config_record=None,
        )
        assert tr.value == 10.0
        assert tr.source_type == "officer"
        assert tr.source_plan_id == 42
        assert tr.is_unit_target is False
        assert tr.config_record is None

    def test_target_resolution_default_value(self):
        tr = TargetResolution(
            value=7.0,
            source_type="default",
            source_plan_id=None,
            is_unit_target=False,
            config_record=None,
        )
        assert tr.source_type == "default"


@pytest.mark.unit
class TestAnnualProgressResolutionShape:

    def test_assigned_kind(self):
        apr = AnnualProgressResolution(
            annual_target=80,
            achieved_ytd=45,
            resolution_kind="assigned",
            source_description="Officer KpiTarget",
            target_record=None,
            seasonal_weights=None,
        )
        assert apr.resolution_kind == "assigned"
        assert apr.annual_target == 80

    def test_inherited_estimate_kind(self):
        apr = AnnualProgressResolution(
            annual_target=26,
            achieved_ytd=10,
            resolution_kind="inherited_estimate",
            source_description="Unit plan (ước tính, 3 officers)",
            target_record=None,
            seasonal_weights=[0.08] * 12,
        )
        assert apr.resolution_kind == "inherited_estimate"
        assert "ước tính" in apr.source_description


# =============================================================================
# RESOLVE_TARGET PERIOD_TYPE TESTS
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
class TestResolveTargetPeriodType:
    """Verify resolve_target() auto-derives period_type from catalog."""

    @patch("app.repositories.KpiRepository")
    async def test_none_period_type_uses_catalog(self, MockRepo):
        """When period_type=None, resolver should use catalog value."""
        from app.services.kpi_resolver import resolve_target

        mock_repo_instance = MagicMock()
        mock_repo_instance.get_resolved_kpi_config = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo_instance

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        result = await resolve_target(
            db=mock_db,
            kpi_code="consultations_daily",
            period_type=None,  # Should auto-derive "daily" from catalog
        )

        # Verify repo was called with catalog-derived period_type
        call_kwargs = mock_repo_instance.get_resolved_kpi_config.call_args
        assert call_kwargs.kwargs.get("period_type") == "daily"

        # Default value from catalog when no config found
        assert result.value == 10.0  # consultations_daily default
        assert result.source_type == "default"

    @patch("app.repositories.KpiRepository")
    async def test_mismatched_period_type_uses_catalog(self, MockRepo):
        """When caller passes wrong period_type, resolver should use catalog value."""
        from app.services.kpi_resolver import resolve_target

        mock_repo_instance = MagicMock()
        mock_repo_instance.get_resolved_kpi_config = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo_instance

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        result = await resolve_target(
            db=mock_db,
            kpi_code="consultations_daily",
            period_type="monthly",  # WRONG — catalog says "daily"
        )

        # Should still return default (10) — meaning it used catalog period
        assert result.value == 10.0
        assert result.source_type == "default"


# =============================================================================
# AGGREGATE ANNUAL PROGRESSES — resolution_kind FORWARDING
# =============================================================================


@pytest.mark.unit
class TestAggregateResolutionKind:

    def _make_progress(self, resolution_kind=None, status="in_progress", annual=80, ytd=40):
        return {
            "kpi_code": "enrollments_annual",
            "fiscal_year": 2026,
            "annual_target": annual,
            "achieved_ytd": ytd,
            "remaining": annual - ytd,
            "progress_pct": round(ytd / annual * 100, 1) if annual > 0 else 0,
            "months_left": 10,
            "monthly_target": round((annual - ytd) / 10, 1),
            "status": status,
            "on_track": status in ("in_progress", "completed"),
            "surplus": None,
            "last_sync_at": None,
            "resolution_kind": resolution_kind,
        }

    def test_all_assigned_returns_assigned(self):
        progresses = [
            self._make_progress(resolution_kind="assigned"),
            self._make_progress(resolution_kind="assigned"),
            self._make_progress(resolution_kind="assigned"),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result is not None
        assert result["resolution_kind"] == "assigned"

    def test_any_inherited_returns_inherited_estimate(self):
        progresses = [
            self._make_progress(resolution_kind="assigned"),
            self._make_progress(resolution_kind="inherited_estimate"),
            self._make_progress(resolution_kind="assigned"),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result is not None
        assert result["resolution_kind"] == "inherited_estimate"

    def test_all_inherited_returns_inherited_estimate(self):
        progresses = [
            self._make_progress(resolution_kind="inherited_estimate"),
            self._make_progress(resolution_kind="inherited_estimate"),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result is not None
        assert result["resolution_kind"] == "inherited_estimate"

    def test_missing_resolution_kind_returns_none(self):
        progresses = [
            self._make_progress(resolution_kind=None),
            self._make_progress(resolution_kind=None),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result is not None
        assert result["resolution_kind"] is None

    def test_mixed_none_and_assigned_returns_none(self):
        """If any member has None resolution_kind, aggregate can't be 'assigned'."""
        progresses = [
            self._make_progress(resolution_kind="assigned"),
            self._make_progress(resolution_kind=None),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result is not None
        # Not all assigned (one is None) → not "assigned"
        # No inherited_estimate → not "inherited_estimate"
        assert result["resolution_kind"] is None

    def test_empty_progresses_returns_none(self):
        result = aggregate_annual_progresses([])
        assert result is None

    def test_aggregate_has_resolution_kind_field(self):
        """Contract: aggregate always includes resolution_kind in response."""
        progresses = [self._make_progress(resolution_kind="assigned")]
        result = aggregate_annual_progresses(progresses)
        assert "resolution_kind" in result

    def test_aggregate_team_breakdown_fields(self):
        """Contract: aggregate includes R1 team breakdown fields."""
        progresses = [
            self._make_progress(status="in_progress"),
            self._make_progress(status="at_risk"),
            self._make_progress(status="overdue"),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result["officer_count"] == 3
        assert result["officers_at_risk"] == 1
        assert result["officers_overdue"] == 1

    def test_aggregate_sums_targets_correctly(self):
        progresses = [
            self._make_progress(annual=80, ytd=40),
            self._make_progress(annual=60, ytd=30),
        ]
        result = aggregate_annual_progresses(progresses)
        assert result["annual_target"] == 140
        assert result["achieved_ytd"] == 70
