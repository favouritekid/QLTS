/**
 * GĐ2-B — React Query cho lần xét nháp (E1–E9).
 *
 * ĐÍNH CHÍNH 2 §1 (DC-1, CHẶN): mọi query mang `config_changed_since_run` — E2 (danh sách), E3 (chi tiết), E7 (danh sách
 * lượt), E8 (chi tiết lượt) — dùng `staleTime: 0` + `gcTime: 0`: cờ ấy máy chủ tính LÚC GET (HĐ4 §3.3), giữ bản cũ là giấu băng
 * "Cấu hình đã đổi" (cấu hình có thể đổi KHÔNG qua thao tác ghi của màn này — vd sửa bảng chỉ tiêu ở thẻ khác). `gcTime: 0` ⇒ rời
 * màn là bản ghi bị gỡ khỏi bộ đệm; quay lại thì hiện "đang tải", KHÔNG vẽ bản cũ trong lúc chờ. E8 KHÔNG `placeholderData`. Tải
 * lỗi (kể cả 429) thì màn hiện LỖI, không vẽ dữ liệu cũ (thành phần đọc `isError` TRƯỚC `data`). Khuôn:
 * `hooks/admin/useCouncilDocuments.ts:319-336`.
 *
 * Thiết kế §6.1 + đính chính 1 / 2 §1: SAU MỌI thao tác ghi (E1, E4, E5, E6, và ghi lựa chọn C2 — `use-review-selections.ts`
 * gọi CÙNG `refreshAfterReviewWrite`) — khi thao tác KẾT THÚC, BẤT KỂ kết quả (thành công,
 * 409, 502 / 504 chưa rõ) — làm mới E2 + E3 + E7 + E8 (`onSettled`, không `onSuccess`).
 *
 * Không tự tải lại khi quay lại cửa sổ (R6 — giới hạn `ADMIN_READ` theo IP); không tự thử lại (người dùng bấm "Tải lại").
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"

import {
  cancelReviewSession,
  createReviewRun,
  createReviewSession,
  getReviewRun,
  getReviewSession,
  listReviewRounds,
  listReviewRunRows,
  listReviewRuns,
  listReviewSessions,
  putReviewFloors,
  type ReviewPageParams,
  type ReviewRowParams,
  type ReviewSessionListParams,
} from "@/lib/api/review-sessions"
import type {
  ReviewFloorsPutBody,
  ReviewRunCreateBody,
  ReviewSessionCancelBody,
  ReviewSessionCreateBody,
} from "@/lib/zod/review-sessions"

export const reviewSessionKeys = {
  all: ["review-sessions"] as const,
  /** E2 — mọi trang / bộ lọc */
  lists: () => [...reviewSessionKeys.all, "list"] as const,
  list: (params: ReviewSessionListParams) => [...reviewSessionKeys.lists(), params] as const,
  session: (sessionId: number) => [...reviewSessionKeys.all, "session", sessionId] as const,
  /** E3 */
  detail: (sessionId: number) => [...reviewSessionKeys.session(sessionId), "detail"] as const,
  /** E7 — mọi trang */
  runLists: (sessionId: number) => [...reviewSessionKeys.session(sessionId), "runs"] as const,
  runList: (sessionId: number, params: ReviewPageParams) => [...reviewSessionKeys.runLists(sessionId), params] as const,
  /** E8 — mọi lượt của lần xét */
  runDetails: (sessionId: number) => [...reviewSessionKeys.session(sessionId), "run"] as const,
  runDetail: (sessionId: number, runId: number) => [...reviewSessionKeys.runDetails(sessionId), runId] as const,
  /** E9 */
  rows: (sessionId: number, runId: number, params: ReviewRowParams) =>
    [...reviewSessionKeys.session(sessionId), "rows", runId, params] as const,
  /** đợt tuyển sinh của một năm (hộp "Tạo lần xét") */
  roundLists: () => [...reviewSessionKeys.all, "rounds"] as const,
  rounds: (academicYear: number) => [...reviewSessionKeys.roundLists(), academicYear] as const,
}

/**
 * DC-1 — tuỳ chọn CHUNG cho E2 / E3 / E7 / E8 (MỘT chỗ; test mức hook khoá từng query). Không `placeholderData` ở đây: đổi khoá
 * (trang, bộ lọc, lượt khác) ⇒ "đang tải", không mượn dữ liệu của khoá khác.
 */
export const FRESH_ONLY_QUERY_OPTIONS = {
  staleTime: 0,
  gcTime: 0,
  retry: false,
  refetchOnWindowFocus: false,
} as const

// ═══════════════════════════════════════ đọc ═══════════════════════════════════════
/** E2 */
export function useReviewSessionList(params: ReviewSessionListParams, enabled = true) {
  return useQuery({
    queryKey: reviewSessionKeys.list(params),
    queryFn: ({ signal }) => listReviewSessions(params, signal),
    enabled,
    ...FRESH_ONLY_QUERY_OPTIONS,
  })
}

