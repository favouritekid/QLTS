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
  // đã đóng lệ phí xét tuyển nhưng hồ sơ CHƯA nộp (prepay-draft). default(0) để
  // không vỡ nếu BE cũ chưa trả field.
  fee_paid_not_submitted: z.number().int().default(0),
  admitted_cumulative: z.number().int(),
  enrolled_cumulative: z.number().int(),
  // Chi tiết hoá (khớp heatmap): nháp + học phí HK1 một-phần/đủ. default(0) để
  // không vỡ nếu BE cũ chưa trả field.
  draft: z.number().int().default(0),
  fee_hk1_partial: z.number().int().default(0),
  fee_hk1_full: z.number().int().default(0),
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
  // True chỉ khi lũy-kế TÍNH ĐẾN HÔM NAY (anchor ngầm = today) → cột snapshot
  // (Nháp/HK1) mới nhất quán với cột cumulative-as-of. default(false) backward-compat.
  snapshot_as_of_now: z.boolean().default(false),
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

// ===========================================================================
// Overview dashboard extras — pipeline funnel · trend · officer×major heatmap
// (GET .../admission-weekly/{pipeline-funnel,trend,officer-major-matrix})
// ===========================================================================

export const funnelStageSchema = z.object({
  stage_id: z.string(), // "stg01"..
  name: z.string(),
  order: z.number().int(), // 0-based
  is_final: z.boolean(),
  color_code: z.string(), // hex #RRGGBB
  current: z.number().int(), // lead đang ở giai đoạn này
  // mô hình phễu do BACKEND tính (thin-client — FE render nguyên):
  reached: z.number().int(), // lũy kế "từng đạt bậc này" (đường phễu); leak = current
  conversion_pct: z.number().nullable(), // % chuyển tiếp từ bậc trước (0..100)
  is_leak: z.boolean(), // bậc rời phễu (terminal âm) — render tách khỏi path
});

export const pipelineFunnelSchema = z.object({
  academic_year: z.number().int(),
  round_code: z.string().nullable(),
  scope_unit_id: z.number().int().nullable(),
  total_leads: z.number().int(), // = Σ on-path + leaked
  leaked: z.number().int(), // lead rời phễu (final + outcome negative, mọi bậc)
  stages: z.array(funnelStageSchema),
});

export const trendPointSchema = z.object({
  iso_year: z.number().int(),
  iso_week: z.number().int(),
  week_start: z.string(), // YYYY-MM-DD (Monday)
  week_end: z.string(),
  submitted_cumulative: z.number().int(),
  admitted_cumulative: z.number().int(),
  enrolled_cumulative: z.number().int(),
});

export const admissionTrendSchema = z.object({
  academic_year: z.number().int(),
  round_code: z.string().nullable(),
  scope_unit_id: z.number().int().nullable(),
  weeks: z.number().int(),
  points: z.array(trendPointSchema), // cũ → mới
});

export const matrixOfficerSchema = z.object({
  id: z.number().int().nullable(), // null = "Chưa gán cán bộ"
  name: z.string(),
});

export const matrixMajorSchema = z.object({
  id: z.number().int().nullable(), // null = "Chưa phân loại ngành"
  code: z.string().nullable(),
  name: z.string(),
  degree_level: z.string().nullable(),
});

// 5 chỉ số/ô → FE render 3 tab (Hồ sơ · Học phí HK1 · Nhập học). `default(0)` để
// không vỡ nếu BE cũ chưa trả field mới.
export const officerMajorCellSchema = z.object({
  officer_id: z.number().int().nullable(),
  major_id: z.number().int().nullable(),
  submitted: z.number().int().default(0), // đã nộp hồ sơ (cumulative)
  draft: z.number().int().default(0), // hồ sơ đang ở trạng thái 'draft' (nháp)
  fee_partial: z.number().int().default(0), // đóng học phí HK1 một phần
  fee_full: z.number().int().default(0), // đóng đủ học phí HK1
  enrolled: z.number().int().default(0), // đã nhập học (cumulative)
});

export const officerMajorMatrixSchema = z.object({
  academic_year: z.number().int(),
  round_code: z.string().nullable(),
  scope_unit_id: z.number().int().nullable(),
  officers: z.array(matrixOfficerSchema), // cán bộ (render làm cột)
  majors: z.array(matrixMajorSchema), // ngành (render làm hàng)
  cells: z.array(officerMajorCellSchema), // thưa
});

export type FunnelStage = z.infer<typeof funnelStageSchema>;
export type PipelineFunnel = z.infer<typeof pipelineFunnelSchema>;
export type TrendPoint = z.infer<typeof trendPointSchema>;
export type AdmissionTrend = z.infer<typeof admissionTrendSchema>;
export type MatrixOfficer = z.infer<typeof matrixOfficerSchema>;
export type MatrixMajor = z.infer<typeof matrixMajorSchema>;
export type OfficerMajorCell = z.infer<typeof officerMajorCellSchema>;
export type OfficerMajorMatrix = z.infer<typeof officerMajorMatrixSchema>;
/** Khoá 1 chỉ số trong ô (dùng cho tab heatmap). */
export type MatrixMetric = "submitted" | "draft" | "fee_partial" | "fee_full" | "enrolled";

// ===========================================================================
// Week-over-week — biến động 2 tuần ISO ĐÃ HOÀN TẤT (loại tuần đang chạy)
// (GET .../admission-weekly/week-over-week)
// ===========================================================================

export const wowMovementSchema = z.object({
  count_current: z.number().int().default(0), // tuần hoàn tất gần nhất (W-1)
  count_previous: z.number().int().default(0), // tuần hoàn tất liền trước (W-2)
  delta: z.number().int().default(0),
  delta_pct: z.number().nullable().default(null), // %; null khi mẫu số 0
});

export const wowRowSchema = z.object({
  group_key: z.number().int().nullable(),
  label: z.string(),
  code: z.string().nullable().default(null),
  degree_level: z.string().nullable().default(null),
  is_bucket: z.boolean().default(false),
  bucket_kind: bucketKindSchema.nullable().default(null),
  submitted: wowMovementSchema,
  admitted: wowMovementSchema,
  enrolled: wowMovementSchema,
});

export const wowComparisonSchema = z.object({
  latest_complete_week: weekMetaSchema, // W-1
  previous_complete_week: weekMetaSchema, // W-2
});

export const admissionWowSchema = z.object({
  academic_year: z.number().int(),
  round_code: z.string().nullable(),
  scope_unit_id: z.number().int().nullable(),
  group_by: z.enum(["major", "officer"]),
  attribution: z.literal("recomputed-current"),
  // Năm chưa bắt đầu / không đủ 2 tuần hoàn tất → comparison=null, rows=[].
  insufficient_data: z.boolean().default(false),
  comparison: wowComparisonSchema.nullable().default(null),
  rows: z.array(wowRowSchema).default([]),
  totals: wowRowSchema,
});

export type WowMovement = z.infer<typeof wowMovementSchema>;
export type WowRow = z.infer<typeof wowRowSchema>;
export type AdmissionWow = z.infer<typeof admissionWowSchema>;
