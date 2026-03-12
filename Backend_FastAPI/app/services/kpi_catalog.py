# app/services/kpi_catalog.py
"""
KPI Canonical Catalog — Single Source of Truth for metric metadata.

Replaces scattered constants:
- DEFAULT_KPIS, KPI_PERIOD_MAP (kpi_service.py)
- KPI_SYNC_MAPPING (kpi_planning_service.py)

Each MetricDefinition encodes: identity, defaults, planning linkage,
comparison policy, and context-specific display aliases.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


# =============================================================================
# ENUMS
# =============================================================================


class ActualKind(str, Enum):
    """How the dashboard computes the actual value for this metric."""

    activity_count = "activity_count"   # Count of events in period
    activity_rate = "activity_rate"     # Ratio computed from events in period
    activity_avg = "activity_avg"       # Average computed from events in period
    cohort_rate = "cohort_rate"         # Ratio of cohort created in period → later outcome
    ytd_count = "ytd_count"            # Year-to-date cumulative count


# =============================================================================
# COMPARISON POLICY
# =============================================================================


@dataclass(frozen=True)
class ComparisonPolicy:
    """
    Encodes when it is valid to display target alongside actual on a dashboard card.

    This is a *necessary* condition, not sufficient. Individual cards may apply
    additional variant logic (e.g. consultations_daily card gates on todayInRange).
    """

    comparable: bool
    """Can this metric's actual be meaningfully compared to its target?"""

    requires_period_match: bool
    """Only valid when the dashboard period matches target_period?"""

    target_period: Optional[str]
    """'daily' | 'monthly' | 'annual' — the period the target is defined for."""

    caveat: Optional[str]
    """Warning text for edge cases. None if no caveats."""


# =============================================================================
# METRIC DEFINITION
# =============================================================================


@dataclass(frozen=True)
class MetricDefinition:
    """Canonical definition of a single KPI metric."""

    code: str
    display_name: str
    unit: Literal["count", "percent", "hours"]
    period_type: Literal["daily", "monthly", "annual"]
    default_value: float
    higher_is_better: bool

    # Planning linkage
    plan_field: Optional[str]
    """Field name on KpiPlanMonth (or KpiPlan for plan-level metrics). None for KpiTarget-only."""

    config_source: Literal["month", "plan", "target"]
    """Where sync_plan_to_kpi_config reads the value: 'month'=KpiPlanMonth, 'plan'=KpiPlan, 'target'=KpiTarget."""

    actual_kind: ActualKind
    comparison: ComparisonPolicy

    display_aliases: Dict[str, str]
    """Context-specific Vietnamese display names: dashboard, planning, config, annual_progress."""


# =============================================================================
# THE CATALOG — 8 canonical metrics
# =============================================================================

