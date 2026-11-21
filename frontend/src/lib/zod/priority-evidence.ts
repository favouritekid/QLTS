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
 *
 * GĐ2-0 / GĐ2-F1 — đường cam kết khi không rõ người tải / người nhận (CÙNG tên trường với nút lẻ giấy tờ GĐ1b):
 * * duyệt: `unknown_submitter_ack` + `reason` (máy chủ đòi lý do khác rỗng sau khi bỏ khoảng trắng);
 * * từ chối: `unknown_submitter_ack`; lý do của cam kết = `reject_reason`.
 * Máy chủ là chốt (409 `UNKNOWN_SUBMITTER` / `OWN_SUBMISSION`); giao diện chỉ gửi khi máy chủ báo `requires_ack`.
 */
import { z } from "zod"

export const verifyObjectEvidenceRequestSchema = z.object({
  version: z.number().int().min(0),
  document_id: z.number().int().positive().nullable().optional(),
  reason: z.string().max(500).optional(),
  unknown_submitter_ack: z.boolean().optional(),
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
  unknown_submitter_ack: z.boolean().optional(),
})

export type RejectObjectEvidenceRequest = z.infer<
  typeof rejectObjectEvidenceRequestSchema
>
