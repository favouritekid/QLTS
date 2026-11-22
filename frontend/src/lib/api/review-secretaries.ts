/**
 * GĐ2-C C1 — API quyền "Thư ký Hội đồng". Chỉ Admin (máy chủ là chốt: Casbin + `require_review_secretary_admin`).
 *
 *   GET  /api/admission-config/review-secretaries                     — `?active=` `?user_id=`; mới nhất trước
 *   POST /api/admission-config/review-secretaries                     — `{user_id, reason}`
 *   POST /api/admission-config/review-secretaries/{grant_id}/revoke   — `{reason}`
 *
 * Mọi phản hồi qua Zod.
 */
import { api } from "@/lib/api/client"
import {
  reviewSecretaryGrantCreateBodySchema,
  reviewSecretaryGrantListSchema,
  reviewSecretaryGrantRevokeBodySchema,
  reviewSecretaryGrantSchema,
  type ReviewSecretaryGrant,
  type ReviewSecretaryGrantCreateBody,
  type ReviewSecretaryGrantList,
} from "@/lib/zod/review-secretaries"

export const REVIEW_SECRETARIES_PATH = "/api/admission-config/review-secretaries"
const P = REVIEW_SECRETARIES_PATH

export interface ReviewSecretaryGrantFilter {
  active?: boolean
  user_id?: number
}

export async function listReviewSecretaryGrants(filter: ReviewSecretaryGrantFilter): Promise<ReviewSecretaryGrantList> {
  const params: Record<string, string | number | boolean> = {}
  if (filter.active !== undefined) params.active = filter.active
  if (filter.user_id !== undefined) params.user_id = filter.user_id
  const res = await api.get(P, { params })
  return reviewSecretaryGrantListSchema.parse(res.data)
}

export async function createReviewSecretaryGrant(body: ReviewSecretaryGrantCreateBody): Promise<ReviewSecretaryGrant> {
  const data = reviewSecretaryGrantCreateBodySchema.parse(body)
  const res = await api.post(P, data)
  return reviewSecretaryGrantSchema.parse(res.data)
}

export async function revokeReviewSecretaryGrant(grantId: number, reason: string): Promise<ReviewSecretaryGrant> {
  const data = reviewSecretaryGrantRevokeBodySchema.parse({ reason })
  const res = await api.post(`${P}/${grantId}/revoke`, data)
  return reviewSecretaryGrantSchema.parse(res.data)
}
