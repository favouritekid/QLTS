/**
 * GĐ1b §5.9 — hook lô duyệt giấy (xem trước / chạy / tra / chốt / danh sách) cho cả đường Quản lý / Admin và đường
 * duyệt chéo.
 *
 * Bất biến của tệp này:
 *  - `execute` có `retry: false` và KHÔNG hook / effect nào gọi lại nó — mất phản hồi ⇒ thành phần chuyển sang TRA lô
 *    (`useBatch`, chỉ `GET`). Test `BulkVerifyFlow.test.tsx` khoá "đúng một lần gọi execute".
 *  - `batch_id` ghi vào `sessionStorage` NGAY khi nhận phản hồi xem trước (§5.2) — chỉ `batch_id`.
 *  - Lô kết thúc ⇒ làm mới danh sách, bộ đếm, chi tiết các hồ sơ trong lô (thay cho sự kiện socket
 *    `bulk_verify_finished` cho tới khi socket được nối — việc nối nằm ở khung chung, chờ biên bản V4).
 */
import { useSyncExternalStore } from "react"
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"
import axios from "axios"

import { useHasMounted } from "@/hooks/useHasMounted"
import { invalidateAfterDocumentChange } from "@/hooks/document-review/useDocumentReview"
import {
  executeBatch,
  finalizeBatch,
  getBatch,
  listBatches,
  previewBulkVerify,
  type BulkEndpoint,
  type BulkSelection,
} from "@/lib/api/document-bulk"
import {
  clearLastBatchId,
  readLastBatchId,
  saveLastBatchId,
  subscribeLastBatchId,
} from "@/lib/document-review/batch-session"
import { batchPollInterval, TERMINAL_BATCH_STATUSES } from "@/lib/document-review/messages"
import type { BatchListScope, BatchView } from "@/lib/zod/document-review"

export const bulkVerifyKeys = {
  all: ["document-bulk-verify"] as const,
  batches: (mode: BulkEndpoint["mode"]) => [...bulkVerifyKeys.all, mode, "batch"] as const,
  batch: (mode: BulkEndpoint["mode"], batchId: string | null) => [...bulkVerifyKeys.batches(mode), batchId] as const,
  lists: (mode: BulkEndpoint["mode"]) => [...bulkVerifyKeys.all, mode, "list"] as const,
  list: (mode: BulkEndpoint["mode"], scope: BatchListScope) => [...bulkVerifyKeys.lists(mode), scope] as const,
}

/** Khoá hàng đợi duyệt chéo — khai ở đây để lô chéo làm mới được mà không vòng import. */
export const CROSS_REVIEW_QUEUE_KEY = ["cross-review", "queue"] as const

/** Lô kết thúc ⇒ dữ liệu giấy của các hồ sơ trong lô đã đổi. */
export function invalidateAfterBatch(queryClient: QueryClient, mode: BulkEndpoint["mode"], view: BatchView): void {
  invalidateAfterDocumentChange(
    queryClient,
    view.items.map((i) => i.profile_id),
  )
  void queryClient.invalidateQueries({ queryKey: bulkVerifyKeys.lists(mode) })
  if (mode === "cross") void queryClient.invalidateQueries({ queryKey: CROSS_REVIEW_QUEUE_KEY })
}

function noRetryOn4xx(failureCount: number, error: unknown): boolean {
  if (axios.isAxiosError(error) && error.response && error.response.status < 500) return false
  return failureCount < 2
}

export interface PreviewVariables {
  selection: BulkSelection
  includeOptional: boolean
}

export function usePreviewBulkVerify(endpoint: BulkEndpoint) {
  return useMutation({
    mutationFn: ({ selection, includeOptional }: PreviewVariables) =>
      previewBulkVerify(endpoint, selection, includeOptional),
    retry: false,
    gcTime: 0,
    // §5.2: lưu `batch_id` NGAY khi nhận phản hồi (trước khi người dùng bấm "Duyệt")
    onSuccess: (preview) => saveLastBatchId(preview.batch_id),
  })
}

export interface ExecuteVariables {
  batchId: string
  confirmationText: string
}

export function useExecuteBatch(endpoint: BulkEndpoint) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ batchId, confirmationText }: ExecuteVariables) =>
      executeBatch(endpoint, batchId, confirmationText),
    // KHÔNG BAO GIỜ gửi lại `execute` tự động (§5.9)
    retry: false,
    gcTime: 0,
    onSuccess: (view) => {
      queryClient.setQueryData(bulkVerifyKeys.batch(endpoint.mode, view.batch_id), view)
      if (TERMINAL_BATCH_STATUSES.has(view.status)) invalidateAfterBatch(queryClient, endpoint.mode, view)
    },
  })
}

/** Tra một lô — chỉ `GET`; hỏi lại 3 s rồi 10 s khi `starting` / `running` / `unknown`. */
export function useBatch(endpoint: BulkEndpoint, batchId: string | null) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: bulkVerifyKeys.batch(endpoint.mode, batchId),
    queryFn: async () => {
      if (!batchId) throw new Error("Thiếu mã lô")
      const view = await getBatch(endpoint, batchId)
      if (TERMINAL_BATCH_STATUSES.has(view.status)) invalidateAfterBatch(queryClient, endpoint.mode, view)
      return view
    },
    enabled: batchId !== null,
    staleTime: 0,
    refetchInterval: (query) => batchPollInterval(query.state.data?.status, query.state.dataUpdateCount),
    retry: noRetryOn4xx,
  })
}

export interface FinalizeVariables {
  batchId: string
  reason?: string
}

export function useFinalizeBatch(endpoint: BulkEndpoint) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ batchId, reason }: FinalizeVariables) => finalizeBatch(endpoint, batchId, reason),
    retry: false,
    gcTime: 0,
    onSuccess: (res) => {
      queryClient.setQueryData(bulkVerifyKeys.batch(endpoint.mode, res.batch.batch_id), res.batch)
      invalidateAfterBatch(queryClient, endpoint.mode, res.batch)
    },
  })
}

export function useBatchList(endpoint: BulkEndpoint, scope: BatchListScope, enabled = true) {
  return useInfiniteQuery({
    queryKey: bulkVerifyKeys.list(endpoint.mode, scope),
    queryFn: ({ pageParam }) => listBatches(endpoint, scope, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
    staleTime: 0,
    retry: noRetryOn4xx,
  })
}

const serverNull = () => null

/**
 * `batch_id` của lô gần nhất trong tab — đọc SAU khi mount (`useHasMounted`): lần vẽ đầu ở trình duyệt trùng HTML máy
 * chủ (cùng `null`), tránh lỗi lệch hydrate #418.
 */
export function useLastBatchId(): { batchId: string | null; forget: () => void } {
  const mounted = useHasMounted()
  const stored = useSyncExternalStore(subscribeLastBatchId, readLastBatchId, serverNull)
  return { batchId: mounted ? stored : null, forget: clearLastBatchId }
}
