# tests/unit/test_officer_kpi_plan.py
"""
Unit tests for Gap 2: get_officer_kpi_plan service method.

Tests:
- Officer plan found directly
- Fallback to unit plan when no officer plan
- No plan at all → ResourceNotFoundError
- actual_enrollments read from KpiPlanMonth (source of truth)
- consultations_monthly_total = consultations_daily * working_days
- achieved_ytd = sum of actual_enrollments
- progress_pct calculation
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from app.utils.exceptions import ResourceNotFoundError


def _make_mock_user(officer_id=1, unit_id=10):
    user = MagicMock()
    user.id = officer_id
    user.unit_id = unit_id
    return user


def _make_mock_plan_month(month, enrollment_target=7, actual_enrollments=None,
                          working_days=22, consultations_daily=10,
                          conversion_rate=Decimal("15.00"), win_rate=Decimal("33.00")):
    pm = MagicMock()
    pm.month = month
    pm.enrollment_target = enrollment_target
    pm.actual_enrollments = actual_enrollments
    pm.working_days = working_days
    pm.consultations_daily = consultations_daily
    pm.conversion_rate = conversion_rate
    pm.win_rate = win_rate
    return pm


def _make_mock_plan(annual_target=84, months=None, officer_id=None):
    plan = MagicMock()
    plan.annual_enrollment_target = annual_target
    plan.officer_id = officer_id
    plan.months = months or [_make_mock_plan_month(m) for m in range(1, 13)]
    return plan


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetOfficerKpiPlan:
    """Tests for officer_service.get_officer_kpi_plan()."""

    @patch("app.services.officer_service.OfficerRepository")
    @patch("app.repositories.kpi_planning_repository.KpiPlanningRepository")
    async def test_returns_officer_plan_directly(self, MockPlanningRepo, MockOfficerRepo):
        """When officer has own plan, source='officer'."""
        from app.services.officer_service import get_officer_kpi_plan

        mock_db = AsyncMock()
        mock_user = _make_mock_user()

        # Setup OfficerRepository mock
        mock_officer_repo = MagicMock()
        mock_officer_repo.get_officer_with_capacity = AsyncMock(return_value=mock_user)
        MockOfficerRepo.return_value = mock_officer_repo

        # Setup KpiPlanningRepository mock
        mock_plan = _make_mock_plan(officer_id=1)
        mock_planning_repo = MagicMock()
        mock_planning_repo.get_active_plan_by_scope = AsyncMock(return_value=mock_plan)

        with patch("app.repositories.kpi_planning_repository.KpiPlanningRepository", return_value=mock_planning_repo):
            result = await get_officer_kpi_plan(mock_db, officer_id=1, fiscal_year=2026)

        assert result["source"] == "officer"
        assert result["fiscal_year"] == 2026
        assert result["annual_target"] == 84
        assert len(result["months"]) == 12

    @patch("app.services.officer_service.OfficerRepository")
    async def test_falls_back_to_unit_plan(self, MockOfficerRepo):
        """When no officer plan, falls back to unit plan with source='unit'."""
        from app.services.officer_service import get_officer_kpi_plan

        mock_db = AsyncMock()
        mock_user = _make_mock_user()

        mock_officer_repo = MagicMock()
        mock_officer_repo.get_officer_with_capacity = AsyncMock(return_value=mock_user)
        MockOfficerRepo.return_value = mock_officer_repo

        unit_plan = _make_mock_plan(officer_id=None)
        mock_planning_repo = MagicMock()
        # First call (officer plan) returns None, second call (unit plan) returns plan
        mock_planning_repo.get_active_plan_by_scope = AsyncMock(
            side_effect=[None, unit_plan]
        )

        with patch("app.repositories.kpi_planning_repository.KpiPlanningRepository", return_value=mock_planning_repo):
            result = await get_officer_kpi_plan(mock_db, officer_id=1, fiscal_year=2026)

        assert result["source"] == "unit"

    @patch("app.services.officer_service.OfficerRepository")
    async def test_no_plan_raises_404(self, MockOfficerRepo):
        """When no plan at either level, raises ResourceNotFoundError."""
        from app.services.officer_service import get_officer_kpi_plan

        mock_db = AsyncMock()
        mock_user = _make_mock_user()

        mock_officer_repo = MagicMock()
        mock_officer_repo.get_officer_with_capacity = AsyncMock(return_value=mock_user)
        MockOfficerRepo.return_value = mock_officer_repo

        mock_planning_repo = MagicMock()
        mock_planning_repo.get_active_plan_by_scope = AsyncMock(return_value=None)

        with patch("app.repositories.kpi_planning_repository.KpiPlanningRepository", return_value=mock_planning_repo):
            with pytest.raises(ResourceNotFoundError):
                await get_officer_kpi_plan(mock_db, officer_id=1, fiscal_year=2026)

    @patch("app.services.officer_service.OfficerRepository")
    async def test_actual_from_kpi_plan_month(self, MockOfficerRepo):
        """actual_enrollments read directly from KpiPlanMonth (source of truth)."""
        from app.services.officer_service import get_officer_kpi_plan

        mock_db = AsyncMock()
        mock_user = _make_mock_user()

        mock_officer_repo = MagicMock()
        mock_officer_repo.get_officer_with_capacity = AsyncMock(return_value=mock_user)
        MockOfficerRepo.return_value = mock_officer_repo

        months = [_make_mock_plan_month(m, actual_enrollments=(m * 2 if m <= 3 else None)) for m in range(1, 13)]
        plan = _make_mock_plan(months=months)

        mock_planning_repo = MagicMock()
        mock_planning_repo.get_active_plan_by_scope = AsyncMock(return_value=plan)

        with patch("app.repositories.kpi_planning_repository.KpiPlanningRepository", return_value=mock_planning_repo):
            result = await get_officer_kpi_plan(mock_db, officer_id=1, fiscal_year=2026)

        # Jan=2, Feb=4, Mar=6 → total=12
        assert result["achieved_ytd"] == 12
        assert result["months"][0]["enrollment_actual"] == 2
        assert result["months"][1]["enrollment_actual"] == 4
        assert result["months"][2]["enrollment_actual"] == 6
        assert result["months"][3]["enrollment_actual"] is None

    @patch("app.services.officer_service.OfficerRepository")
    async def test_consultations_monthly_total(self, MockOfficerRepo):
        """consultations_monthly_total = consultations_daily * working_days."""
        from app.services.officer_service import get_officer_kpi_plan

        mock_db = AsyncMock()
        mock_user = _make_mock_user()

        mock_officer_repo = MagicMock()
        mock_officer_repo.get_officer_with_capacity = AsyncMock(return_value=mock_user)
        MockOfficerRepo.return_value = mock_officer_repo

        months = [_make_mock_plan_month(m, consultations_daily=8, working_days=20) for m in range(1, 13)]
        plan = _make_mock_plan(months=months)

        mock_planning_repo = MagicMock()
        mock_planning_repo.get_active_plan_by_scope = AsyncMock(return_value=plan)

        with patch("app.repositories.kpi_planning_repository.KpiPlanningRepository", return_value=mock_planning_repo):
            result = await get_officer_kpi_plan(mock_db, officer_id=1, fiscal_year=2026)

        # 8 * 20 = 160
        assert result["months"][0]["consultations_monthly_total"] == 160

    @patch("app.services.officer_service.OfficerRepository")
    async def test_progress_pct_calculation(self, MockOfficerRepo):
        """progress_pct = achieved_ytd / annual_target * 100."""
        from app.services.officer_service import get_officer_kpi_plan

        mock_db = AsyncMock()
        mock_user = _make_mock_user()

        mock_officer_repo = MagicMock()
        mock_officer_repo.get_officer_with_capacity = AsyncMock(return_value=mock_user)
        MockOfficerRepo.return_value = mock_officer_repo

        months = [_make_mock_plan_month(m, actual_enrollments=5) for m in range(1, 13)]
        plan = _make_mock_plan(annual_target=100, months=months)

        mock_planning_repo = MagicMock()
        mock_planning_repo.get_active_plan_by_scope = AsyncMock(return_value=plan)

        with patch("app.repositories.kpi_planning_repository.KpiPlanningRepository", return_value=mock_planning_repo):
            result = await get_officer_kpi_plan(mock_db, officer_id=1, fiscal_year=2026)

        # 12 months * 5 = 60 / 100 * 100 = 60.0
        assert result["achieved_ytd"] == 60
        assert result["progress_pct"] == 60.0