METRIC_CATALOG: Dict[str, MetricDefinition] = {
    "consultations_daily": MetricDefinition(
        code="consultations_daily",
        display_name="Tư vấn/ngày",
        unit="count",
        period_type="daily",
        default_value=10,
        higher_is_better=True,
        plan_field="consultations_daily",
        config_source="month",
        actual_kind=ActualKind.activity_count,
        comparison=ComparisonPolicy(
            comparable=True,
            requires_period_match=False,
            target_period="daily",
            caveat=None,
        ),
        display_aliases={
            "dashboard": "Tư vấn hôm nay",
            "planning": "Tư vấn/ngày",
            "config": "Tư vấn (Ngày)",
            "annual_progress": "Tư vấn ngày",
        },
    ),
    "conversion_rate": MetricDefinition(
        code="conversion_rate",
        display_name="Tỷ lệ chuyển đổi",
        unit="percent",
        period_type="monthly",
        default_value=15,
        higher_is_better=True,
        plan_field="conversion_rate",
        config_source="month",
        actual_kind=ActualKind.cohort_rate,
        comparison=ComparisonPolicy(
            comparable=False,
            requires_period_match=False,
            target_period=None,
            caveat="Target = funnel-derived (M_t/L_t). Actual = cohort-based. Different grain.",
        ),
        display_aliases={
            "dashboard": "Chuyển đổi lead mới",
            "planning": "Tỷ lệ chuyển đổi",
            "config": "TL chuyển đổi Lead mới (%)",
            "annual_progress": "TL chuyển đổi Lead mới",
        },
    ),
    "win_rate": MetricDefinition(
        code="win_rate",
        display_name="Tỷ lệ chốt đơn",
        unit="percent",
        period_type="monthly",
        default_value=33,
        higher_is_better=True,
        plan_field="win_rate",
        config_source="month",
        actual_kind=ActualKind.activity_rate,
        comparison=ComparisonPolicy(
            comparable=True,
            requires_period_match=True,
            target_period="monthly",
            caveat=(
                "Dashboard denominator = won+lost (excludes neutral final). "
                "Planning snapshot denominator = all is_final_stage leads. "
                "If neutral final stages exist, denominators differ."
            ),
        ),
        display_aliases={
            "dashboard": "Tỉ lệ chốt đơn",
            "planning": "Tỷ lệ thắng",
            "config": "Tỉ lệ chốt đơn (%)",
            "annual_progress": "Tỉ lệ chốt đơn",
        },
    ),
    "response_time_hours": MetricDefinition(
        code="response_time_hours",
        display_name="Thời gian phản hồi",
        unit="hours",
        period_type="daily",
        default_value=2,
        higher_is_better=False,
        plan_field="response_time_target",
        config_source="plan",
        actual_kind=ActualKind.activity_avg,
        comparison=ComparisonPolicy(
            comparable=True,
            requires_period_match=False,
            target_period="daily",
            caveat=None,
        ),
        display_aliases={
            "dashboard": "Thời gian phản hồi",
            "planning": "Thời gian phản hồi",
            "config": "Thời gian phản hồi (giờ)",
            "annual_progress": "Thời gian phản hồi",
        },
    ),
    "enrollments_monthly": MetricDefinition(
        code="enrollments_monthly",
        display_name="Nhập học tháng",
        unit="count",
        period_type="monthly",
        default_value=7,
        higher_is_better=True,
        plan_field="enrollment_target",
        config_source="month",
        actual_kind=ActualKind.activity_count,
        comparison=ComparisonPolicy(
            comparable=True,
            requires_period_match=True,
            target_period="monthly",
            caveat=(
                "Dashboard default 7d shows period count, not monthly count. "
                "Only compare when period = calendar month."
            ),
        ),
        display_aliases={
            "dashboard": "Nhập học",
            "planning": "Chỉ tiêu nhập học",
            "config": "Nhập học (Tháng)",
            "annual_progress": "Nhập học tháng",
        },
    ),
    "enrollments_annual": MetricDefinition(
        code="enrollments_annual",
        display_name="Nhập học năm",
        unit="count",
        period_type="annual",
        default_value=80,
        higher_is_better=True,
        plan_field="annual_enrollment_target",
        config_source="target",
        actual_kind=ActualKind.ytd_count,
        comparison=ComparisonPolicy(
            comparable=True,
            requires_period_match=False,
            target_period="annual",
            caveat=None,
        ),
        display_aliases={
            "dashboard": "Nhập học năm",
            "planning": "Chỉ tiêu nhập học năm",
            "config": "Nhập học (Năm)",
            "annual_progress": "Nhập học năm",
        },
    ),
    "sla_compliance_rate": MetricDefinition(
        code="sla_compliance_rate",
        display_name="SLA tuân thủ",
        unit="percent",
        period_type="monthly",
        default_value=80,
        higher_is_better=True,
        plan_field="sla_target",
        config_source="plan",
        actual_kind=ActualKind.activity_rate,
        comparison=ComparisonPolicy(
            comparable=True,
            requires_period_match=False,
            target_period="monthly",
            caveat=None,
        ),
        display_aliases={
            "dashboard": "SLA tuân thủ",
            "planning": "SLA",
            "config": "SLA tuân thủ (%)",
            "annual_progress": "SLA tuân thủ",
        },
    ),
    "consultation_effectiveness": MetricDefinition(
        code="consultation_effectiveness",
        display_name="Hiệu quả tư vấn",
        unit="percent",
        period_type="monthly",
        default_value=50,
        higher_is_better=True,
        plan_field="consultation_effectiveness",
        config_source="month",
        actual_kind=ActualKind.activity_rate,
        comparison=ComparisonPolicy(
            comparable=False,
            requires_period_match=False,
            target_period=None,
            caveat=(
                "Target = funnel-derived with 50% floor. "
                "Actual = activity-based latest-transition. Different grain."
            ),
        ),
        display_aliases={
            "dashboard": "Hiệu quả tư vấn",
            "planning": "Hiệu quả tư vấn",
            "config": "Hiệu quả tư vấn (%)",
            "annual_progress": "Hiệu quả tư vấn",
        },
    ),
}


# =============================================================================
# DERIVED ACCESSORS — replace scattered constants in other modules
# =============================================================================


def get_default(kpi_code: str) -> float:
    """Get default target value for a single metric. Returns 0 if unknown code."""
    m = METRIC_CATALOG.get(kpi_code)
    return m.default_value if m else 0


def get_default_kpis() -> Dict[str, float]:
    """Replaces DEFAULT_KPIS dict in kpi_service.py."""
    return {m.code: m.default_value for m in METRIC_CATALOG.values()}


def get_period_type(kpi_code: str) -> str:
    """Get period_type for a metric. Falls back to 'monthly' for unknown codes."""
    m = METRIC_CATALOG.get(kpi_code)
    return m.period_type if m else "monthly"


def get_period_map() -> Dict[str, str]:
    """Replaces KPI_PERIOD_MAP dict in kpi_service.py."""
    return {m.code: m.period_type for m in METRIC_CATALOG.values()}


def get_sync_mapping() -> List[Dict[str, str]]:
    """
    Replaces KPI_SYNC_MAPPING in kpi_planning_service.py.

    Returns list of dicts with: kpi_code, period_type, source, field.
    Only includes metrics with config_source != 'target' (target-only metrics
    like enrollments_annual are synced via KpiTarget, not KpiConfig).
    """
    mapping = []
    for m in METRIC_CATALOG.values():
        if m.config_source == "target":
            continue  # enrollments_annual goes through KpiTarget, not KpiConfig
        mapping.append({
            "kpi_code": m.code,
            "period_type": m.period_type,
            "source": m.config_source,
            "field": m.plan_field,
        })
    return mapping


def get_catalog_api_response() -> List[Dict[str, Any]]:
    """Serializable response for GET /api/meta/kpi-catalog."""
    result = []
    for m in METRIC_CATALOG.values():
        result.append({
            "code": m.code,
            "display_name": m.display_name,
            "unit": m.unit,
            "period_type": m.period_type,
            "default_value": m.default_value,
            "higher_is_better": m.higher_is_better,
            "actual_kind": m.actual_kind.value,
            "comparison": {
                "comparable": m.comparison.comparable,
                "requires_period_match": m.comparison.requires_period_match,
                "target_period": m.comparison.target_period,
                "caveat": m.comparison.caveat,
            },
            "display_aliases": m.display_aliases,
        })
    return result


def validate_kpi_code(kpi_code: str) -> bool:
    """Check if a kpi_code is a known canonical metric."""
    return kpi_code in METRIC_CATALOG
