/**
 * Zod schemas for OfferingAdmissionRound (Phase 2 PR-2A).
 *
 * Mirrors backend Pydantic models in
 * `Backend_FastAPI/app/schemas/admission_round.py`.
 */
import { z } from "zod"

export const AdmissionRoundCreateSchema = z.object({
  round_code: z.string().min(1).max(20),
  round_name: z.string().min(1).max(100),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  round_quota: z.number().int().nonnegative().nullable().optional(),
  admit_quota: z.number().int().nonnegative().nullable().optional(),
  is_active: z.boolean().default(true),
})

export const AdmissionRoundUpdateSchema = z.object({
  round_name: z.string().min(1).max(100).optional(),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  round_quota: z.number().int().nonnegative().nullable().optional(),
  admit_quota: z.number().int().nonnegative().nullable().optional(),
  is_active: z.boolean().optional(),
  override: z.boolean().default(false),
})

export const AdmissionRoundExtendSchema = z.object({
  end_date: z.string().min(1, "end_date required"),
  extension_reason: z
    .string()
    .min(10, "Extension reason phải ≥10 ký tự")
    .transform((s) => s.trim()),
})

export const AdmissionRoundResponseSchema = z.object({
  id: z.number().int(),
  academic_info_id: z.number().int(),
  round_code: z.string(),
  round_name: z.string(),
  start_date: z.string().nullable(),
  end_date: z.string().nullable(),
  round_quota: z.number().int().nullable(),
  admit_quota: z.number().int().nullable(),
  submission_count: z.number().int(),
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

export type AdmissionRoundCreate = z.infer<typeof AdmissionRoundCreateSchema>
export type AdmissionRoundUpdate = z.infer<typeof AdmissionRoundUpdateSchema>
export type AdmissionRoundExtend = z.infer<typeof AdmissionRoundExtendSchema>
export type AdmissionRoundResponse = z.infer<typeof AdmissionRoundResponseSchema>
export type AdmissionRoundListResponse = z.infer<
  typeof AdmissionRoundListResponseSchema
>
