/**
 * GĐ1b §5.9 — hook lô duyệt giấy (xem trước / chạy / tra / chốt / danh sách) cho cả đường Quản lý / Admin và đường
 * duyệt chéo.
 *
 * Bất biến của tệp này:
 *  - `execute` có `retry: false` và KHÔNG hook / effect nào gọi lại nó — mất phản hồi ⇒ thành phần chuyển sang TRA lô
 *    (`useBatch`, chỉ `GET`). Test `BulkVerifyFlow.test.tsx` khoá "đúng một lần gọi execute".
 *  - `batch_id` ghi vào `sessionStorage` NGAY khi nhận phản hồi xem trước (§5.2) — chỉ `batch_id`.
 *  - Lô kết thúc ⇒ làm mới danh sách, bộ đếm, chi tiết các hồ sơ trong lô — cả khi chính tab này thấy lô kết thúc
 *    (`execute` / tra lô) lẫn khi nhận sự kiện socket `bulk_verify_finished` (bản 6 C2.3, `onBulkVerifyFinished`).
 *  - Cờ quyền chạy lô (bản 6 C1) đọc từ máy chủ (`useBulkVerifyEligibility`) — lỗi / đang tải ⇒ coi như KHÔNG có quyền.
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
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import {
  executeBatch,
  finalizeBatch,
  getBatch,
  getBulkVerifyEligibility,
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
import { bulkVerifyFinishedEventSchema, type BatchListScope, type BatchView } from "@/lib/zod/document-review"

// Thành phần lấy kiểu đường lô qua hook (kiến trúc 2.6.2: thành phần không nhập tầng API).
export type { BulkEndpoint, BulkSelection }

export const bulkVerifyKeys = {
  all: ["document-bulk-verify"] as const,
  eligibility: () => [...bulkVerifyKeys.all, "eligibility"] as const,
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

/**
 * Bản 6 C1 — cờ quyền chạy lô của chính người gọi (mục thanh bên "Lô duyệt giấy", nút "Duyệt giấy theo bộ lọc hiện tại").
 * Người dùng: chỉ hiện khi `isSuccess && data.eligible === true`; đang tải / lỗi mạng / 4xx / 5xx ⇒ ẩn (fail-closed).
 */
export function useBulkVerifyEligibility(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: bulkVerifyKeys.eligibility(),
    queryFn: getBulkVerifyEligibility,
    enabled: options?.enabled ?? true,
    staleTime: 60_000,
    retry: noRetryOn4xx,
  })
}

const isNotAllowed = (e: unknown) =>
  axios.isAxiosError(e) && (e.response?.status === 403 || e.response?.status === 404)

/**
 * Bản 6 C2.3 — xử lý sự kiện socket `bulk_verify_finished {batch_id}` (máy chủ phát tới phòng của NGƯỜI TẠO sau commit
 * cuối). CHỈ làm mới / đọc (GET) — không gửi lại lệnh nào:
 *  1. danh sách hồ sơ, bộ đếm trạng thái, danh sách lô (cả hai đường), hàng đợi chéo;
 *  2. bảng tra của chính lô ấy nếu đang mở (cả hai đường);
 *  3. chi tiết các hồ sơ thuộc lô — `profile_id` lấy từ `GET` lô. Sự kiện không mang đường lô ⇒ đọc đường lô trong
 *     cache nếu có, không thì thử đường Quản lý / Admin rồi đường chéo (403 / 404 ⇒ đường kia).
 * Payload sai dạng ⇒ bỏ qua.
 */
export async function onBulkVerifyFinished(queryClient: QueryClient, payload: unknown): Promise<void> {
  const ev = bulkVerifyFinishedEventSchema.safeParse(payload)
  if (!ev.success) return
  const batchId = ev.data.batch_id

  void queryClient.invalidateQueries({ queryKey: admissionsKeys.lists() })
  void queryClient.invalidateQueries({ queryKey: [...admissionsKeys.all, "status-counts"] })
  void queryClient.invalidateQueries({ queryKey: bulkVerifyKeys.lists("batch") })
  void queryClient.invalidateQueries({ queryKey: bulkVerifyKeys.lists("cross") })
  void queryClient.invalidateQueries({ queryKey: CROSS_REVIEW_QUEUE_KEY })
  void queryClient.invalidateQueries({ queryKey: bulkVerifyKeys.batch("batch", batchId) })
  void queryClient.invalidateQueries({ queryKey: bulkVerifyKeys.batch("cross", batchId) })

  const modes: BulkEndpoint["mode"][] =
    queryClient.getQueryData(bulkVerifyKeys.batch("cross", batchId)) !== undefined ? ["cross", "batch"] : ["batch", "cross"]
  for (const mode of modes) {
    try {
      const view = await getBatch({ mode }, batchId)
      invalidateAfterDocumentChange(
        queryClient,
        view.items.map((i) => i.profile_id),
      )
      return
    } catch (e) {
      if (!isNotAllowed(e)) return // lỗi mạng / 5xx: danh sách + bộ đếm đã làm mới ở trên; không thử thêm
    }
  }
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
