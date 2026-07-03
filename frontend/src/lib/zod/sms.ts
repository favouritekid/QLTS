// src/lib/zod/sms.ts
// Mirror Backend Pydantic: SmsLandingResponse + SmsPublicOptOut* (PR-5 §19.4)
// cho landing công khai, và các schema admin reports/dashboard/opt-out (PR-6
// tiêu thụ router admin của PR-5: app/routers/sms_reports.py).
// Public landing /lp/{code} — KHÔNG lộ PII recipient.
import { z } from "zod"

/** 1 ngành trong danh mục landing 2 tầng (Phase 2 §16.1). */
export const smsLandingProgramSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  code: z.string(),
  degree_level: z.string(),
})
export type SmsLandingProgram = z.infer<typeof smsLandingProgramSchema>

export const smsLandingResponseSchema = z.object({
  school_name: z.string(),
  headline: z.string().nullable().optional(),
  body: z.string().nullable().optional(),
  cta_label: z.string().nullable().optional(),
  cta_url: z.string().nullable().optional(),
  consent_notice: z.string(),
  already_opted_out: z.boolean(),
  // Phase 2: danh mục ngành (rỗng nếu chưa có ngành active).
  programs: z.array(smsLandingProgramSchema).default([]),
})
export type SmsLandingResponse = z.infer<typeof smsLandingResponseSchema>

export const smsPublicOptOutResponseSchema = z.object({
  success: z.boolean(),
  already_opted_out: z.boolean(),
})
export type SmsPublicOptOutResponse = z.infer<
  typeof smsPublicOptOutResponseSchema
>

// =====================================================================
// Phase 2 (§16) — deep engagement tracking (session / view / heartbeat)
// Public: /api/public/sms/landing/{code}/{session,program-view,heartbeat}
// =====================================================================
export const smsSessionStartResponseSchema = z.object({
  session_token: z.string(),
  session_id: z.number().int(),
})
export type SmsSessionStartResponse = z.infer<
  typeof smsSessionStartResponseSchema
>

export const smsProgramViewResponseSchema = z.object({
  program_view_id: z.number().int(),
  sequence_no: z.number().int(),
})
export type SmsProgramViewResponse = z.infer<
  typeof smsProgramViewResponseSchema
>

export const smsHeartbeatResponseSchema = z.object({
  ok: z.boolean(),
  dwell_seconds: z.number().int(),
  active_seconds: z.number().int(),
})
export type SmsHeartbeatResponse = z.infer<typeof smsHeartbeatResponseSchema>

// Admin — report ngành nóng + hồ sơ sở thích 1 contact (§16.7).
export const smsProgramInterestRowSchema = z.object({
  major_program_id: z.number().int().nullable(),
  program_name: z.string(),
  distinct_contacts: z.number().int(),
  view_count: z.number().int(),
  total_dwell_seconds: z.number().int(),
  avg_dwell_seconds: z.number(),
})
export type SmsProgramInterestRow = z.infer<
  typeof smsProgramInterestRowSchema
>

export const smsProgramInterestReportSchema = z.object({
  items: z.array(smsProgramInterestRowSchema).default([]),
  distinct_contacts_total: z.number().int(),
  view_count_total: z.number().int(),
  total_dwell_seconds: z.number().int(),
})
export type SmsProgramInterestReport = z.infer<
  typeof smsProgramInterestReportSchema
>

export const smsContactInterestRowSchema = z.object({
  major_program_id: z.number().int(),
  program_name: z.string(),
  view_count: z.number().int(),
  total_dwell_seconds: z.number().int(),
  interest_score: z.number(),
  first_interest_at: z.string().nullable().optional(),
  last_interest_at: z.string().nullable().optional(),
})
export type SmsContactInterestRow = z.infer<
  typeof smsContactInterestRowSchema
>

