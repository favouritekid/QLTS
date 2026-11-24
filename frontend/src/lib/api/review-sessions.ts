/**
 * GĐ2-B — API lần xét nháp (hợp đồng API GĐ2-B bản 4, E1–E9; tiền tố `/api/admission-config/review-sessions` — MỘT hằng, dùng
 * chung với route lựa chọn của Ban thư ký C2). Máy chủ là chốt quyền (GĐ2-B: chỉ Admin — Casbin + `require_review_admin`).
 *
 *   E1 POST /review-sessions                                — tạo lần xét nháp
 *   E2 GET  /review-sessions                                — danh sách (năm ↓, số thứ tự ↓)
 *   E3 GET  /review-sessions/{id}                           — chi tiết + điểm sàn + lượt mới nhất + `available_actions`
 *   E4 PUT  /review-sessions/{id}/floors                    — thay TOÀN BỘ điểm sàn
 *   E5 POST /review-sessions/{id}/cancel                    — huỷ (giải phóng sàn, trạng thái cuối)
 *   E6 POST /review-sessions/{id}/runs                      — chạy kiểm hồ sơ (202; GĐ2-B đồng bộ, GĐ2-C có thể chạy nền)
 *   E7 GET  /review-sessions/{id}/runs                      — danh sách lượt kiểm (id ↓)
 *   E8 GET  /review-sessions/{id}/runs/{run_id}             — chi tiết lượt kiểm
 *   E9 GET  /review-sessions/{id}/runs/{run_id}/rows        — dòng kết quả (bốn tab, lọc, phân trang)
 *
 * Mọi thân gửi đi qua Zod `.strict()`; mọi phản hồi qua Zod (bỏ qua trường lạ). Không `console.*`.
 */
import { listRoundsByYear } from "@/lib/api/admission-rounds"
import { api } from "@/lib/api/client"
import { REVIEW_SESSIONS_PATH } from "@/lib/api/review-selections"
import {
  reviewFloorsPutBodySchema,
  reviewRoundListSchema,
  reviewRunCreateBodySchema,
  reviewSessionCancelBodySchema,
  reviewSessionCreateBodySchema,
  rowPageSchema,
  runPageSchema,
  runSchema,
  sessionPageSchema,
  sessionSchema,
  type ReviewFloorsPutBody,
  type ReviewRoundList,
  type ReviewRowPage,
  type ReviewRun,
  type ReviewRunCreateBody,
  type ReviewRunPage,
  type ReviewSession,
  type ReviewSessionCancelBody,
  type ReviewSessionCreateBody,
  type ReviewSessionPage,
} from "@/lib/zod/review-sessions"

export { REVIEW_SESSIONS_PATH }

/**
 * KT-11 / R5: axios không có thời gian chờ mặc định, nginx cắt 60 s ⇒ E6 tự đặt thời gian chờ RIÊNG > 60 s (HĐ4 E6). Hết giờ ⇒
 * lỗi không phản hồi ⇒ màn tra E7 xem lượt đã được ghi chưa (thiết kế §3.5 bước 3), không bấm lại ngay.
 */
export const REVIEW_RUN_TIMEOUT_MS = 90_000

export interface ReviewSessionListParams {
  academic_year?: number
  /** `draft` | `cancelled` (E2 — giá trị khác máy chủ trả 422; GĐ2-C mở rộng). */
  status?: string
  page?: number
  page_size?: number
}

export interface ReviewPageParams {
  page?: number
  page_size?: number
}

export interface ReviewRowParams extends ReviewPageParams {
  tab?: string
  offering_academic_info_id?: number
  reason_code?: string
  flag?: string
}

/** Bỏ khoá không có giá trị — chỉ gửi tham số người dùng đã chọn. */
function definedOnly<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")) as Partial<T>
}

function sessionPath(sessionId: number): string {
  return `${REVIEW_SESSIONS_PATH}/${sessionId}`
}

function runsPath(sessionId: number): string {
  return `${sessionPath(sessionId)}/runs`
}

// ── E1 ──
export async function createReviewSession(body: ReviewSessionCreateBody): Promise<ReviewSession> {
  const data = reviewSessionCreateBodySchema.parse(body)
  const res = await api.post(REVIEW_SESSIONS_PATH, data)
  return sessionSchema.parse(res.data)
}

// ── E2 ──
export async function listReviewSessions(params: ReviewSessionListParams, signal?: AbortSignal): Promise<ReviewSessionPage> {
  const res = await api.get(REVIEW_SESSIONS_PATH, { params: definedOnly(params), signal })
  return sessionPageSchema.parse(res.data)
}

// ── E3 ──
export async function getReviewSession(sessionId: number, signal?: AbortSignal): Promise<ReviewSession> {
  const res = await api.get(sessionPath(sessionId), { signal })
  return sessionSchema.parse(res.data)
}

// ── E4 ──
export async function putReviewFloors(sessionId: number, body: ReviewFloorsPutBody): Promise<ReviewSession> {
  const data = reviewFloorsPutBodySchema.parse(body)
  const res = await api.put(`${sessionPath(sessionId)}/floors`, data)
  return sessionSchema.parse(res.data)
}

// ── E5 ──
export async function cancelReviewSession(sessionId: number, body: ReviewSessionCancelBody): Promise<ReviewSession> {
  const data = reviewSessionCancelBodySchema.parse(body)
  const res = await api.post(`${sessionPath(sessionId)}/cancel`, data)
  return sessionSchema.parse(res.data)
}

// ── E6 ──
export async function createReviewRun(sessionId: number, body: ReviewRunCreateBody): Promise<ReviewRun> {
  const data = reviewRunCreateBodySchema.parse(body)
  const res = await api.post(runsPath(sessionId), data, { timeout: REVIEW_RUN_TIMEOUT_MS })
  return runSchema.parse(res.data)
}

// ── E7 ──
export async function listReviewRuns(sessionId: number, params: ReviewPageParams, signal?: AbortSignal): Promise<ReviewRunPage> {
  const res = await api.get(runsPath(sessionId), { params: definedOnly(params), signal })
  return runPageSchema.parse(res.data)
}

// ── E8 ──
export async function getReviewRun(sessionId: number, runId: number, signal?: AbortSignal): Promise<ReviewRun> {
  const res = await api.get(`${runsPath(sessionId)}/${runId}`, { signal })
  return runSchema.parse(res.data)
}

// ── E9 ──
export async function listReviewRunRows(
  sessionId: number,
  runId: number,
  params: ReviewRowParams,
  signal?: AbortSignal,
): Promise<ReviewRowPage> {
  const res = await api.get(`${runsPath(sessionId)}/${runId}/rows`, { params: definedOnly(params), signal })
  return rowPageSchema.parse(res.data)
}

// ── đợt tuyển sinh của một năm (route có sẵn, cùng hàm với trang Cấu hình tuyển sinh — một chỗ khai đường dẫn) ──
export async function listReviewRounds(academicYear: number): Promise<ReviewRoundList> {
  return reviewRoundListSchema.parse(await listRoundsByYear(academicYear))
}
