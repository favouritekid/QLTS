// src/types/kpi-planning.types.ts
// TypeScript types for KPI Planning — mirrors backend Pydantic schemas

export interface KpiPlanMonth {
  id: number;
  month: number;
  enrollment_target: number;
  working_days: number;
  weight: number;
  k_factor: number;
  lead_forecast: number | null;
  close_forecast: number | null;
  consultations_daily: number | null;
  conversion_rate: number | null;
  win_rate: number | null;
  consultation_effectiveness: number | null;
  overridden_fields: Record<string, boolean>;
  override_reason: string | null;
  overridden_by: number | null;
  overridden_at: string | null;
  actual_enrollments: number | null;
  actual_consultations_avg: number | null;
  actual_conversion_rate: number | null;
  actual_win_rate: number | null;
  actual_consultation_effectiveness: number | null;
  actual_sla_compliance_rate: number | null;
}

export interface KpiPlan {
  id: number;
  unit_id: number;
  officer_id: number | null;
  fiscal_year: number;
  annual_enrollment_target: number;
  sla_target: number;
  response_time_target: number;
  seasonal_weights: number[] | null;
  is_active: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  months: KpiPlanMonth[];
}

export interface KpiPlanListResponse {
  items: KpiPlan[];
  total: number;
  skip: number;
  limit: number;
}

export interface KpiPlanCreate {
  unit_id: number;
  fiscal_year: number;
  annual_enrollment_target: number;
  sla_target?: number;
  response_time_target?: number;
  seasonal_weights?: number[] | null;
  officer_id?: number | null;
}

export interface KpiPlanUpdate {
  annual_enrollment_target?: number;
  sla_target?: number;
  response_time_target?: number;
  seasonal_weights?: number[];
}

export interface KpiPlanCloneRequest {
  fiscal_year: number;
}

export interface KpiPlanPreviewRequest {
  unit_id: number;
  fiscal_year: number;
  annual_enrollment_target: number;
  sla_target?: number;
  response_time_target?: number;
  seasonal_weights?: number[] | null;
  start_month?: number | null;
}

export interface PreviewMonth {
  month: number;
  enrollment_target: number;
  working_days: number;
  weight: number;
  k_factor: number;
  lead_forecast: number | null;
  close_forecast: number | null;
  consultations_daily: number | null;
  conversion_rate: number | null;
  win_rate: number | null;
  consultation_effectiveness: number | null;
}

export interface KpiPlanPreviewResponse {
  annual_enrollment_target: number;
  sla_target: number;
  response_time_target: number;
  months: PreviewMonth[];
  holiday_warning?: string | null;
}

export interface MonthOverrideRequest {
  overrides: Record<string, number>;
  reason: string;
}

export interface MonthResetRequest {
  fields: string[] | null;
}

export interface BatchOverrideRequest {
  month_ids: number[];
  overrides: Record<string, number>;
  reason: string;
}

export interface WorkingDaysOverrideRequest {
  working_days: number;
  reason: string;
}

export interface HolidayStatus {
  year: number;
  total_holidays: number;
  has_lunar_holidays: boolean;
  is_complete: boolean;
  warning: string | null;
}

export interface Holiday {
  id: number;
  date: string;
  name: string;
  year: number;
  is_recurring: boolean;
  created_by: number | null;
  created_at: string;
}

export interface HolidayCreate {
  date: string;
  name: string;
  is_recurring?: boolean;
}

export interface HolidayUpdate {
  date?: string;
  name?: string;
  is_recurring?: boolean;
}

export interface HolidayListResponse {
  items: Holiday[];
  total: number;
}

// =============================================================================
// OFFICER QUOTA ASSIGNMENT (V2)
// =============================================================================

export interface AssignOfficerQuotaRequest {
  unit_id: number;
  officer_id: number;
  fiscal_year: number;
  quota: number;
}

export interface QuotaSummary {
  unit_plan_target: number;
  officer_quota: number;
  other_officers_total: number;
  remaining_unassigned: number;
}

export interface AssignOfficerQuotaResponse {
  plan_id: number;
  target_id: number;
  quota_summary: QuotaSummary;
}

// Month labels in Vietnamese
export const MONTH_LABELS: Record<number, string> = {
  1: "T1", 2: "T2", 3: "T3", 4: "T4", 5: "T5", 6: "T6",
  7: "T7", 8: "T8", 9: "T9", 10: "T10", 11: "T11", 12: "T12",
};

// Default seasonal weights (mirrors backend DEFAULT_ENROLLMENT_WEIGHTS)
export const DEFAULT_SEASONAL_WEIGHTS: readonly number[] = [
  0.040, 0.033, 0.050, 0.060, 0.073, 0.127,
  0.153, 0.160, 0.133, 0.093, 0.043, 0.033,
];

// Even weights (equal distribution across 12 months)
export const EVEN_WEIGHTS: readonly number[] = Array.from({ length: 12 }, () => 1 / 12);

// High season weights (peak June-September)
export const HIGH_SEASON_WEIGHTS: readonly number[] = [
  0.040, 0.040, 0.050, 0.060, 0.080, 0.130,
  0.160, 0.160, 0.140, 0.080, 0.030, 0.030,
];

// Overridable derived fields
export const OVERRIDABLE_FIELDS = [
  "consultations_daily",
  "conversion_rate",
  "win_rate",
  "consultation_effectiveness",
] as const;

export type OverridableField = (typeof OVERRIDABLE_FIELDS)[number];

// KPI field display config
export const KPI_FIELD_CONFIG: Record<string, { label: string; unit: string; decimals: number }> = {
  enrollment_target: { label: "Chỉ tiêu nhập học", unit: "", decimals: 0 },
  working_days: { label: "Ngày làm việc", unit: "ngày", decimals: 0 },
  consultations_daily: { label: "Tư vấn/ngày", unit: "", decimals: 0 },
  conversion_rate: { label: "Tỷ lệ chuyển đổi", unit: "%", decimals: 2 },
  win_rate: { label: "Tỷ lệ thắng", unit: "%", decimals: 2 },
  consultation_effectiveness: { label: "Hiệu quả tư vấn", unit: "%", decimals: 2 },
  sla_compliance_rate: { label: "SLA", unit: "%", decimals: 2 },
  response_time_hours: { label: "Thời gian phản hồi", unit: "h", decimals: 1 },
};