export const smsContactInterestListSchema = z.object({
  contact_id: z.number().int(),
  items: z.array(smsContactInterestRowSchema).default([]),
})
export type SmsContactInterestList = z.infer<
  typeof smsContactInterestListSchema
>

// --- P2-3/P2-4b consult officer (§16.7) ---
export const smsConsultLinkResponseSchema = z.object({
  code: z.string(),
  url: z.string(),
  consult_link_id: z.number().int(),
  contact_id: z.number().int(),
})
export type SmsConsultLinkResponse = z.infer<
  typeof smsConsultLinkResponseSchema
>

export const smsLeadInterestResponseSchema = z.object({
  lead_id: z.number().int(),
  contact_id: z.number().int().nullable(),
  items: z.array(smsContactInterestRowSchema).default([]),
})
export type SmsLeadInterestResponse = z.infer<
  typeof smsLeadInterestResponseSchema
>

// =====================================================================
// Admin — enum literal (mirror CHECK constraint / Literal ở Backend)
// =====================================================================
/** granularity báo cáo click (sms_reports.py: pattern `^(day|month|year)$`). */
export const SMS_GRANULARITIES = ["day", "month", "year"] as const
export type SmsGranularity = (typeof SMS_GRANULARITIES)[number]

/** Nguồn opt-out thủ công (Pydantic SmsManualOptOutSource). */
export const SMS_MANUAL_OPT_OUT_SOURCES = [
  "manual",
  "sms_reply",
  "phone_call",
  "external_suppression",
] as const
export type SmsManualOptOutSource = (typeof SMS_MANUAL_OPT_OUT_SOURCES)[number]

/**
 * Nhóm nhà mạng (sms_prefix_carrier_rule.carrier_bucket). `unknown` = số
 * không khớp prefix nào (BE seed comment). Dùng cho filter báo cáo + nhãn.
 */
export const SMS_CARRIER_BUCKETS = [
  "viettel",
  "vinaphone",
  "mobifone",
  "vietnamobile",
  "gmobile",
  "unknown",
] as const
export type SmsCarrierBucket = (typeof SMS_CARRIER_BUCKETS)[number]

// =====================================================================
// Admin — Reports click (§9 / SmsClickReport, SmsClickBucket)
// =====================================================================
export const smsClickBucketSchema = z.object({
  period: z.string(),
  total_clicks: z.number(),
  human_clicks: z.number(),
  distinct_contacts_clicked: z.number(),
})
export type SmsClickBucket = z.infer<typeof smsClickBucketSchema>

export const smsClickReportSchema = z.object({
  granularity: z.string(),
  buckets: z.array(smsClickBucketSchema),
  total_clicks: z.number(),
  human_clicks: z.number(),
  distinct_contacts_clicked: z.number(),
  recipients_handed_off: z.number(),
  ctr_percent: z.number(),
})
export type SmsClickReport = z.infer<typeof smsClickReportSchema>

// =====================================================================
// Admin — Dashboard chiến dịch (SmsCampaignDashboard, SmsClickerOut)
// =====================================================================
export const smsClickerSchema = z.object({
  recipient_id: z.number(),
  contact_id: z.number().nullable().optional(),
  full_name: z.string(),
  phone_masked: z.string(),
  carrier_bucket: z.string(),
  human_click_count: z.number(),
  first_human_clicked_at: z.string().nullable().optional(),
  last_human_clicked_at: z.string().nullable().optional(),
})
export type SmsClicker = z.infer<typeof smsClickerSchema>

export const smsCampaignDashboardSchema = z.object({
  campaign_id: z.number(),
  build_revision: z.number(),
  has_link: z.boolean(),
  recipients_handed_off: z.number(),
  total_clicks: z.number(),
  human_clicks: z.number(),
  distinct_contacts_clicked: z.number(),
  ctr_percent: z.number(),
  carrier_distribution: z.record(z.string(), z.number()),
  clickers: z.array(smsClickerSchema),
})
export type SmsCampaignDashboard = z.infer<typeof smsCampaignDashboardSchema>