/** E3 */
export function useReviewSession(sessionId: number, enabled = true) {
  return useQuery({
    queryKey: reviewSessionKeys.detail(sessionId),
    queryFn: ({ signal }) => getReviewSession(sessionId, signal),
    enabled,
    ...FRESH_ONLY_QUERY_OPTIONS,
  })
}

/** E7 */
export function useReviewRuns(sessionId: number, params: ReviewPageParams, enabled = true) {
  return useQuery({
    queryKey: reviewSessionKeys.runList(sessionId, params),
    queryFn: ({ signal }) => listReviewRuns(sessionId, params, signal),
    enabled,
    ...FRESH_ONLY_QUERY_OPTIONS,
  })
}

/** E8 — KHÔNG `placeholderData` (đính chính 2 §1). */
export function useReviewRun(sessionId: number, runId: number, enabled = true) {
  return useQuery({
    queryKey: reviewSessionKeys.runDetail(sessionId, runId),
    queryFn: ({ signal }) => getReviewRun(sessionId, runId, signal),
    enabled,
    ...FRESH_ONLY_QUERY_OPTIONS,
  })
}

/**
 * E9 — dòng của lượt kiểm. KHÔNG mang `config_changed_since_run` (băng ấy đọc từ E8). Dòng của lượt đã xong là bất biến trừ
 * họ tên / đơn vị (HĐ4 §7) ⇒ giữ trang cũ khi lật trang cho bảng khỏi nháy (thiết kế §6.1). Đợt F4 chốt lại tuỳ chọn này.
 */
export function useReviewRunRows(sessionId: number, runId: number, params: ReviewRowParams, enabled = true) {
  return useQuery({
    queryKey: reviewSessionKeys.rows(sessionId, runId, params),
    queryFn: ({ signal }) => listReviewRunRows(sessionId, runId, params, signal),
    enabled,
    staleTime: 2 * 60 * 1000,
    retry: false,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
  })
}

/** Đợt tuyển sinh của một năm (hộp "Tạo lần xét"). `academicYear === null` ⇒ không gọi. */
export function useReviewRounds(academicYear: number | null) {
  return useQuery({
    queryKey: reviewSessionKeys.rounds(academicYear ?? 0),
    queryFn: () => {
      if (academicYear === null) throw new Error("Chưa chọn năm.")
      return listReviewRounds(academicYear)
    },
    enabled: academicYear !== null,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

// ═══════════════════════════════════════ ghi ═══════════════════════════════════════
/**
 * Làm mới sau MỘT thao tác ghi — gọi ở `onSettled` (bất kể kết quả). Không chờ: refetch treo không được giữ nút ở trạng thái
 * "đang gửi" (màn khoá nút ghi trong lúc E3 đang tải lại để thao tác kế dùng `version` mới nhất).
 */
export function refreshAfterReviewWrite(queryClient: QueryClient, sessionId: number | null): void {
  void queryClient.invalidateQueries({ queryKey: reviewSessionKeys.lists() })
  if (sessionId === null) return
  void queryClient.invalidateQueries({ queryKey: reviewSessionKeys.detail(sessionId) })
  void queryClient.invalidateQueries({ queryKey: reviewSessionKeys.runLists(sessionId) })
  void queryClient.invalidateQueries({ queryKey: reviewSessionKeys.runDetails(sessionId) })
}

/** E1. Đợt có thể vừa đổi (400 `review_round_invalid`) ⇒ làm mới cả danh sách đợt. */
export function useCreateReviewSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReviewSessionCreateBody) => createReviewSession(body),
    retry: false,
    gcTime: 0,
    onSettled: () => {
      refreshAfterReviewWrite(queryClient, null)
      void queryClient.invalidateQueries({ queryKey: reviewSessionKeys.roundLists() })
    },
  })
}

/** E4 */
export function usePutReviewFloors(sessionId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReviewFloorsPutBody) => putReviewFloors(sessionId, body),
    retry: false,
    gcTime: 0,
    onSettled: () => refreshAfterReviewWrite(queryClient, sessionId),
  })
}

/** E5. `gcTime: 0` ⇒ lý do huỷ không nằm lại trong MutationCache. */
export function useCancelReviewSession(sessionId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReviewSessionCancelBody) => cancelReviewSession(sessionId, body),
    retry: false,
    gcTime: 0,
    onSettled: () => refreshAfterReviewWrite(queryClient, sessionId),
  })
}

/** E6 */
export function useCreateReviewRun(sessionId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReviewRunCreateBody) => createReviewRun(sessionId, body),
    retry: false,
    gcTime: 0,
    onSettled: () => refreshAfterReviewWrite(queryClient, sessionId),
  })
}
