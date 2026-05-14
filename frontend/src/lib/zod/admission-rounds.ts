/**
 * Zod schemas for OfferingAdmissionRound year-level (Phase 2 v8.2 PR-2A v2).
 *
 * Mirrors backend Pydantic models in
 * `Backend_FastAPI/app/schemas/admission_round.py`.
 * Quota fields ship trên admission_path (PR-2B v2), KHÔNG trên đây.
 */
import { z } from "zod"

// Phase 3 round flags surfaced via phase3_01 migration columns + this PR's
// Pydantic + FE wiring (Q-P3-02 allow_multi_nv, Q-P3-06 confirm_expiry_hours).
// Keep validation bounds consistent with Backend_FastAPI/app/schemas/admission_round.py.
const CONFIRM_EXPIRY_HOURS_MIN = 1
const CONFIRM_EXPIRY_HOURS_MAX = 8760 // 1 year ceiling, sanity guard.

export const AdmissionRoundCreateSchema = z.object({
  round_code: z.string().min(1).max(20),
  round_name: z.string().min(1).max(100),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  is_active: z.boolean().default(true),
  allow_multi_nv: z.boolean().default(false),
  confirm_expiry_hours: z
    .number()
    .int()
    .min(CONFIRM_EXPIRY_HOURS_MIN)
    .max(CONFIRM_EXPIRY_HOURS_MAX)
    .default(168),
})

export const AdmissionRoundUpdateSchema = z.object({
  round_name: z.string().min(1).max(100).optional(),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  is_active: z.boolean().optional(),
  allow_multi_nv: z.boolean().optional(),
  confirm_expiry_hours: z
    .number()
    .int()
    .min(CONFIRM_EXPIRY_HOURS_MIN)
    .max(CONFIRM_EXPIRY_HOURS_MAX)
    .optional(),
})

export const AdmissionRoundExtendSchema = z.object({
  end_date: z.string().min(1, "Vui lòng chọn ngày kết thúc mới"),
  extension_reason: z
    .string()
    .min(10, "Lý do phải có ít nhất 10 ký tự")
    .transform((s) => s.trim()),
})

export const AdmissionRoundBulkCreateItemSchema = z.object({
  round_code: z.string().min(1).max(20),
  round_name: z.string().min(1).max(100),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  is_active: z.boolean().default(true),
  allow_multi_nv: z.boolean().default(false),
  confirm_expiry_hours: z
    .number()
    .int()
    .min(CONFIRM_EXPIRY_HOURS_MIN)
    .max(CONFIRM_EXPIRY_HOURS_MAX)
    .default(168),
})

export const AdmissionRoundBulkCreateSchema = z.object({
  rounds: z.array(AdmissionRoundBulkCreateItemSchema).min(1).max(10),
})

export const AdmissionRoundResponseSchema = z.object({
  id: z.number().int(),
  academic_year: z.number().int(),
  round_code: z.string(),
  round_name: z.string(),
  start_date: z.string().nullable(),
  end_date: z.string().nullable(),
  is_active: z.boolean(),
  archived_at: z.string().nullable(),
  extended_at: z.string().nullable(),
  extended_by_user_id: z.number().int().nullable(),
  extension_reason: z.string().nullable(),
  allow_multi_nv: z.boolean(),
  confirm_expiry_hours: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
})

export const AdmissionRoundListResponseSchema = z.object({
  total: z.number().int(),
  items: z.array(AdmissionRoundResponseSchema),
})

export const AdmissionRoundBulkCreateResponseSchema = z.object({
  requested: z.number().int(),
  created: z.number().int(),
  skipped_duplicates: z.number().int(),
  items: z.array(AdmissionRoundResponseSchema),
})

export type AdmissionRoundCreate = z.infer<typeof AdmissionRoundCreateSchema>
export type AdmissionRoundUpdate = z.infer<typeof AdmissionRoundUpdateSchema>
export type AdmissionRoundExtend = z.infer<typeof AdmissionRoundExtendSchema>
export type AdmissionRoundBulkCreateItem = z.infer<typeof AdmissionRoundBulkCreateItemSchema>
export type AdmissionRoundBulkCreate = z.infer<typeof AdmissionRoundBulkCreateSchema>
export type AdmissionRoundResponse = z.infer<typeof AdmissionRoundResponseSchema>
export type AdmissionRoundListResponse = z.infer<typeof AdmissionRoundListResponseSchema>
export type AdmissionRoundBulkCreateResponse = z.infer<typeof AdmissionRoundBulkCreateResponseSchema>