// =====================================================================
// Admin — danh sách campaign (cho picker dashboard + filter report).
// Subset cố ý của SmsCampaignOut: chỉ field UI dùng (Zod strip key thừa).
// =====================================================================
export const smsCampaignListItemSchema = z.object({
  id: z.number(),
  name: z.string(),
  code: z.string(),
  status: z.string(),
  build_revision: z.number(),
  has_link: z.boolean().nullable().optional(),
})
export type SmsCampaignListItem = z.infer<typeof smsCampaignListItemSchema>

export const smsCampaignListSchema = z.object({
  total: z.number(),
  items: z.array(smsCampaignListItemSchema),
})
export type SmsCampaignList = z.infer<typeof smsCampaignListSchema>

// =====================================================================
// Admin — Opt-out (suppression toàn cục)
// =====================================================================
export const smsOptOutSchema = z.object({
  id: z.number(),
  phone_normalized: z.string(),
  source: z.string(),
  source_reference: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
  observed_at: z.string(),
  created_at: z.string(),
})
export type SmsOptOut = z.infer<typeof smsOptOutSchema>

export const smsOptOutListSchema = z.object({
  total: z.number(),
  items: z.array(smsOptOutSchema),
})
export type SmsOptOutList = z.infer<typeof smsOptOutListSchema>

/**
 * Form thêm opt-out thủ công. Mirror Pydantic SmsOptOutManualCreate:
 * phone 8–32 ký tự; reason ≤ 2000; source_reference ≤ 512.
 */
export const smsManualOptOutSchema = z.object({
  phone: z
    .string()
    .trim()
    .min(8, "Số điện thoại tối thiểu 8 ký tự")
    .max(32, "Số điện thoại tối đa 32 ký tự"),
  source: z.enum(SMS_MANUAL_OPT_OUT_SOURCES),
  // "" hợp lệ (length 0 ≤ max) nên `.optional()` đủ — không cần `.or("")`;
  // giữ message max cụ thể khi vượt giới hạn.
  source_reference: z
    .string()
    .trim()
    .max(512, "Tham chiếu nguồn tối đa 512 ký tự")
    .optional(),
  reason: z
    .string()
    .trim()
    .max(2000, "Lý do tối đa 2000 ký tự")
    .optional(),
})
export type SmsManualOptOutInput = z.infer<typeof smsManualOptOutSchema>

// =====================================================================
// Admin — Contact / Group / Consent (PR-6b; mirror app/schemas/sms.py
// SmsContactGroup*, SmsContact*, SmsConsentEvent*, SmsImportResult).
// =====================================================================

/** Loại nhóm liên hệ (mirror GroupType). */
export const SMS_GROUP_TYPES = [
  "parent",
  "student",
  "teacher",
  "lead",
  "custom",
] as const
export type SmsGroupType = (typeof SMS_GROUP_TYPES)[number]

/** Trạng thái consent marketing (CHECK chk_sms_contact_consent_status). */
export const SMS_CONSENT_STATUSES = ["unknown", "granted", "revoked"] as const

/** Căn cứ consent GRANT (mirror ConsentBasis). */
export const SMS_CONSENT_BASES = [
  "explicit_form",
  "signed_form",
  "recorded_call",
  "imported_proof",
] as const
export type SmsConsentBasis = (typeof SMS_CONSENT_BASES)[number]

/** Nguồn REVOKE (mirror RevokeSource). */
export const SMS_REVOKE_SOURCES = [
  "sms_reply",
  "landing_optout",
  "manual",
  "phone_call",
  "external_suppression",
] as const
export type SmsRevokeSource = (typeof SMS_REVOKE_SOURCES)[number]

export const SMS_CONSENT_EVENT_TYPES = ["granted", "revoked"] as const

