# tests/unit/test_kpi_catalog.py
"""
Unit tests for kpi_catalog.py — canonical KPI metadata.

Pure-Python tests (no DB, no async). Validates catalog invariants
that prevent vocabulary drift across bounded contexts.
"""
import pytest

from app.services.kpi_catalog import (
    METRIC_CATALOG,
    ActualKind,
    ComparisonPolicy,
    MetricDefinition,
    get_catalog_api_response,
    get_default,
    get_default_kpis,
    get_period_map,
    get_period_type,
    get_sync_mapping,
    validate_kpi_code,
)

# The 8 canonical metric codes
EXPECTED_CODES = {
    "consultations_daily",
    "conversion_rate",
    "win_rate",
    "response_time_hours",
    "enrollments_monthly",
    "enrollments_annual",
    "sla_compliance_rate",
    "consultation_effectiveness",
}


@pytest.mark.unit
class TestMetricCatalog:
    """Core catalog invariants."""

    def test_catalog_has_exactly_8_metrics(self):
        assert len(METRIC_CATALOG) == 8

    def test_catalog_codes_match_expected(self):
        assert set(METRIC_CATALOG.keys()) == EXPECTED_CODES

    def test_all_codes_unique(self):
        codes = [m.code for m in METRIC_CATALOG.values()]
        assert len(codes) == len(set(codes))

    def test_code_matches_dict_key(self):
        for key, metric in METRIC_CATALOG.items():
            assert key == metric.code, f"Key '{key}' != metric.code '{metric.code}'"

    def test_all_metrics_are_metric_definitions(self):
        for m in METRIC_CATALOG.values():
            assert isinstance(m, MetricDefinition)

    def test_period_types_valid(self):
        valid = {"daily", "monthly", "annual"}
        for m in METRIC_CATALOG.values():
            assert m.period_type in valid, f"{m.code} has invalid period_type '{m.period_type}'"

    def test_units_valid(self):
        valid = {"count", "percent", "hours"}
        for m in METRIC_CATALOG.values():
            assert m.unit in valid, f"{m.code} has invalid unit '{m.unit}'"

    def test_config_sources_valid(self):
        valid = {"month", "plan", "target"}
        for m in METRIC_CATALOG.values():
            assert m.config_source in valid, f"{m.code} has invalid config_source '{m.config_source}'"

    def test_actual_kind_is_enum(self):
        for m in METRIC_CATALOG.values():
            assert isinstance(m.actual_kind, ActualKind), f"{m.code} actual_kind is not ActualKind"

    def test_comparison_policy_shape(self):
        for m in METRIC_CATALOG.values():
            cp = m.comparison
            assert isinstance(cp, ComparisonPolicy), f"{m.code} comparison is not ComparisonPolicy"
            assert isinstance(cp.comparable, bool)
            assert isinstance(cp.requires_period_match, bool)
            assert cp.target_period in (None, "daily", "monthly", "annual")
            assert cp.caveat is None or isinstance(cp.caveat, str)

    def test_display_aliases_has_all_contexts(self):
        required_contexts = {"dashboard", "planning", "config", "annual_progress"}
        for m in METRIC_CATALOG.values():
            assert set(m.display_aliases.keys()) == required_contexts, (
                f"{m.code} display_aliases missing contexts: "
                f"{required_contexts - set(m.display_aliases.keys())}"
            )

    def test_display_aliases_not_empty(self):
        for m in METRIC_CATALOG.values():
            for ctx, label in m.display_aliases.items():
                assert label and len(label.strip()) > 0, (
                    f"{m.code} display_aliases['{ctx}'] is empty"
                )

    def test_default_values_positive(self):
        for m in METRIC_CATALOG.values():
            assert m.default_value > 0, f"{m.code} default_value should be positive"

    def test_higher_is_better_correct_for_response_time(self):
        rt = METRIC_CATALOG["response_time_hours"]
        assert rt.higher_is_better is False

    def test_higher_is_better_true_for_others(self):
        for code, m in METRIC_CATALOG.items():
            if code != "response_time_hours":
                assert m.higher_is_better is True, f"{code} should have higher_is_better=True"


@pytest.mark.unit
class TestDerivedAccessors:
    """Tests for catalog accessor functions."""

    def test_get_default_kpis_returns_all_8(self):
        defaults = get_default_kpis()
        assert len(defaults) == 8
        assert set(defaults.keys()) == EXPECTED_CODES

    def test_get_default_kpis_values_match_catalog(self):
        defaults = get_default_kpis()
        for code, val in defaults.items():
            assert val == METRIC_CATALOG[code].default_value

    def test_get_default_known_code(self):
        assert get_default("consultations_daily") == 10

    def test_get_default_unknown_code(self):
        assert get_default("nonexistent_metric") == 0

    def test_get_period_map_returns_all_8(self):
        pm = get_period_map()
        assert len(pm) == 8
        assert set(pm.keys()) == EXPECTED_CODES

    def test_get_period_map_values_match_catalog(self):
        pm = get_period_map()
        for code, pt in pm.items():
            assert pt == METRIC_CATALOG[code].period_type

    def test_get_period_type_known_code(self):
        assert get_period_type("consultations_daily") == "daily"
        assert get_period_type("enrollments_annual") == "annual"
        assert get_period_type("win_rate") == "monthly"

    def test_get_period_type_unknown_falls_back_to_monthly(self):
        assert get_period_type("unknown_code") == "monthly"

    def test_validate_kpi_code(self):
        for code in EXPECTED_CODES:
            assert validate_kpi_code(code) is True
        assert validate_kpi_code("nonexistent") is False


