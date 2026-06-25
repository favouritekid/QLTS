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
    onSuccess: (blob, format) => {
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `mau_import_thu_hoc_phi.${format}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    },
    onError: async (error) => {
      // responseType:'blob' → body lỗi (JSON) bị bọc thành Blob → đọc text để lấy
      // detail thật thay vì luôn fallback.
      let msg = "Không tải được file mẫu"
      const data = error.response?.data as unknown
      if (data instanceof Blob) {
        try {
          const parsed = JSON.parse(await data.text())
          if (typeof parsed?.detail === "string") msg = parsed.detail
        } catch {
          /* blob không phải JSON → giữ fallback */
        }
      } else {
        msg = errMsg(error, msg)
      }
      toast.error(msg)
    },
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
export function useCommitPaymentImport() {
  const queryClient = useQueryClient()
  return useMutation<PaymentImportCommit, AxiosError<ApiErrorResponse>, number>({
    mutationFn: (batchId) => paymentImportApi.commit(batchId),
    onSuccess: (result) => {
      toast.success(
        `Đã ghi ${result.committed_count} dòng` +
          (result.failed_count > 0 ? `, ${result.failed_count} lỗi` : ""),
      )
      queryClient.invalidateQueries({ queryKey: paymentImportKeys.all })
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
      queryClient.invalidateQueries({ queryKey: paymentImportKeys.all })
    },
    onError: (error) => toast.error(errMsg(error, "Không đảo được lô import")),
  })
}
