/**
 * Q9 #07 Phase E.3 — UT evidence verify/reject Zod schemas.
 *
 * Mirrors BE Pydantic ``VerifyObjectEvidenceRequest`` +
 * ``RejectObjectEvidenceRequest`` trong
 * ``Backend_FastAPI/app/schemas/admission.py`` — keep in sync.
 *
 * Service-layer guards (per memory ``version-guard-before-state-machine``):
 * * Version check FIRST → 409 ConflictError trên mismatch.
 * * sub_code must be trong profile.priority_object_codes → 400.
 * * Status hard-deny {draft, withdrawn, dropped} → 400.
 * * Reject reason 10-500 char mandatory.
 */
import { z } from "zod"

export const verifyObjectEvidenceRequestSchema = z.object({
  version: z.number().int().min(0),
  document_id: z.number().int().positive().nullable().optional(),
})

export type VerifyObjectEvidenceRequest = z.infer<
  typeof verifyObjectEvidenceRequestSchema
>

export const rejectObjectEvidenceRequestSchema = z.object({
  version: z.number().int().min(0),
  reject_reason: z
    .string()
    .trim()
    .min(10, "Lý do từ chối phải có ít nhất 10 ký tự")
    .max(500, "Lý do từ chối không được vượt quá 500 ký tự"),
})

export type RejectObjectEvidenceRequest = z.infer<
  typeof rejectObjectEvidenceRequestSchema
>
