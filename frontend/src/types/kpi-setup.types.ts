// types/kpi-setup.types.ts
// Mirrors backend schemas/kpi_setup.py 1:1

export interface HolidayStatusCoverage {
  total_holidays: number;
  is_complete: boolean;
  reason_code: string | null; // "missing_holiday" | null
}

export interface OfficerCoverage {
  officer_id: number;
  officer_name: string;
  target_source: "custom" | "inherited" | "inherited_global" | "none";
  target_id: number | null;
  annual_target: number;
  achieved_ytd: number;
  progress_pct: number;
  status: "in_progress" | "completed" | "at_risk" | "overdue" | "not_started";
}

export interface UnitCoverage {
  unit_id: number;
  unit_name: string;
  plan_id: number | null;
  plan_status: string | null; // "active" | null
  annual_target: number | null;
  officers: OfficerCoverage[];
  total_officer_target: number;
  target_gap: number;
}

export interface CoverageWarning {
  reason_code: string;
  action_hint: string;
  section: number; // 0-3
  detail: string;
  entity_id: number | null;
}

export interface CoverageSummary {
  total_units: number;
  units_with_plan: number;
  total_officers: number;
  officers_with_target: number;
  total_annual_target: number;
  total_achieved_ytd: number;
  progress_pct: number;
}

export interface CoverageReport {
  fiscal_year: number;
  holiday_status: HolidayStatusCoverage;
  units: UnitCoverage[];
  warnings: CoverageWarning[];
  summary: CoverageSummary;
}

export const REASON_CODES = {
  MISSING_HOLIDAY: "missing_holiday",
  MISSING_UNIT_PLAN: "missing_unit_plan",
  OFFICER_NO_TARGET: "officer_no_target",
  OFFICER_TARGET_MISMATCH: "officer_target_mismatch",
  STALE_SYNC: "stale_sync",
} as const;

export const ACTION_HINTS = {
  SEED_HOLIDAYS: "seed_holidays",
  CREATE_PLAN: "create_plan",
  ASSIGN_TARGET: "assign_target",
  REVIEW_TARGETS: "review_targets",
  SYNC_YTD: "sync_ytd",
} as const;

export const STATUS_CONFIG: Record<
  OfficerCoverage["status"],
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  completed: { label: "Hoàn thành", variant: "default" },
  in_progress: { label: "Đang thực hiện", variant: "secondary" },
  at_risk: { label: "Có nguy cơ", variant: "destructive" },
  overdue: { label: "Quá hạn", variant: "destructive" },
  not_started: { label: "Chưa bắt đầu", variant: "outline" },
};

export const TARGET_SOURCE_CONFIG: Record<
  OfficerCoverage["target_source"],
  { label: string; variant: "default" | "secondary" | "destructive" | "outline"; tooltip?: string }
> = {
  custom: { label: "Tùy chỉnh", variant: "default" },
  inherited: { label: "Kế thừa (đơn vị)", variant: "secondary", tooltip: "Tính từ chỉ tiêu đơn vị ÷ số cán bộ" },
  inherited_global: { label: "Kế thừa (toàn trường)", variant: "outline", tooltip: "Từ chỉ tiêu mặc định toàn trường" },
  none: { label: "Chưa có", variant: "destructive" },
};
