// src/lib/hooks/use-kpi-catalog.ts
"use client";

import { useQuery } from "@tanstack/react-query";
import { metaApi, type MetricCatalogEntry } from "../api/meta";

// =============================================================================
// LOCAL FALLBACK — prevents blank UI if /api/meta/kpi-catalog is unreachable
// Must stay in sync with backend kpi_catalog.py METRIC_CATALOG
// =============================================================================

const LOCAL_FALLBACK: MetricCatalogEntry[] = [
  {
    code: "consultations_daily",
    display_name: "Tư vấn/ngày",
    unit: "count",
    period_type: "daily",
    default_value: 10,
    higher_is_better: true,
    actual_kind: "activity_count",
    comparison: { comparable: true, requires_period_match: false, target_period: "daily", caveat: null },
    display_aliases: { dashboard: "Tư vấn hôm nay", planning: "Tư vấn/ngày", config: "Tư vấn (Ngày)", annual_progress: "Tư vấn ngày" },
  },
  {
    code: "conversion_rate",
    display_name: "Tỷ lệ chuyển đổi",
    unit: "percent",
    period_type: "monthly",
    default_value: 15,
    higher_is_better: true,
    actual_kind: "cohort_rate",
    comparison: { comparable: false, requires_period_match: false, target_period: null, caveat: "Target = funnel-derived (M_t/L_t). Actual = cohort-based. Different grain." },
    display_aliases: { dashboard: "Chuyển đổi lead mới", planning: "Tỷ lệ chuyển đổi", config: "TL chuyển đổi Lead mới (%)", annual_progress: "TL chuyển đổi Lead mới" },
  },
  {
    code: "win_rate",
    display_name: "Tỷ lệ chốt đơn",
    unit: "percent",
    period_type: "monthly",
    default_value: 33,
    higher_is_better: true,
    actual_kind: "activity_rate",
    comparison: { comparable: true, requires_period_match: true, target_period: "monthly", caveat: "Dashboard denominator = won+lost (excludes neutral final). Planning snapshot denominator = all is_final_stage leads. If neutral final stages exist, denominators differ." },
    display_aliases: { dashboard: "Tỉ lệ chốt đơn", planning: "Tỷ lệ thắng", config: "Tỉ lệ chốt đơn (%)", annual_progress: "Tỉ lệ chốt đơn" },
  },
  {
    code: "response_time_hours",
    display_name: "Thời gian phản hồi",
    unit: "hours",
    period_type: "daily",
    default_value: 2,
    higher_is_better: false,
    actual_kind: "activity_avg",
    comparison: { comparable: true, requires_period_match: false, target_period: "daily", caveat: null },
    display_aliases: { dashboard: "Thời gian phản hồi", planning: "Thời gian phản hồi", config: "Thời gian phản hồi (giờ)", annual_progress: "Thời gian phản hồi" },
  },
  {
    code: "enrollments_monthly",
    display_name: "Nhập học tháng",
    unit: "count",
    period_type: "monthly",
    default_value: 7,
    higher_is_better: true,
    actual_kind: "activity_count",
    comparison: { comparable: true, requires_period_match: true, target_period: "monthly", caveat: "Dashboard default 7d shows period count, not monthly count. Only compare when period = calendar month." },
    display_aliases: { dashboard: "Nhập học", planning: "Chỉ tiêu nhập học", config: "Nhập học (Tháng)", annual_progress: "Nhập học tháng" },
  },
  {
    code: "enrollments_annual",
    display_name: "Nhập học năm",
    unit: "count",
    period_type: "annual",
    default_value: 80,
    higher_is_better: true,
    actual_kind: "ytd_count",
    comparison: { comparable: true, requires_period_match: false, target_period: "annual", caveat: null },
    display_aliases: { dashboard: "Nhập học năm", planning: "Chỉ tiêu nhập học năm", config: "Nhập học (Năm)", annual_progress: "Nhập học năm" },
  },
  {
    code: "sla_compliance_rate",
    display_name: "SLA tuân thủ",
    unit: "percent",
    period_type: "monthly",
    default_value: 80,
    higher_is_better: true,
    actual_kind: "activity_rate",
    comparison: { comparable: true, requires_period_match: false, target_period: "monthly", caveat: null },
    display_aliases: { dashboard: "SLA tuân thủ", planning: "SLA", config: "SLA tuân thủ (%)", annual_progress: "SLA tuân thủ" },
  },
  {
    code: "consultation_effectiveness",
    display_name: "Hiệu quả tư vấn",
    unit: "percent",
    period_type: "monthly",
    default_value: 50,
    higher_is_better: true,
    actual_kind: "activity_rate",
    comparison: { comparable: false, requires_period_match: false, target_period: null, caveat: "Target = funnel-derived with 50% floor. Actual = activity-based latest-transition. Different grain." },
    display_aliases: { dashboard: "Hiệu quả tư vấn", planning: "Hiệu quả tư vấn", config: "Hiệu quả tư vấn (%)", annual_progress: "Hiệu quả tư vấn" },
  },
];

// =============================================================================
// QUERY KEY & HOOK
// =============================================================================

export const kpiCatalogQueryKeys = {
  catalog: ["meta", "kpi-catalog"] as const,
};

export function useKpiCatalog() {
  const query = useQuery<MetricCatalogEntry[]>({
    queryKey: kpiCatalogQueryKeys.catalog,
    queryFn: () => metaApi.getKpiCatalog(),
    staleTime: Infinity,
    gcTime: Infinity,
    placeholderData: LOCAL_FALLBACK,
  });

  const catalog = query.data ?? LOCAL_FALLBACK;
  const catalogMap = new Map(catalog.map((m) => [m.code, m]));

  return {
    ...query,
    catalog,
    catalogMap,

    getDisplayName(code: string, context: keyof MetricCatalogEntry["display_aliases"] = "dashboard"): string {
      return catalogMap.get(code)?.display_aliases[context] ?? code;
    },

    getUnit(code: string): string {
      return catalogMap.get(code)?.unit ?? "count";
    },

    getComparison(code: string) {
      return catalogMap.get(code)?.comparison ?? { comparable: false, requires_period_match: false, target_period: null, caveat: null };
    },

    getKpiOptions(): { value: string; label: string }[] {
      return catalog.map((m) => ({ value: m.code, label: m.display_aliases.config }));
    },

    /**
     * Necessary condition for showing target alongside actual.
     * Cards may apply additional variant logic on top (e.g. todayInRange).
     */
    canShowTarget(code: string, dashboardRange?: { start: Date; end: Date }): boolean {
      const entry = catalogMap.get(code);
      if (!entry) return false;
      const { comparison } = entry;
      if (!comparison.comparable) return false;
      if (!comparison.requires_period_match) return true;
      if (!dashboardRange) return false;
      if (comparison.target_period === "monthly") {
        return isCalendarMonth(dashboardRange);
      }
      if (comparison.target_period === "annual") return true;
      return false;
    },
  };
}

// =============================================================================
// UTILITIES
// =============================================================================

/** Check if a date range covers exactly one calendar month */
function isCalendarMonth(range: { start: Date; end: Date }): boolean {
  const s = range.start;
  const e = range.end;
  if (s.getFullYear() !== e.getFullYear() || s.getMonth() !== e.getMonth()) return false;
  if (s.getDate() !== 1) return false;
  const lastDay = new Date(s.getFullYear(), s.getMonth() + 1, 0).getDate();
  return e.getDate() === lastDay;
}

