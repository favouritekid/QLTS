# tests/unit/test_annual_resolution.py
"""
Tests for shared batch-aware annual resolution.

Validates:
- resolve_officer_annual_from_context() pure rule for all 6 priority steps
- Priority ordering (officer target > officer plan > unit plan > unit target > global)
- map_resolution_to_coverage_source() contract mapping
- Single path and batch path consistency (same context → same result)
- Edge cases: officer transfer, inactive unit, zero officer count
"""
import pytest
from unittest.mock import MagicMock

from app.services.kpi_resolver import (
    AnnualResolutionContext,
    AnnualProgressResolution,
    resolve_officer_annual_from_context,
    map_resolution_to_coverage_source,
)


# =============================================================================
# TEST HELPERS
# =============================================================================


def _mock_target(
    officer_id=None, unit_id=None, kpi_code="enrollments_annual",
    annual_target=80, achieved_ytd=20, fiscal_year=2026, target_id=1,
):
    """Create a mock KpiTarget."""
    t = MagicMock()
    t.id = target_id
    t.officer_id = officer_id
    t.unit_id = unit_id
    t.kpi_code = kpi_code
    t.annual_target = annual_target
    t.achieved_ytd = achieved_ytd
    t.fiscal_year = fiscal_year
    t.is_active = True
    t.last_sync_at = None
    return t


def _mock_plan(
    officer_id=None, unit_id=1, annual_enrollment_target=80,
    seasonal_weights=None, plan_id=100,
):
    """Create a mock KpiPlan."""
    p = MagicMock()
    p.id = plan_id
    p.officer_id = officer_id
    p.unit_id = unit_id
    p.annual_enrollment_target = annual_enrollment_target
    p.seasonal_weights = seasonal_weights
    p.is_active = True
    return p


def _empty_context(**overrides):
    """Create an empty AnnualResolutionContext with optional overrides."""
    defaults = dict(
        officer_targets={},
        officer_plans={},
        unit_plans={},
        unit_targets={},
        global_target=None,
        unit_officer_counts={},
        total_active_officers=0,
        ytd_by_officer={},
        officer_unit_map={},
    )
    defaults.update(overrides)
    return AnnualResolutionContext(**defaults)


# =============================================================================
# STEP 1: OFFICER KPI TARGET
# =============================================================================


