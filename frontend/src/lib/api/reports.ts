import { api } from "./client";
import {
  admissionWeeklyReportSchema,
  reportFiltersSchema,
  type AdmissionWeeklyReport,
  type ReportFilters,
  type ReportGroupBy,
} from "@/lib/zod/reports";

export interface WeeklyReportParams {
  academic_year: number;
  group_by: ReportGroupBy;
  round_code?: string;
  week_start?: string; // YYYY-MM-DD; omit = current week (BE picks)
  officer_id?: number;
  unit_id?: number;
}

export async function getAdmissionWeeklyReport(
  params: WeeklyReportParams,
): Promise<AdmissionWeeklyReport> {
  const response = await api.get("/api/v2/admin/reports/admission-weekly", {
    params,
  });
  // Runtime-validate the contract (throws on drift) instead of trusting the cast.
  return admissionWeeklyReportSchema.parse(response.data);
}

/**
 * Filter options (năm + đợt) for the report controls. Admin + manager (same gate
 * as the report) — replaces the admin-only rounds endpoint + profile-only years.
 */
export async function getReportFilters(
  academic_year?: number,
): Promise<ReportFilters> {
  const response = await api.get(
    "/api/v2/admin/reports/admission-weekly/filters",
    { params: academic_year !== undefined ? { academic_year } : undefined },
  );
  return reportFiltersSchema.parse(response.data);
}
