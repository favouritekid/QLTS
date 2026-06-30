// src/lib/zod/sms.ts
// Mirror Backend Pydantic: SmsLandingResponse + SmsPublicOptOut* (PR-5 §19.4)
// cho landing công khai, và các schema admin reports/dashboard/opt-out (PR-6
// tiêu thụ router admin của PR-5: app/routers/sms_reports.py).
// Public landing /lp/{code} — KHÔNG lộ PII recipient.
import { z } from "zod"

export const smsLandingResponseSchema = z.object({
  school_name: z.string(),
  headline: z.string().nullable().optional(),
  body: z.string().nullable().optional(),
  cta_label: z.string().nullable().optional(),
  cta_url: z.string().nullable().optional(),
  consent_notice: z.string(),
  already_opted_out: z.boolean(),
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
  source_reference: z
    .string()
    .trim()
    .max(512, "Tham chiếu nguồn tối đa 512 ký tự")
    .optional()
    .or(z.literal("")),
  reason: z
    .string()
    .trim()
    .max(2000, "Lý do tối đa 2000 ký tự")
    .optional()
    .or(z.literal("")),
})
export type SmsManualOptOutInput = z.infer<typeof smsManualOptOutSchema>
