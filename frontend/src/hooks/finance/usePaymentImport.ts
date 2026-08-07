/**
 * React Query hooks — Import file thu học phí hàng loạt (BV-4).
 *
 * @see lib/api/payment-import.ts
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { AxiosError, isAxiosError } from "axios"
import { toast } from "sonner"

import { paymentImportApi } from "@/lib/api/payment-import"
import { blobErrorMessage, downloadBlob } from "@/lib/utils/download-blob"
import type {
  PaymentImportCommit,
  PaymentImportPreview,
  PaymentImportVoidResult,
} from "@/lib/zod/payment-import"
import type { ApiErrorResponse } from "@/types/api.types"

// ============================================================================
// QUERY KEYS
// ============================================================================
export const paymentImportKeys = {
  all: ["payment-import"] as const,
  batches: (page: number, pageSize: number) =>
    [...paymentImportKeys.all, "batches", page, pageSize] as const,
  detail: (batchId: number) =>
    [...paymentImportKeys.all, "detail", batchId] as const,
}

function errMsg(error: unknown, fallback: string): string {
  if (isAxiosError(error)) {
    const detail = (error.response?.data as ApiErrorResponse | undefined)?.detail
    return typeof detail === "string" ? detail : fallback
  }
  // ZodError (contract drift) / lỗi khác → log cho dev, user thấy fallback rõ
  console.error("[payment-import] unexpected error", error)
  return fallback
}

// ============================================================================
// LỊCH SỬ LÔ (list)
// ============================================================================
export function usePaymentImportBatches(page: number, pageSize: number) {
  return useQuery({
    queryKey: paymentImportKeys.batches(page, pageSize),
    queryFn: () => paymentImportApi.listBatches(page, pageSize),
    staleTime: 30_000,
    placeholderData: keepPreviousData, // đổi trang → giữ data cũ, không nháy spinner
  })
}

// ============================================================================
// TẢI FILE MẪU (download blob → trigger browser save)
// ============================================================================
export function useDownloadPaymentImportTemplate() {
  return useMutation<Blob, AxiosError<ApiErrorResponse>, "xlsx" | "csv">({
    mutationFn: (format) => paymentImportApi.downloadTemplate(format),
    onSuccess: (blob, format) =>
      downloadBlob(blob, `mau_import_thu_hoc_phi.${format}`),
    onError: async (error) =>
      toast.error(await blobErrorMessage(error, "Không tải được file mẫu")),
  })
}

// ============================================================================
// PHA 1 — PREVIEW (dry-run)
// ============================================================================
export function usePreviewPaymentImport() {
  return useMutation<
    PaymentImportPreview,
    AxiosError<ApiErrorResponse>,
    { file: File; academicYear: number; semesterNo: number }
  >({
    mutationFn: (vars) => paymentImportApi.preview(vars),
    onError: (error) =>
      toast.error(errMsg(error, "Không xem trước được file import")),
  })
}

// ============================================================================
// PHA 2 — COMMIT (ghi tiền)
// ============================================================================
/**
 * Ghi tiền cho lô.
 *
 * `confirmedRows` chỉ gửi những dòng kế toán đã đọc và
 * khẳng định đó là những khoản thu riêng. Máy chủ giữ lô ở trạng thái xem
 * trước khi còn dòng bị chặn, nên lượt gửi lại này là đường DUY NHẤT để chúng
 * vào sổ; không có nó thì tiền đã thu thật bị kẹt ngoài hệ thống.
 */
export function useCommitPaymentImport() {
  const queryClient = useQueryClient()
  return useMutation<
    PaymentImportCommit,
    AxiosError<ApiErrorResponse>,
    | {
        batchId: number
        confirmedRows?: Array<{ row_no: number; review_token: string }>
      }
    | number
  >({
    mutationFn: (bien) =>
      typeof bien === "number"
        ? paymentImportApi.commit(bien)
        : paymentImportApi.commit(bien.batchId, bien.confirmedRows),
    onSuccess: (result) => {
      toast.success(
        `Đã ghi ${result.committed_count} dòng` +
          (result.failed_count > 0 ? `, ${result.failed_count} lỗi` : "") +
          // Dòng chờ xác nhận KHÔNG phải dòng lỗi: chúng đòi hai hành động
          // khác nhau, nên gộp vào một con số là buộc kế toán đoán.
          (result.review_required_count > 0
            ? `, ${result.review_required_count} dòng chờ xác nhận trùng`
            : ""),
      )
      // return → mutation pending tới khi cache refetch xong (tránh thao tác tiếp
      // trên dữ liệu cũ; convention await-invalidate của repo).
      return queryClient.invalidateQueries({ queryKey: paymentImportKeys.all })
    },
    onError: (error) => toast.error(errMsg(error, "Không ghi được tiền lô import")),
  })
}

// ============================================================================
// VOID (đảo lô) — manager/admin
// ============================================================================
export function useVoidPaymentImport() {
  const queryClient = useQueryClient()
  return useMutation<
    PaymentImportVoidResult,
    AxiosError<ApiErrorResponse>,
    { batchId: number; reason: string }
  >({
    mutationFn: ({ batchId, reason }) =>
      paymentImportApi.voidBatch(batchId, reason),
    onSuccess: (result) => {
      toast.success(`Đã đảo lô — rút lại ${result.reversed_count} khoản`)
      // return → mutation pending tới khi cache refetch xong: dòng History hết stale
      // can_void → chặn double-void (409). Convention await-invalidate của repo.
      return queryClient.invalidateQueries({ queryKey: paymentImportKeys.all })
    },
    onError: (error) => toast.error(errMsg(error, "Không đảo được lô import")),
  })
}

// ============================================================================
// BV-5 R2 — chi tiết lô (per-row) · R1 — tải file kết quả
// ============================================================================
export function usePaymentImportBatchDetail(batchId: number, enabled: boolean) {
  return useQuery({
    queryKey: paymentImportKeys.detail(batchId),
    queryFn: () => paymentImportApi.getBatchDetail(batchId),
    enabled,
    staleTime: 30_000,
  })
}

export function useDownloadPaymentImportResult() {
  return useMutation<
    Blob,
    AxiosError<ApiErrorResponse>,
    { batchId: number; format: "xlsx" | "csv" }
  >({
    mutationFn: ({ batchId, format }) =>
      paymentImportApi.downloadResult(batchId, format),
    onSuccess: (blob, { batchId, format }) =>
      downloadBlob(blob, `ket_qua_import_lo_${batchId}.${format}`),
    onError: async (error) =>
      toast.error(await blobErrorMessage(error, "Không tải được file kết quả")),
  })
}
