/**
 * React Query Hooks for Invoice Management
 *
 * @see lib/api/invoices.ts
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { invoicesApi, type InvoicePaginatedResponse } from "@/lib/api/invoices"
import type { ApiErrorResponse } from "@/types/api.types"
import type {
  Invoice,
  InvoiceDetail,
  InvoiceFilters,
  InvoicePenaltyRequest,
  InvoiceStatusCountFilters,
  InvoiceStatusCounts,
  VietQRResponse,
} from "@/types/finance.types"
import { feesKeys } from "./useFees"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const invoicesKeys = {
  all: ["invoices"] as const,
  lists: () => [...invoicesKeys.all, "list"] as const,
  list: (filters?: InvoiceFilters) => [...invoicesKeys.lists(), filters] as const,
  statusCounts: (filters?: InvoiceStatusCountFilters) =>
    [...invoicesKeys.all, "status-counts", filters ?? {}] as const,
  details: () => [...invoicesKeys.all, "detail"] as const,
  detail: (id: number) => [...invoicesKeys.details(), id] as const,
  vietqr: (id: number) => [...invoicesKeys.detail(id), "vietqr"] as const,
  byFee: (feeId: number) => [...invoicesKeys.all, "by-fee", feeId] as const,
}

// =====================================================================
// QUERY INVALIDATION HELPERS
// =====================================================================

type InvoiceInvalidationOptions = {
  detail?: boolean
  lists?: boolean
  byFee?: number
  feeDetail?: number
  dashboard?: boolean
}

const invalidateInvoiceQueries = async (
  queryClient: ReturnType<typeof useQueryClient>,
  invoiceId: number,
  options: InvoiceInvalidationOptions = {}
) => {
  const {
    detail = true,
    lists = true,
    byFee,
    feeDetail,
    dashboard = true,
  } = options

  const invalidations: Promise<void>[] = []

  if (detail) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: invoicesKeys.detail(invoiceId) })
    )
  }
  if (lists) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: invoicesKeys.lists(),
        refetchType: "active",
      })
    )
    // Workspace tab counts + metric chips derive from the same list state →
    // invalidate the status-counts prefix so they don't drift after a status/
    // amount change. Prefix (no filter arg) matches every cached filter variant.
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: [...invoicesKeys.all, "status-counts"],
        refetchType: "active",
      })
    )
  }
  if (byFee) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: invoicesKeys.byFee(byFee) })
    )
  }
  if (feeDetail) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: feesKeys.detail(feeDetail) })
    )
  }
  if (dashboard) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    )
  }
  // PR2: refresh the collection drawer (a profile's fees + invoices + payments)
  // after any invoice mutation — the prefix matches every open collection.
  invalidations.push(
    queryClient.invalidateQueries({
      queryKey: [...feesKeys.all, "collection"],
      refetchType: "active",
    })
  )

  return Promise.all(invalidations)
}

// =====================================================================
// QUERIES (READ)
// =====================================================================

/**
 * Get paginated invoices list with optional filters
 *
 * @param filters - Filter parameters
 * @param options - Query options
 *
 * @example
 * ```tsx
 * const { data, isLoading } = useInvoices({ status: 'issued', overdue_only: true })
 * ```
 */
export function useInvoices(
  filters?: InvoiceFilters,
  options?: { initialData?: InvoicePaginatedResponse; enabled?: boolean }
) {
  return useQuery<InvoicePaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: invoicesKeys.list(filters),
    queryFn: () => invoicesApi.getInvoices(filters),
    staleTime: 1000 * 30, // 30 seconds
    gcTime: 1000 * 60 * 5, // 5 minutes
    initialData: options?.initialData,
    // Keep the previous page's rows visible while a new filter/page fetches
    // (isFetching drives an opacity dim) instead of flashing the full-page
    // skeleton. Mirrors useAdmissions. isLoading stays true only on first load.
    placeholderData: keepPreviousData,
    enabled: options?.enabled ?? true,
  })
}

/**
 * Get invoice tab status counts (per-enum + overdue_derived + total).
 *
 * @param filters - Context filters (fee_id, fee_type, search); NOT status/page.
 *
 * @example
 * ```tsx
 * const { data: counts } = useInvoiceStatusCounts({ search: "Nguyễn" })
 * ```
 */
export function useInvoiceStatusCounts(
  filters?: InvoiceStatusCountFilters,
  options?: { enabled?: boolean }
) {
  return useQuery<InvoiceStatusCounts, AxiosError<ApiErrorResponse>>({
    queryKey: invoicesKeys.statusCounts(filters),
    queryFn: () => invoicesApi.getInvoiceStatusCounts(filters),
    staleTime: 1000 * 30,
    gcTime: 1000 * 60 * 5,
    enabled: options?.enabled ?? true,
  })
}

/**
 * Get a single invoice by ID with full details
 *
 * @param id - Invoice ID
 * @param options - Query options
 *
 * @example
 * ```tsx
 * const { data: invoice, isLoading } = useInvoiceDetail(123)
 * ```
 */