// --- Contact group ---
export const smsContactGroupSchema = z.object({
  id: z.number(),
  name: z.string(),
  code: z.string(),
  group_type: z.string(),
  description: z.string().nullable().optional(),
  is_active: z.boolean(),
  created_by_id: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  member_count: z.number().nullable().optional(),
})
export type SmsContactGroup = z.infer<typeof smsContactGroupSchema>

export const smsContactGroupListSchema = z.object({
  total: z.number(),
  items: z.array(smsContactGroupSchema),
})
export type SmsContactGroupList = z.infer<typeof smsContactGroupListSchema>

/** Form tạo nhóm. `code` để trống → BE tự slugify từ name. */
export const smsContactGroupCreateSchema = z.object({
  name: z.string().trim().min(1, "Bắt buộc nhập tên").max(200),
  code: z
    .string()
    .trim()
    .max(50)
    .regex(/^[a-z0-9][a-z0-9-]*$/, "Chỉ a-z, 0-9, dấu gạch; bắt đầu bằng chữ/số")
    .optional()
    .or(z.literal("")),
  group_type: z.enum(SMS_GROUP_TYPES),
  description: z.string().trim().max(2000).optional().or(z.literal("")),
})
export type SmsContactGroupCreateInput = z.infer<
  typeof smsContactGroupCreateSchema
>

/** Form sửa nhóm — không đổi `code`. */
export const smsContactGroupUpdateSchema = z.object({
  name: z.string().trim().min(1, "Bắt buộc nhập tên").max(200),
  group_type: z.enum(SMS_GROUP_TYPES),
  description: z.string().trim().max(2000).optional().or(z.literal("")),
  is_active: z.boolean(),
})
export type SmsContactGroupUpdateInput = z.infer<
  typeof smsContactGroupUpdateSchema
>