@pytest.mark.unit
class TestSyncMapping:
    """Tests for get_sync_mapping() — replaces old KPI_SYNC_MAPPING."""

    def test_sync_mapping_has_7_entries(self):
        """enrollments_annual (config_source=target) must be excluded."""
        mapping = get_sync_mapping()
        assert len(mapping) == 7

    def test_sync_mapping_excludes_target_source(self):
        mapping = get_sync_mapping()
        codes_in_mapping = {m["kpi_code"] for m in mapping}
        assert "enrollments_annual" not in codes_in_mapping

    def test_sync_mapping_includes_all_non_target(self):
        mapping = get_sync_mapping()
        codes = {m["kpi_code"] for m in mapping}
        expected = EXPECTED_CODES - {"enrollments_annual"}
        assert codes == expected

    def test_sync_mapping_fields_match_catalog(self):
        mapping = get_sync_mapping()
        for entry in mapping:
            code = entry["kpi_code"]
            m = METRIC_CATALOG[code]
            assert entry["period_type"] == m.period_type
            assert entry["source"] == m.config_source
            assert entry["field"] == m.plan_field

    def test_sync_mapping_exact_records(self):
        """Verify exact field values match old hardcoded KPI_SYNC_MAPPING."""
        mapping = get_sync_mapping()
        by_code = {m["kpi_code"]: m for m in mapping}

        assert by_code["consultations_daily"] == {
            "kpi_code": "consultations_daily", "period_type": "daily",
            "source": "month", "field": "consultations_daily",
        }
        assert by_code["sla_compliance_rate"] == {
            "kpi_code": "sla_compliance_rate", "period_type": "monthly",
            "source": "plan", "field": "sla_target",
        }
        assert by_code["response_time_hours"] == {
            "kpi_code": "response_time_hours", "period_type": "daily",
            "source": "plan", "field": "response_time_target",
        }
        assert by_code["enrollments_monthly"] == {
            "kpi_code": "enrollments_monthly", "period_type": "monthly",
            "source": "month", "field": "enrollment_target",
        }


@pytest.mark.unit
class TestCatalogApiResponse:
    """Tests for get_catalog_api_response() — the meta API payload."""

    def test_response_has_8_entries(self):
        resp = get_catalog_api_response()
        assert len(resp) == 8

    def test_response_shape(self):
        resp = get_catalog_api_response()
        required_keys = {
            "code", "display_name", "unit", "period_type",
            "default_value", "higher_is_better", "actual_kind",
            "comparison", "display_aliases",
        }
        for entry in resp:
            assert set(entry.keys()) == required_keys, (
                f"Entry '{entry.get('code')}' has wrong keys: {set(entry.keys())}"
            )

    def test_response_comparison_shape(self):
        resp = get_catalog_api_response()
        for entry in resp:
            comp = entry["comparison"]
            assert set(comp.keys()) == {
                "comparable", "requires_period_match", "target_period", "caveat",
            }

    def test_response_display_aliases_shape(self):
        resp = get_catalog_api_response()
        for entry in resp:
            assert set(entry["display_aliases"].keys()) == {
                "dashboard", "planning", "config", "annual_progress",
            }

    def test_response_values_match_catalog(self):
        resp = get_catalog_api_response()
        for entry in resp:
            m = METRIC_CATALOG[entry["code"]]
            assert entry["display_name"] == m.display_name
            assert entry["unit"] == m.unit
            assert entry["period_type"] == m.period_type
            assert entry["default_value"] == m.default_value
            assert entry["higher_is_better"] == m.higher_is_better
            assert entry["actual_kind"] == m.actual_kind.value
            assert entry["comparison"]["comparable"] == m.comparison.comparable
            assert entry["display_aliases"] == m.display_aliases

    def test_response_does_not_expose_internal_fields(self):
        """plan_field and config_source are backend-internal."""
        resp = get_catalog_api_response()
        for entry in resp:
            assert "plan_field" not in entry
            assert "config_source" not in entry


@pytest.mark.unit
class TestComparisonPolicyInvariants:
    """Policy rules that must hold across all metrics."""

    def test_non_comparable_has_no_period_match_requirement(self):
        for m in METRIC_CATALOG.values():
            if not m.comparison.comparable:
                assert not m.comparison.requires_period_match, (
                    f"{m.code}: non-comparable should not require period match"
                )

    def test_non_comparable_has_caveat(self):
        for m in METRIC_CATALOG.values():
            if not m.comparison.comparable:
                assert m.comparison.caveat is not None, (
                    f"{m.code}: non-comparable should explain why via caveat"
                )

    def test_consultations_daily_does_not_require_period_match(self):
        """Card uses todayInRange variant logic, catalog must not gate on period."""
        cd = METRIC_CATALOG["consultations_daily"]
        assert cd.comparison.comparable is True
        assert cd.comparison.requires_period_match is False

    def test_enrollments_monthly_requires_period_match(self):
        em = METRIC_CATALOG["enrollments_monthly"]
        assert em.comparison.comparable is True
        assert em.comparison.requires_period_match is True
        assert em.comparison.target_period == "monthly"