export function useInvoiceDetail(
  id: number,
  options?: {
    enabled?: boolean
    initialData?: InvoiceDetail
    /**
     * Ghi đè độ tươi. Mặc định 30 giây là đủ cho màn xem, nhưng chỗ nào lấy số
     * dư ra để QUYẾT ĐỊNH — form ghi tiền — phải truyền 0: trang cha dùng
     * chung query key này, nên dialog mở lại trong 30 giây sẽ đọc lại đúng bản
     * cache đã cũ. Ca hỏng: người khác vừa duyệt phiếu, hàng đợi chờ duyệt
     * (staleTime 0) đã trống, còn "còn phải thu" vẫn là số trước khi duyệt —
     * hai nửa của cùng một panel nói hai thời điểm khác nhau.
     */
    staleTime?: number
  }
) {
  return useQuery<InvoiceDetail, AxiosError<ApiErrorResponse>>({
    queryKey: invoicesKeys.detail(id),
    queryFn: () => invoicesApi.getInvoice(id),
    enabled: (options?.enabled ?? true) && !!id,
    initialData: options?.initialData,
    staleTime: options?.staleTime ?? 1000 * 30,
  })
}

/**
 * Get invoices by fee ID
 *
 * @param feeId - Fee ID
 *
 * @example
 * ```tsx
 * const { data: invoices } = useInvoicesByFee(456)
 * ```
 */
export function useInvoicesByFee(feeId: number, options?: { enabled?: boolean }) {
  return useQuery<Invoice[], AxiosError<ApiErrorResponse>>({
    queryKey: invoicesKeys.byFee(feeId),
    queryFn: () => invoicesApi.getInvoicesByFee(feeId),
    enabled: (options?.enabled ?? true) && !!feeId,
    staleTime: 1000 * 30,
  })
}

export function useInvoiceVietQR(invoiceId: number, options?: { enabled?: boolean }) {
  return useQuery<VietQRResponse, AxiosError<ApiErrorResponse>>({
    queryKey: invoicesKeys.vietqr(invoiceId),
    queryFn: () => invoicesApi.getInvoiceVietQR(invoiceId),
    enabled: (options?.enabled ?? true) && !!invoiceId,
    staleTime: 1000 * 60,
  })
}

// =====================================================================
// MUTATIONS (WRITE)
// =====================================================================

/**
 * Issue an invoice (draft → issued)
 *
 * @example
 * ```tsx
 * const { mutate: issueInvoice, isPending } = useIssueInvoice()
 *
 * issueInvoice({ invoiceId: 123, feeId: 456 })
 * ```
 */
export function useIssueInvoice() {
  const queryClient = useQueryClient()

  return useMutation<
    Invoice,
    AxiosError<ApiErrorResponse>,
    { invoiceId: number; feeId: number }
  >({
    mutationFn: ({ invoiceId }) => invoicesApi.issueInvoice(invoiceId),
    onSuccess: (invoice, { feeId }) => {
      toast.success("Đã xuất hóa đơn thành công")
      invalidateInvoiceQueries(queryClient, invoice.id, {
        byFee: feeId,
        feeDetail: feeId,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể xuất hóa đơn. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

/**
 * Cancel an invoice
 *
 * @example
 * ```tsx
 * const { mutate: cancelInvoice, isPending } = useCancelInvoice()
 *
 * cancelInvoice({ invoiceId: 123, feeId: 456, reason: 'Nhập sai thông tin' })
 * ```
 */
export function useCancelInvoice() {
  const queryClient = useQueryClient()

  return useMutation<
    Invoice,
    AxiosError<ApiErrorResponse>,
    { invoiceId: number; feeId: number; reason: string }
  >({
    mutationFn: ({ invoiceId, reason }) => invoicesApi.cancelInvoice(invoiceId, reason),
    onSuccess: (invoice, { feeId }) => {
      toast.success("Đã hủy hóa đơn thành công")
      invalidateInvoiceQueries(queryClient, invoice.id, {
        byFee: feeId,
        feeDetail: feeId,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể hủy hóa đơn. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

/**
 * Apply penalty to an overdue invoice
 *
 * @example
 * ```tsx
 * const { mutate: applyPenalty, isPending } = useApplyPenalty()
 *
 * applyPenalty({
 *   invoiceId: 123,
 *   feeId: 456,
 *   data: { penalty_amount: '500000' }
 * })
 * ```
 */
export function useApplyPenalty() {
  const queryClient = useQueryClient()

  return useMutation<
    Invoice,
    AxiosError<ApiErrorResponse>,
    { invoiceId: number; feeId: number; data: InvoicePenaltyRequest }
  >({
    mutationFn: ({ invoiceId, data }) => invoicesApi.applyPenalty(invoiceId, data),
    onSuccess: (invoice, { feeId }) => {
      toast.success("Đã áp dụng phí trễ hạn thành công")
      invalidateInvoiceQueries(queryClient, invoice.id, {
        byFee: feeId,
        feeDetail: feeId,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể áp dụng phí trễ hạn. Vui lòng thử lại."
      toast.error(message)
    },
  })
}
