/**
 * GĐ1b — API client duyệt chéo tạm thời (hợp đồng bản 4 §2.2). Mọi phản hồi qua Zod.
 *
 * Nguồn `grant_id` (Codex 68 / 69): `grant_id_by_action` của hàng đợi. Lệnh duyệt gửi `…verify`, lệnh từ chối gửi
 * `…reject`; máy chủ KHÔNG tự đổi sang quyền khác — sai / hết hạn ⇒ 409 `actor_not_authorized`, giao diện làm mới hàng
 * đợi. Giao diện KHÔNG tự chọn quyền từ `eligibility`.
 */
import { api } from "@/lib/api/client"
import {
  crossReviewActionBodySchema,
  crossReviewActionResponseSchema,
  crossReviewEligibilitySchema,
  crossReviewGrantCreateBodySchema,
  crossReviewGrantListSchema,
  crossReviewGrantRevokeBodySchema,
  crossReviewGrantSchema,
  crossReviewQueuePageSchema,
  type CrossReviewActionBody,
  type CrossReviewEligibility,
  type CrossReviewGrant,
  type CrossReviewGrantCreateBody,
  type CrossReviewGrantList,
  type CrossReviewQueuePage,
} from "@/lib/zod/document-review"

export const CROSS_REVIEW_PREFIX = "/api/admissions/cross-review"
const P = CROSS_REVIEW_PREFIX

/** Mọi người đã đăng nhập — CHỈ quyền còn hiệu lực của chính người gọi; `eligible` cho mục thanh bên. */
export async function getCrossReviewEligibility(): Promise<CrossReviewEligibility> {
  const res = await api.get(`${P}/eligibility`)
  return crossReviewEligibilitySchema.parse(res.data)
}

export async function getCrossReviewQueue(cursor?: string | null): Promise<CrossReviewQueuePage> {
  const params: Record<string, string> = {}
  if (cursor) params.cursor = cursor
  const res = await api.get(`${P}/queue`, { params })
  return crossReviewQueuePageSchema.parse(res.data)
}

export async function crossReviewVerify(body: CrossReviewActionBody): Promise<void> {
  const data = crossReviewActionBodySchema.parse(body)
  const res = await api.post(`${P}/verify`, data)
  crossReviewActionResponseSchema.parse(res.data)
}

export async function crossReviewReject(body: CrossReviewActionBody): Promise<void> {
  const data = crossReviewActionBodySchema.parse(body)
  if (!data.reason) throw new Error("Từ chối cần lý do")
  const res = await api.post(`${P}/reject`, data)
  crossReviewActionResponseSchema.parse(res.data)
}

// ── Admin: cấp / thu hồi / xem quyền ──

export interface CrossReviewGrantFilter {
  active?: boolean
  grantee_user_id?: number
  unit_id?: number
}

export async function listCrossReviewGrants(filter: CrossReviewGrantFilter): Promise<CrossReviewGrantList> {
  const params: Record<string, string | number | boolean> = {}
  if (filter.active !== undefined) params.active = filter.active
  if (filter.grantee_user_id !== undefined) params.grantee_user_id = filter.grantee_user_id
  if (filter.unit_id !== undefined) params.unit_id = filter.unit_id
  const res = await api.get(`${P}/grants`, { params })
  return crossReviewGrantListSchema.parse(res.data)
}

export async function createCrossReviewGrant(body: CrossReviewGrantCreateBody): Promise<CrossReviewGrant> {
  const data = crossReviewGrantCreateBodySchema.parse(body)
  const res = await api.post(`${P}/grants`, data)
  return crossReviewGrantSchema.parse(res.data)
}

export async function revokeCrossReviewGrant(grantId: number, reason: string): Promise<CrossReviewGrant> {
  const data = crossReviewGrantRevokeBodySchema.parse({ reason })
  const res = await api.post(`${P}/grants/${grantId}/revoke`, data)
  return crossReviewGrantSchema.parse(res.data)
}
