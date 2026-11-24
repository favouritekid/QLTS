/**
 * GĐ2-C C2 — API lựa chọn của Ban thư ký. Máy chủ là chốt quyền (Casbin + `require_review_secretary`: Admin, hoặc Quản lý /
 * Cán bộ có quyền Thư ký còn hiệu lực; không đạt ⇒ 404).
 *
 *   GET /api/admission-config/review-sessions/{session_id}/selections               — lựa chọn hiệu lực của mọi hồ sơ
 *   GET /api/admission-config/review-sessions/{session_id}/selections/{profile_id}  — lịch sử của một hồ sơ (mới trước)
 *   PUT /api/admission-config/review-sessions/{session_id}/selections/{profile_id}  — `{kind, based_on_row_hash, supersedes_id, note}`
 *
 * Mọi phản hồi qua Zod.
 */
import { api } from "@/lib/api/client"
import {
  selectionHistorySchema,
  selectionListSchema,
  selectionPutBodySchema,
  selectionSchema,
  type Selection,
  type SelectionHistory,
  type SelectionList,
  type SelectionPutBody,
} from "@/lib/zod/review-selections"

export const REVIEW_SESSIONS_PATH = "/api/admission-config/review-sessions"

function selectionsPath(sessionId: number): string {
  return `${REVIEW_SESSIONS_PATH}/${sessionId}/selections`
}

export async function listReviewSelections(sessionId: number): Promise<SelectionList> {
  const res = await api.get(selectionsPath(sessionId))
  return selectionListSchema.parse(res.data)
}

export async function getReviewSelectionHistory(sessionId: number, profileId: number): Promise<SelectionHistory> {
  const res = await api.get(`${selectionsPath(sessionId)}/${profileId}`)
  return selectionHistorySchema.parse(res.data)
}

export async function putReviewSelection(
  sessionId: number,
  profileId: number,
  body: SelectionPutBody,
): Promise<Selection> {
  const data = selectionPutBodySchema.parse(body)
  const res = await api.put(`${selectionsPath(sessionId)}/${profileId}`, data)
  return selectionSchema.parse(res.data)
}
