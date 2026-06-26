import { api } from "./client";
import { filenameFromDisposition } from "@/lib/utils/download-blob";
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

export interface ExportedFile {
  blob: Blob;
  filename: string;
}

/**
 * Xuất báo cáo tuyển sinh (snapshot) ra Excel — số liệu CẢ NĂM tại thời điểm bấm.
 * Trả {blob, filename} (giữ tên có timestamp do backend đặt, tránh ghi đè file cũ);
 * scope theo vai trò ở backend (admin toàn trường / manager đơn vị).
 */
export async function exportAdmissionSummary(
  academic_year: number,
  unit_id?: number,
): Promise<ExportedFile> {
  const response = await api.get(
    "/api/v2/admin/reports/admission-summary/export.xlsx",
    {
      params: { academic_year, ...(unit_id ? { unit_id } : {}) },
      responseType: "blob",
    },
  );
  return {
    blob: response.data,
    filename: filenameFromDisposition(
      response.headers["content-disposition"],
      `bao_cao_tuyen_sinh_${academic_year}.xlsx`,
    ),
  };
}
