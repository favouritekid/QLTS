/**
 * Zod schemas for OfferingAdmissionRound year-level (Phase 2 v8.2 PR-2A v2).
 *
 * Mirrors backend Pydantic models in
 * `Backend_FastAPI/app/schemas/admission_round.py`.
 * Quota fields ship trên admission_path (PR-2B v2), KHÔNG trên đây.
 */
import { z } from "zod"

export const AdmissionRoundCreateSchema = z.object({
  round_code: z.string().min(1).max(20),
  round_name: z.string().min(1).max(100),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  is_active: z.boolean().default(true),
})

export const AdmissionRoundUpdateSchema = z.object({
  round_name: z.string().min(1).max(100).optional(),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  is_active: z.boolean().optional(),
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
