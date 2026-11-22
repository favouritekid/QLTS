/**
 * GĐ2-C C1 — schema quyền "Thư ký Hội đồng" (máy chủ: `app/schemas/review_secretary.py`).
 *
 * Không có trường hạn (owner C1 22-11: không hết hạn, giữ tới khi Admin thu hồi) và không có đơn vị (owner C2 22-11: toàn
 * trường). Thân gán / thu hồi `strict` như máy chủ (`extra = "forbid"`).
 */
import { z } from "zod"

const reasonSchema = z.string().trim().min(1).max(500)

export const reviewSecretaryGrantCreateBodySchema = z
  .object({
    user_id: z.number().int().positive(),
    reason: reasonSchema,
  })
  .strict()
export type ReviewSecretaryGrantCreateBody = z.infer<typeof reviewSecretaryGrantCreateBodySchema>

export const reviewSecretaryGrantRevokeBodySchema = z.object({ reason: reasonSchema }).strict()
export type ReviewSecretaryGrantRevokeBody = z.infer<typeof reviewSecretaryGrantRevokeBodySchema>

/** Tóm tắt CÁN BỘ được gán (không dữ liệu học sinh). */
export const reviewSecretaryUserSchema = z.object({
  id: z.number().int().positive(),
  username: z.string(),
  full_name: z.string().nullable(),
  role: z.string(),
  status: z.string(),
})

/** `ReviewSecretaryGrantView` — `is_active` do máy chủ tính (`revoked_at` trống). */
export const reviewSecretaryGrantSchema = z.object({
  id: z.number().int().positive(),
  user_id: z.number().int().positive(),
  user: reviewSecretaryUserSchema.nullable(),
  granted_by_user_id: z.number().int().positive(),
  granted_at: z.string().min(1),
  reason: z.string(),
  revoked_at: z.string().nullable(),
  revoked_by_user_id: z.number().int().positive().nullable(),
  revoke_reason: z.string().nullable(),
  is_active: z.boolean(),
})
export type ReviewSecretaryGrant = z.infer<typeof reviewSecretaryGrantSchema>

/** Danh sách = MẢNG TRẦN, mới nhất trước, tối đa 500. */
export const reviewSecretaryGrantListSchema = z.array(reviewSecretaryGrantSchema)
export type ReviewSecretaryGrantList = z.infer<typeof reviewSecretaryGrantListSchema>