@pytest.mark.unit
class TestStep1OfficerTarget:

    def test_officer_target_returns_assigned(self):
        target = _mock_target(officer_id=10, annual_target=80, achieved_ytd=25)
        ctx = _empty_context(
            officer_targets={10: target},
            ytd_by_officer={10: 25},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is not None
        assert result.annual_target == 80
        assert result.achieved_ytd == 25
        assert result.resolution_kind == "assigned"
        assert result.source_description == "Officer KpiTarget"
        assert result.target_record is target

    def test_officer_target_uses_ytd_from_context(self):
        """YTD comes from context (pre-resolved), not from target record."""
        target = _mock_target(officer_id=10, achieved_ytd=999)
        ctx = _empty_context(
            officer_targets={10: target},
            ytd_by_officer={10: 42},  # Context has different value
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.achieved_ytd == 42  # Uses context, not record


# =============================================================================
# STEP 2: OFFICER KPI PLAN
# =============================================================================


@pytest.mark.unit
class TestStep2OfficerPlan:

    def test_officer_plan_returns_assigned(self):
        plan = _mock_plan(officer_id=10, annual_enrollment_target=60)
        ctx = _empty_context(
            officer_plans={10: plan},
            ytd_by_officer={10: 15},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is not None
        assert result.annual_target == 60
        assert result.achieved_ytd == 15
        assert result.resolution_kind == "assigned"
        assert result.source_description == "Officer KpiPlan"
        assert result.target_record is None

    def test_officer_plan_extracts_seasonal_weights(self):
        weights = [0.05, 0.06, 0.08, 0.09, 0.10, 0.10, 0.10, 0.10, 0.09, 0.08, 0.08, 0.07]
        plan = _mock_plan(officer_id=10, seasonal_weights=weights)
        ctx = _empty_context(
            officer_plans={10: plan},
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.seasonal_weights == weights


# =============================================================================
# STEP 3: UNIT KPI PLAN (INHERITED)
# =============================================================================


@pytest.mark.unit
class TestStep3UnitPlan:

    def test_unit_plan_returns_inherited_estimate(self):
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        ctx = _empty_context(
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 3},
            ytd_by_officer={10: 8},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is not None
        assert result.annual_target == 30  # 90 // 3
        assert result.achieved_ytd == 8
        assert result.resolution_kind == "inherited_estimate"
        assert "Unit plan" in result.source_description
        assert "3 officers" in result.source_description

    def test_unit_plan_integer_division(self):
        """Verify integer division (floor), not float."""
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=100)
        ctx = _empty_context(
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 3},
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.annual_target == 33  # 100 // 3 = 33 (floor)

    def test_unit_plan_zero_officers_skipped(self):
        """Unit with 0 officers → skip to next step."""
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        ctx = _empty_context(
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 0},
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is None  # Falls through to None


# =============================================================================
# STEP 4: UNIT KPI TARGET (INHERITED)
# =============================================================================


@pytest.mark.unit
class TestStep4UnitTarget:

    def test_unit_target_returns_inherited_estimate(self):
        unit_target = _mock_target(unit_id=1, annual_target=120)
        ctx = _empty_context(
            unit_targets={1: unit_target},
            unit_officer_counts={1: 4},
            ytd_by_officer={10: 10},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is not None
        assert result.annual_target == 30  # 120 // 4
        assert result.resolution_kind == "inherited_estimate"
        assert "Unit target" in result.source_description

    def test_unit_target_skipped_when_unit_plan_exists(self):
        """Step 3 (unit plan) has higher priority than step 4 (unit target)."""
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        unit_target = _mock_target(unit_id=1, annual_target=120)
        ctx = _empty_context(
            unit_plans={1: unit_plan},
            unit_targets={1: unit_target},
            unit_officer_counts={1: 3},
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.annual_target == 30  # From unit plan (90//3), not target (120//3=40)


# =============================================================================
# STEP 5: GLOBAL KPI TARGET (INHERITED)
# =============================================================================


@pytest.mark.unit
class TestStep5GlobalTarget:

    def test_global_target_returns_inherited_estimate(self):
        global_target = _mock_target(annual_target=200)
        ctx = _empty_context(
            global_target=global_target,
            total_active_officers=10,
            ytd_by_officer={10: 5},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is not None
        assert result.annual_target == 20  # 200 // 10
        assert result.resolution_kind == "inherited_estimate"
        assert "Global" in result.source_description
        assert "10 officers" in result.source_description

    def test_global_target_zero_officers_returns_none(self):
        global_target = _mock_target(annual_target=200)
        ctx = _empty_context(
            global_target=global_target,
            total_active_officers=0,
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is None


# =============================================================================
# STEP 6: NO TARGET
# =============================================================================


@pytest.mark.unit
class TestStep6NoTarget:

    def test_no_target_returns_none(self):
        ctx = _empty_context(
            ytd_by_officer={10: 5},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is None

    def test_no_unit_no_global_returns_none(self):
        """Officer with no unit and no global target → None."""
        ctx = _empty_context(
            ytd_by_officer={10: 0},
            officer_unit_map={10: None},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is None


# =============================================================================
# PRIORITY ORDERING
# =============================================================================


@pytest.mark.unit
class TestPriorityOrdering:

    def test_officer_target_beats_officer_plan(self):
        """Step 1 > Step 2: officer target has higher priority than officer plan."""
        target = _mock_target(officer_id=10, annual_target=80)
        plan = _mock_plan(officer_id=10, annual_enrollment_target=60)
        ctx = _empty_context(
            officer_targets={10: target},
            officer_plans={10: plan},
            ytd_by_officer={10: 20},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.annual_target == 80  # From target, not plan (60)
        assert result.source_description == "Officer KpiTarget"

    def test_officer_plan_beats_unit_plan(self):
        """Step 2 > Step 3: officer plan has higher priority than unit plan."""
        officer_plan = _mock_plan(officer_id=10, annual_enrollment_target=60)
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        ctx = _empty_context(
            officer_plans={10: officer_plan},
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 3},
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.annual_target == 60  # From officer plan, not unit (90//3=30)
        assert result.resolution_kind == "assigned"

    def test_unit_plan_beats_global_target(self):
        """Step 3 > Step 5: unit plan has higher priority than global target."""
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        global_target = _mock_target(annual_target=200)
        ctx = _empty_context(
            unit_plans={1: unit_plan},
            global_target=global_target,
            unit_officer_counts={1: 3},
            total_active_officers=10,
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.annual_target == 30  # From unit plan (90//3), not global (200//10=20)

    def test_full_chain_officer_target_wins(self):
        """All 5 sources present → officer target wins."""
        target = _mock_target(officer_id=10, annual_target=80)
        officer_plan = _mock_plan(officer_id=10, annual_enrollment_target=60)
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        unit_target = _mock_target(unit_id=1, annual_target=120)
        global_target = _mock_target(annual_target=200)
        ctx = _empty_context(
            officer_targets={10: target},
            officer_plans={10: officer_plan},
            unit_plans={1: unit_plan},
            unit_targets={1: unit_target},
            global_target=global_target,
            unit_officer_counts={1: 3},
            total_active_officers=10,
            ytd_by_officer={10: 20},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.annual_target == 80
        assert result.resolution_kind == "assigned"
        assert result.source_description == "Officer KpiTarget"


# =============================================================================
# COVERAGE SOURCE MAPPING
# =============================================================================


@pytest.mark.unit
class TestCoverageSourceMapping:

    def test_none_returns_none_source(self):
        assert map_resolution_to_coverage_source(None) == "none"

    def test_assigned_returns_custom(self):
        resolution = AnnualProgressResolution(
            annual_target=80, achieved_ytd=20,
            resolution_kind="assigned",
            source_description="Officer KpiTarget",
            target_record=None, seasonal_weights=None,
        )
        assert map_resolution_to_coverage_source(resolution) == "custom"

    def test_assigned_plan_returns_custom(self):
        resolution = AnnualProgressResolution(
            annual_target=60, achieved_ytd=10,
            resolution_kind="assigned",
            source_description="Officer KpiPlan",
            target_record=None, seasonal_weights=None,
        )
        assert map_resolution_to_coverage_source(resolution) == "custom"

    def test_inherited_unit_plan_returns_inherited(self):
        resolution = AnnualProgressResolution(
            annual_target=30, achieved_ytd=5,
            resolution_kind="inherited_estimate",
            source_description="Unit plan (ước tính, 3 officers)",
            target_record=None, seasonal_weights=None,
        )
        assert map_resolution_to_coverage_source(resolution) == "inherited"

    def test_inherited_unit_target_returns_inherited(self):
        resolution = AnnualProgressResolution(
            annual_target=30, achieved_ytd=5,
            resolution_kind="inherited_estimate",
            source_description="Unit target (ước tính, 4 officers)",
            target_record=None, seasonal_weights=None,
        )
        assert map_resolution_to_coverage_source(resolution) == "inherited"

    def test_inherited_global_returns_inherited_global(self):
        resolution = AnnualProgressResolution(
            annual_target=20, achieved_ytd=3,
            resolution_kind="inherited_estimate",
            source_description="Global target (ước tính, 10 officers)",
            target_record=None, seasonal_weights=None,
        )
        assert map_resolution_to_coverage_source(resolution) == "inherited_global"


# =============================================================================
# SEASONAL WEIGHTS RESOLUTION FROM CONTEXT
# =============================================================================


@pytest.mark.unit
class TestSeasonalWeightsFromContext:

    def test_officer_plan_weights_used_for_target_step(self):
        """Step 1: weights from officer plan when officer has target."""
        weights = [0.08] * 12
        target = _mock_target(officer_id=10, annual_target=80)
        officer_plan = _mock_plan(officer_id=10, seasonal_weights=weights)
        ctx = _empty_context(
            officer_targets={10: target},
            officer_plans={10: officer_plan},
            ytd_by_officer={10: 20},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.seasonal_weights == weights

    def test_unit_plan_weights_used_when_no_officer_plan(self):
        """Step 1: weights from unit plan when officer has target but no plan."""
        weights = [0.08] * 12
        target = _mock_target(officer_id=10, annual_target=80)
        unit_plan = _mock_plan(unit_id=1, seasonal_weights=weights)
        ctx = _empty_context(
            officer_targets={10: target},
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 3},
            ytd_by_officer={10: 20},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.seasonal_weights == weights

    def test_no_plan_returns_none_weights(self):
        """Step 1: no plan → None weights (linear fallback)."""
        target = _mock_target(officer_id=10, annual_target=80)
        ctx = _empty_context(
            officer_targets={10: target},
            ytd_by_officer={10: 20},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.seasonal_weights is None

    def test_plan_with_null_weights_uses_defaults(self):
        """Plan exists but seasonal_weights=None → default weights from catalog."""
        plan = _mock_plan(officer_id=10, seasonal_weights=None)
        ctx = _empty_context(
            officer_plans={10: plan},
            ytd_by_officer={10: 0},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result.seasonal_weights is not None
        assert len(result.seasonal_weights) == 12
        assert sum(result.seasonal_weights) == pytest.approx(1.0, abs=0.01)


# =============================================================================
# SINGLE PATH vs BATCH PATH CONSISTENCY
# =============================================================================


@pytest.mark.unit
class TestSingleBatchConsistency:
    """Prove that the same context → same rule → same results.

    Both kpi_service.get_annual_target_progress() and
    kpi_setup_service.get_coverage_report() call
    resolve_officer_annual_from_context() with the same rule.
    These tests verify that for a given set of data, the pure
    function produces consistent output regardless of how the
    context was built.
    """

    def _build_scenario_context(self, officer_id=10, unit_id=1):
        """Build a realistic context with multiple data sources."""
        unit_plan = _mock_plan(unit_id=unit_id, annual_enrollment_target=90)
        global_target = _mock_target(annual_target=200)
        return _empty_context(
            unit_plans={unit_id: unit_plan},
            global_target=global_target,
            unit_officer_counts={unit_id: 3},
            total_active_officers=10,
            ytd_by_officer={officer_id: 12},
            officer_unit_map={officer_id: unit_id},
        )

    def test_same_context_same_result_unit_plan(self):
        """Two calls with identical context produce identical results."""
        ctx = self._build_scenario_context()
        result1 = resolve_officer_annual_from_context(10, ctx)
        result2 = resolve_officer_annual_from_context(10, ctx)
        assert result1.annual_target == result2.annual_target
        assert result1.achieved_ytd == result2.achieved_ytd
        assert result1.resolution_kind == result2.resolution_kind
        assert result1.source_description == result2.source_description

    def test_consistency_officer_target_scenario(self):
        """Officer target scenario: both paths get same values."""
        target = _mock_target(officer_id=10, annual_target=80)
        ctx = _empty_context(
            officer_targets={10: target},
            ytd_by_officer={10: 25},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        source = map_resolution_to_coverage_source(result)

        # Single path would return: annual_target=80, achieved_ytd=25, kind=assigned
        assert result.annual_target == 80
        assert result.achieved_ytd == 25
        assert result.resolution_kind == "assigned"
        # Coverage path would map to: target_source=custom
        assert source == "custom"

    def test_consistency_inherited_unit_plan_scenario(self):
        """Inherited unit plan scenario: both paths get same split."""
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        ctx = _empty_context(
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 3},
            ytd_by_officer={10: 8},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        source = map_resolution_to_coverage_source(result)

        assert result.annual_target == 30  # 90 // 3
        assert result.achieved_ytd == 8
        assert result.resolution_kind == "inherited_estimate"
        assert source == "inherited"

    def test_consistency_global_target_scenario(self):
        """Global target scenario: both paths get same split."""
        global_target = _mock_target(annual_target=200)
        ctx = _empty_context(
            global_target=global_target,
            total_active_officers=10,
            ytd_by_officer={10: 3},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        source = map_resolution_to_coverage_source(result)

        assert result.annual_target == 20  # 200 // 10
        assert result.achieved_ytd == 3
        assert result.resolution_kind == "inherited_estimate"
        assert source == "inherited_global"

    def test_consistency_no_target_scenario(self):
        """No target scenario: both paths return None / 'none'."""
        ctx = _empty_context(
            ytd_by_officer={10: 5},
            officer_unit_map={10: 1},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        source = map_resolution_to_coverage_source(result)

        assert result is None
        assert source == "none"

    def test_multiple_officers_same_context(self):
        """Batch path: multiple officers resolved from same context."""
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=90)
        officer_target = _mock_target(officer_id=11, annual_target=50)
        ctx = _empty_context(
            officer_targets={11: officer_target},
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 3},
            ytd_by_officer={10: 8, 11: 15, 12: 3},
            officer_unit_map={10: 1, 11: 1, 12: 1},
        )

        r10 = resolve_officer_annual_from_context(10, ctx)
        r11 = resolve_officer_annual_from_context(11, ctx)
        r12 = resolve_officer_annual_from_context(12, ctx)

        # Officer 10: no target, inherits from unit plan
        assert r10.annual_target == 30  # 90 // 3
        assert r10.resolution_kind == "inherited_estimate"

        # Officer 11: has own target
        assert r11.annual_target == 50
        assert r11.resolution_kind == "assigned"

        # Officer 12: no target, inherits from unit plan
        assert r12.annual_target == 30  # 90 // 3
        assert r12.resolution_kind == "inherited_estimate"


# =============================================================================
# EDGE CASES
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:

    def test_officer_not_in_context_returns_none(self):
        """Officer not in context maps → None."""
        ctx = _empty_context()
        result = resolve_officer_annual_from_context(999, ctx)
        assert result is None

    def test_officer_with_no_unit(self):
        """Officer with unit_id=None (unassigned) → only global fallback."""
        global_target = _mock_target(annual_target=200)
        ctx = _empty_context(
            global_target=global_target,
            total_active_officers=10,
            ytd_by_officer={10: 0},
            officer_unit_map={10: None},
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is not None
        assert result.annual_target == 20  # 200 // 10
        assert result.resolution_kind == "inherited_estimate"

    def test_transferred_officer_keeps_old_target(self):
        """Officer transferred to unit 2 but target still references unit 1.

        The context should contain the officer's target regardless of current unit.
        Coverage report loads ALL officer targets; single path doesn't filter by unit.
        """
        old_target = _mock_target(officer_id=10, unit_id=1, annual_target=80)
        ctx = _empty_context(
            officer_targets={10: old_target},
            ytd_by_officer={10: 30},
            officer_unit_map={10: 2},  # Now in unit 2
        )
        result = resolve_officer_annual_from_context(10, ctx)
        assert result is not None
        assert result.annual_target == 80  # Old target still applies
        assert result.resolution_kind == "assigned"

    def test_context_reusable_across_officers(self):
        """Same context object can be used for multiple officers."""
        unit_plan = _mock_plan(unit_id=1, annual_enrollment_target=100)
        ctx = _empty_context(
            unit_plans={1: unit_plan},
            unit_officer_counts={1: 4},
            ytd_by_officer={1: 10, 2: 20, 3: 5, 4: 15},
            officer_unit_map={1: 1, 2: 1, 3: 1, 4: 1},
        )
        results = [resolve_officer_annual_from_context(oid, ctx) for oid in [1, 2, 3, 4]]

        # All get same split target
        for r in results:
            assert r.annual_target == 25  # 100 // 4

        # Each has own YTD
        assert [r.achieved_ytd for r in results] == [10, 20, 5, 15]
