/**
 * Runtime contract for the weekly admission report
 * (GET /api/v2/admin/reports/admission-weekly).
 *
 * Backend Decimals arrive as JSON strings (precision-safe) → validate money as
 * `z.string()` and format with `formatVND`. Counts are integers.
 */
import { z } from "zod";

export const weekMetaSchema = z.object({
  iso_year: z.number().int(),
  iso_week: z.number().int(),
  week_start: z.string(), // YYYY-MM-DD (Monday, VN)
  week_end: z.string(), // YYYY-MM-DD (Sunday, VN)
  timezone: z.string(),
});

export const leadMetricsSchema = z.object({
  new_in_week: z.number().int(),
  active_current: z.number().int(),
  consulting_positive_current: z.number().int(),
});

export const admissionMetricsSchema = z.object({
  profiles_total: z.number().int(),
  submitted_in_week: z.number().int(),
  admitted_in_week: z.number().int(),
  enrolled_in_week: z.number().int(),
  submitted_cumulative: z.number().int(),
  admitted_cumulative: z.number().int(),
  enrolled_cumulative: z.number().int(),
  quota: z.number().int().nullable(), // chỉ tiêu (major view); null = N/A
});

export const conversionMetricsSchema = z.object({
  submit_to_admit: z.number().nullable(), // admitted/submitted (lũy kế); null nếu mẫu=0
  admit_to_enroll: z.number().nullable(), // enrolled/admitted (lũy kế)
});

export const financeMetricsSchema = z.object({
  gross_in_week: z.string(),
  refund_in_week: z.string(),
  net_in_week: z.string(),
  application_net_in_week: z.string(),
  tuition_net_in_week: z.string(),
  net_cumulative: z.string(),
  profiles_paid: z.number().int(),
});

export const bucketKindSchema = z.enum(["ambiguous", "unresolved", "unassigned"]);

export const reportRowSchema = z.object({
  group_key: z.number().int().nullable(),
  label: z.string(),
  code: z.string().nullable(),
  degree_level: z.string().nullable(),
  is_bucket: z.boolean(),
  bucket_kind: bucketKindSchema.nullable(),
  lead: leadMetricsSchema,
  admission: admissionMetricsSchema,
  conversion: conversionMetricsSchema,
  finance: financeMetricsSchema,
});

export const dataQualitySchema = z.object({
  total_profiles: z.number().int(),
  ambiguous_profiles: z.number().int(),
  unresolved_profiles: z.number().int(),
  unassigned_profiles: z.number().int(),
});

export const admissionWeeklyReportSchema = z.object({
  academic_year: z.number().int(),
  round_code: z.string().nullable(),
  group_by: z.enum(["major", "officer"]),
  week: weekMetaSchema,
  scope_unit_id: z.number().int().nullable(),
  attribution: z.literal("recomputed-current"),
  rows: z.array(reportRowSchema),
  totals: reportRowSchema,
  data_quality: dataQualitySchema,
});

/** GET /api/v2/admin/reports/admission-weekly/filters — năm (config ∪ data) + đợt. */
export const reportFiltersSchema = z.object({
  academic_years: z.array(z.number().int()),
  rounds: z.array(z.string()),
});

export type WeekMeta = z.infer<typeof weekMetaSchema>;
export type ReportRow = z.infer<typeof reportRowSchema>;
export type DataQuality = z.infer<typeof dataQualitySchema>;
export type AdmissionWeeklyReport = z.infer<typeof admissionWeeklyReportSchema>;
export type ReportFilters = z.infer<typeof reportFiltersSchema>;
export type ReportGroupBy = AdmissionWeeklyReport["group_by"];