// --- Contact ---
export const smsContactSchema = z.object({
  id: z.number(),
  full_name: z.string(),
  phone_raw: z.string().nullable().optional(),
  phone_normalized: z.string(),
  phone_international: z.string(),
  note: z.string().nullable().optional(),
  source_label: z.string().nullable().optional(),
  marketing_consent_status: z.string(),
  marketing_consented_at: z.string().nullable().optional(),
  marketing_consent_basis: z.string().nullable().optional(),
  marketing_consent_proof_ref: z.string().nullable().optional(),
  consent_disclosure_version: z.string().nullable().optional(),
  last_handed_off_at: z.string().nullable().optional(),
  created_by_id: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type SmsContact = z.infer<typeof smsContactSchema>

export const smsContactListSchema = z.object({
  total: z.number(),
  items: z.array(smsContactSchema),
})
export type SmsContactList = z.infer<typeof smsContactListSchema>

export const smsContactCreateSchema = z.object({
  full_name: z.string().trim().min(1, "Bắt buộc nhập họ tên").max(255),
  phone: z
    .string()
    .trim()
    .min(1, "Bắt buộc nhập số điện thoại")
    .max(32),
  note: z.string().trim().max(2000).optional().or(z.literal("")),
  source_label: z.string().trim().max(255).optional().or(z.literal("")),
})
export type SmsContactCreateInput = z.infer<typeof smsContactCreateSchema>

/** Sửa identity/note — KHÔNG đổi phone (identity), KHÔNG đụng consent. */
export const smsContactUpdateSchema = z.object({
  full_name: z.string().trim().min(1, "Bắt buộc nhập họ tên").max(255),
  note: z.string().trim().max(2000).optional().or(z.literal("")),
  source_label: z.string().trim().max(255).optional().or(z.literal("")),
})
export type SmsContactUpdateInput = z.infer<typeof smsContactUpdateSchema>

// --- Consent event (append-only ledger) ---
export const smsConsentEventSchema = z.object({
  id: z.number(),
  contact_id: z.number().nullable().optional(),
  phone_normalized_snapshot: z.string(),
  event_type: z.string(),
  basis: z.string().nullable().optional(),
  revoke_source: z.string().nullable().optional(),
  disclosure_version: z.string().nullable().optional(),
  proof_reference: z.string().nullable().optional(),
  occurred_at: z.string(),
  recorded_by_id: z.number().nullable().optional(),
  import_batch_id: z.number().nullable().optional(),
  metadata_json: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string(),
})
export type SmsConsentEvent = z.infer<typeof smsConsentEventSchema>

export const smsConsentEventListSchema = z.object({
  total: z.number(),
  items: z.array(smsConsentEventSchema),
})
export type SmsConsentEventList = z.infer<typeof smsConsentEventListSchema>

/**
 * Form ghi consent. Mirror cross-field của BE model_validator:
 * GRANT → cần basis + disclosure_version + proof_reference (không rỗng), cấm
 * revoke_source. REVOKE → cần revoke_source, cấm grant-data.
 * `occurred_at` = ISO tz-aware (form gửi datetime-local + offset).
 */
export const smsConsentEventCreateSchema = z
  .object({
    event_type: z.enum(SMS_CONSENT_EVENT_TYPES),
    occurred_at: z.string().min(1, "Bắt buộc chọn thời điểm"),
    basis: z.enum(SMS_CONSENT_BASES).optional(),
    disclosure_version: z.string().trim().max(50).optional().or(z.literal("")),
    proof_reference: z.string().trim().max(512).optional().or(z.literal("")),
    revoke_source: z.enum(SMS_REVOKE_SOURCES).optional(),
  })
  .superRefine((v, ctx) => {
    if (v.event_type === "granted") {
      if (!v.basis)
        ctx.addIssue({
          code: "custom",
          path: ["basis"],
          message: "GRANT cần căn cứ consent",
        })
      if (!v.disclosure_version?.trim())
        ctx.addIssue({
          code: "custom",
          path: ["disclosure_version"],
          message: "GRANT cần phiên bản công bố",
        })
      if (!v.proof_reference?.trim())
        ctx.addIssue({
          code: "custom",
          path: ["proof_reference"],
          message: "GRANT cần tham chiếu bằng chứng",
        })
    } else {
      if (!v.revoke_source)
        ctx.addIssue({
          code: "custom",
          path: ["revoke_source"],
          message: "REVOKE cần nguồn từ chối",
        })
    }
  })
export type SmsConsentEventCreateInput = z.infer<
  typeof smsConsentEventCreateSchema
>

// --- Import result (upload contacts vào nhóm) ---
export const smsImportRowErrorSchema = z.object({
  row_number: z.number(),
  phone_raw: z.string().nullable().optional(),
  reason: z.string(),
})
export type SmsImportRowError = z.infer<typeof smsImportRowErrorSchema>

export const smsImportResultSchema = z.object({
  batch_id: z.number(),
  group_id: z.number().nullable().optional(),
  file_name: z.string().nullable().optional(),
  row_count: z.number(),
  valid_count: z.number(),
  invalid_count: z.number(),
  duplicate_contact_count: z.number(),
  existing_member_count: z.number(),
  inserted_contact_count: z.number(),
  added_member_count: z.number(),
  skipped_count: z.number(),
  consent_applied: z.boolean(),
  errors: z.array(smsImportRowErrorSchema),
})
export type SmsImportResult = z.infer<typeof smsImportResultSchema>

// =====================================================================
// Admin — Campaign (full) + Build/Preflight (PR-6d; mirror SmsCampaignOut/
// Create/Update, SmsPreflightReport, SmsOverLimitRow ở app/schemas/sms.py).
// =====================================================================

/** Loại landing (mirror SmsLandingType). */
export const SMS_LANDING_TYPES = ["qlts_hosted", "external"] as const
export type SmsLandingType = (typeof SMS_LANDING_TYPES)[number]

/** Lý do recipient bị loại (mirror SmsExcludedReason / CHECK). */
export const SMS_EXCLUDED_REASONS = [
  "no_consent",
  "opted_out",
  "dnc_suppressed",
  "frequency_capped",
  "over_limit",
  "missing_data",
] as const
export type SmsExcludedReason = (typeof SMS_EXCLUDED_REASONS)[number]

/** Campaign đầy đủ (mirror SmsCampaignOut). Datetime = ISO string. */
export const smsCampaignSchema = z.object({
  id: z.number(),
  name: z.string(),
  code: z.string(),
  status: z.string(),
  sms_template: z.string(),
  frequency_cap_days: z.number().nullable().optional(),
  landing_type: z.string(),
  landing_url: z.string().nullable().optional(),
  landing_headline: z.string().nullable().optional(),
  landing_body: z.string().nullable().optional(),
  landing_cta_label: z.string().nullable().optional(),
  landing_cta_url: z.string().nullable().optional(),
  build_revision: z.number(),
  link_expires_at: z.string().nullable().optional(),
  optout_instruction_snapshot: z.string().nullable().optional(),
  // Attestation (dùng ở PR-6e; hợp lệ khi *_checked_build_revision === build_revision)
  consent_checked_at: z.string().nullable().optional(),
  consent_checked_by_id: z.number().nullable().optional(),
  consent_reference: z.string().nullable().optional(),
  consent_checked_build_revision: z.number().nullable().optional(),
  dnc_checked_at: z.string().nullable().optional(),
  dnc_checked_by_id: z.number().nullable().optional(),
  dnc_reference: z.string().nullable().optional(),
  dnc_checked_build_revision: z.number().nullable().optional(),
  optout_channel_checked_at: z.string().nullable().optional(),
  optout_channel_checked_by_id: z.number().nullable().optional(),
  optout_channel_reference: z.string().nullable().optional(),
  optout_channel_checked_build_revision: z.number().nullable().optional(),
  created_by_id: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
  handed_off_marked_at: z.string().nullable().optional(),
  has_link: z.boolean().nullable().optional(),
  group_count: z.number().nullable().optional(),
})
export type SmsCampaign = z.infer<typeof smsCampaignSchema>

export const smsCampaignFullListSchema = z.object({
  total: z.number(),
  items: z.array(smsCampaignSchema),
})
export type SmsCampaignFullList = z.infer<typeof smsCampaignFullListSchema>

/** Form tạo campaign. Cross-field (biến template, external+{link}) do BE gate. */
export const smsCampaignCreateSchema = z.object({
  name: z.string().trim().min(1, "Bắt buộc nhập tên").max(200),
  code: z
    .string()
    .trim()
    .max(50)
    .regex(/^[a-z0-9][a-z0-9-]*$/, "Chỉ a-z, 0-9, dấu gạch; bắt đầu bằng chữ/số")
    .optional()
    .or(z.literal("")),
  sms_template: z
    .string()
    .trim()
    .min(1, "Bắt buộc nhập nội dung tin")
    .max(2000),
  landing_type: z.enum(SMS_LANDING_TYPES),
  landing_url: z.string().trim().max(2000).optional().or(z.literal("")),
  landing_headline: z.string().trim().max(200).optional().or(z.literal("")),
  landing_body: z.string().trim().max(10000).optional().or(z.literal("")),
  landing_cta_label: z.string().trim().max(100).optional().or(z.literal("")),
  landing_cta_url: z.string().trim().max(2000).optional().or(z.literal("")),
  frequency_cap_days: z.number().int().min(0).max(3650).nullable().optional(),
  link_expires_at: z.string().nullable().optional(),
})
export type SmsCampaignCreateInput = z.infer<typeof smsCampaignCreateSchema>

/** Form sửa campaign (chỉ khi draft; không đổi code). */
export const smsCampaignUpdateSchema = smsCampaignCreateSchema.omit({
  code: true,
})
export type SmsCampaignUpdateInput = z.infer<typeof smsCampaignUpdateSchema>

// --- Build / Preflight ---
export const smsOverLimitRowSchema = z.object({
  phone_normalized: z.string(),
  full_name: z.string(),
  encoding: z.string().nullable().optional(),
  length: z.number().nullable().optional(),
  segments: z.number().nullable().optional(),
})
export type SmsOverLimitRow = z.infer<typeof smsOverLimitRowSchema>

export const smsPreflightReportSchema = z.object({
  campaign_id: z.number(),
  build_revision: z.number(),
  status: z.string(),
  has_link: z.boolean(),
  total: z.number(),
  exportable: z.number(),
  excluded_by_reason: z.record(z.string(), z.number()),
  carrier_distribution: z.record(z.string(), z.number()),
  over_limit: z.array(smsOverLimitRowSchema),
  warnings: z.array(z.string()),
  preview: z.array(z.string()),
})
export type SmsPreflightReport = z.infer<typeof smsPreflightReportSchema>

// =====================================================================
// Admin — Attestation + Export lifecycle (PR-6e; mirror SmsAttestationCreate,
// SmsExportBatchOut/Result/List ở app/schemas/sms.py).
// =====================================================================

/** Loại attestation gate export (mirror SmsAttestationKind). */
export const SMS_ATTESTATION_KINDS = [
  "consent",
  "dnc",
  "optout_channel",
] as const
export type SmsAttestationKind = (typeof SMS_ATTESTATION_KINDS)[number]

/** Form ghi attestation cho build_revision hiện tại. */
export const smsAttestationCreateSchema = z.object({
  kind: z.enum(SMS_ATTESTATION_KINDS),
  reference: z.string().trim().min(1, "Bắt buộc nhập tham chiếu").max(512),
})
export type SmsAttestationCreateInput = z.infer<
  typeof smsAttestationCreateSchema
>

/** Trạng thái vòng đời batch export (mirror SmsExportStatus / CHECK). */
export const SMS_EXPORT_STATUSES = [
  "pending",
  "generated",
  "handed_off",
  "failed",
  "purged",
  "invalidated",
] as const
export type SmsExportStatus = (typeof SMS_EXPORT_STATUSES)[number]

/** 1 file Excel / nhà mạng / build_revision (mirror SmsExportBatchOut). */
export const smsExportBatchSchema = z.object({
  id: z.number(),
  campaign_id: z.number(),
  build_revision: z.number(),
  group_id: z.number().nullable().optional(),
  group_name_snapshot: z.string().nullable().optional(),
  carrier_bucket: z.string(),
  recipient_count: z.number(),
  file_name: z.string().nullable().optional(),
  file_size_bytes: z.number().nullable().optional(),
  status: z.string(),
  failure_reason: z.string().nullable().optional(),
  expires_at: z.string().nullable().optional(),
  generated_at: z.string().nullable().optional(),
  generated_by_id: z.number().nullable().optional(),
  marked_handed_off_at: z.string().nullable().optional(),
  invalidated_at: z.string().nullable().optional(),
  // Cờ do BE điền — thin-client đọc cờ, KHÔNG tự suy trạng thái.
  can_download: z.boolean(),
  can_mark_handed_off: z.boolean(),
  is_expired: z.boolean(),
})
export type SmsExportBatch = z.infer<typeof smsExportBatchSchema>

export const smsExportResultSchema = z.object({
  campaign_id: z.number(),
  build_revision: z.number(),
  total_exportable: z.number(),
  batches: z.array(smsExportBatchSchema),
  message: z.string().nullable().optional(),
})
export type SmsExportResult = z.infer<typeof smsExportResultSchema>

export const smsExportBatchListSchema = z.object({
  campaign_id: z.number(),
  build_revision: z.number(),
  batches: z.array(smsExportBatchSchema),
})
export type SmsExportBatchList = z.infer<typeof smsExportBatchListSchema>
