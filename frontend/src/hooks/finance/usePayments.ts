/**
 * React Query Hooks for Payment Management
 *
 * Implements Maker-Checker workflow:
 * - Maker (Accountant): Records payment → status = "pending"
 * - Checker (Manager/Admin): Verifies/Rejects → status = "verified" or "rejected"
 *
 * @see lib/api/payments.ts
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { paymentsApi, type PaymentPaginatedResponse } from "@/lib/api/payments"
import type { ApiErrorResponse } from "@/types/api.types"
import type {
  Payment,
  PaymentIntent,
  PaymentFilters,
  PaymentCreateRequest,
  PaymentIntentCreateRequest,
  PaymentRejectRequest,
} from "@/types/finance.types"
import { invoicesKeys } from "./useInvoices"
import { feesKeys } from "./useFees"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const paymentsKeys = {
  all: ["payments"] as const,
  lists: () => [...paymentsKeys.all, "list"] as const,
  list: (filters?: PaymentFilters) => [...paymentsKeys.lists(), filters] as const,
  details: () => [...paymentsKeys.all, "detail"] as const,
  detail: (id: number) => [...paymentsKeys.details(), id] as const,
  byInvoice: (invoiceId: number) => [...paymentsKeys.all, "by-invoice", invoiceId] as const,
  intents: () => [...paymentsKeys.all, "intents"] as const,
  intent: (id: number) => [...paymentsKeys.intents(), id] as const,
}

// =====================================================================
// QUERY INVALIDATION HELPERS
// =====================================================================

type PaymentInvalidationOptions = {
  detail?: boolean
  lists?: boolean
  byInvoice?: number
  invoiceDetail?: number
  feeDetail?: number
  dashboard?: boolean
}

const invalidatePaymentQueries = async (
  queryClient: ReturnType<typeof useQueryClient>,
  paymentId: number,
  options: PaymentInvalidationOptions = {}
) => {
  const {
    detail = true,
    lists = true,
    byInvoice,
    invoiceDetail,
    feeDetail,
    dashboard = true,
  } = options

  const invalidations: Promise<void>[] = []

  if (detail) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: paymentsKeys.detail(paymentId) })
    )
  }
  if (lists) {
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: paymentsKeys.lists(),
        refetchType: "active",
      })
    )
  }
  if (byInvoice) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: paymentsKeys.byInvoice(byInvoice) })
    )
  }
  if (invoiceDetail) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: invoicesKeys.detail(invoiceDetail) })
    )
    // A verified/rejected payment changes the invoice's status + remaining → the
    // collection workspace list rows + tab counts must refresh too, not just the
    // invoice detail.
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: invoicesKeys.lists(),
        refetchType: "active",
      })
    )
    invalidations.push(
      queryClient.invalidateQueries({
        queryKey: [...invoicesKeys.all, "status-counts"],
        refetchType: "active",
      })
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

  return Promise.all(invalidations)
}

// =====================================================================
// QUERIES (READ)
// =====================================================================

/**
 * Get paginated payments list with optional filters
 *
 * @param filters - Filter parameters
 * @param options - Query options
 *
 * @example
 * ```tsx
 * // Get pending payments for verification queue
 * const { data, isLoading } = usePayments({ status: 'pending' })
 * ```
 */
export function usePayments(
  filters?: PaymentFilters,
  options?: { initialData?: PaymentPaginatedResponse; enabled?: boolean }
) {
  return useQuery<PaymentPaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: paymentsKeys.list(filters),
    queryFn: () => paymentsApi.getPayments(filters),
    staleTime: 1000 * 15, // 15 seconds - shorter for verification queue
    gcTime: 1000 * 60 * 5,
    initialData: options?.initialData,
    enabled: options?.enabled ?? true,
  })
}

/**
 * Get a single payment by ID
 *
 * @param id - Payment ID
 * @param options - Query options
 *
 * @example
 * ```tsx
 * const { data: payment, isLoading } = usePaymentDetail(123)
 * ```
 */
export function usePaymentDetail(
  id: number,
  options?: { enabled?: boolean; initialData?: Payment }
) {
  return useQuery<Payment, AxiosError<ApiErrorResponse>>({
    queryKey: paymentsKeys.detail(id),
    queryFn: () => paymentsApi.getPayment(id),
    enabled: (options?.enabled ?? true) && !!id,
    initialData: options?.initialData,
    staleTime: 1000 * 30,
  })
}

/**
 * Get payments by invoice ID
 *
 * @param invoiceId - Invoice ID
 *
 * @example
 * ```tsx
 * const { data: payments } = usePaymentsByInvoice(456)
 * ```
 */
export function usePaymentsByInvoice(invoiceId: number, options?: { enabled?: boolean }) {
  return useQuery<Payment[], AxiosError<ApiErrorResponse>>({
    queryKey: paymentsKeys.byInvoice(invoiceId),
    queryFn: () => paymentsApi.getPaymentsByInvoice(invoiceId),
    enabled: (options?.enabled ?? true) && !!invoiceId,
    staleTime: 1000 * 30,
  })
}

/**
 * Get payment intent by ID
 *
 * @param intentId - Payment intent ID
 *
 * @example
 * ```tsx
 * const { data: intent } = usePaymentIntent(789)
 * ```
 */
export function usePaymentIntent(intentId: number, options?: { enabled?: boolean }) {
  return useQuery<PaymentIntent, AxiosError<ApiErrorResponse>>({
    queryKey: paymentsKeys.intent(intentId),
    queryFn: () => paymentsApi.getPaymentIntent(intentId),
    enabled: (options?.enabled ?? true) && !!intentId,
    staleTime: 1000 * 5, // 5 seconds - poll for status updates
    refetchInterval: (query) => {
      // Poll every 5 seconds while pending
      const data = query.state.data
      if (data && ["created", "pending"].includes(data.status)) {
        return 5000
      }
      return false
    },
  })
}

// =====================================================================
// MUTATIONS (WRITE) - MAKER-CHECKER WORKFLOW
// =====================================================================

/**
 * Record a manual payment (Maker action)
 * Creates payment with status "pending" for verification
 *
 * @example
 * ```tsx
 * const { mutate: createPayment, isPending } = useCreatePayment()
 *
 * createPayment({
 *   data: {
 *     invoice_id: 123,
 *     method_id: 1,
 *     amount: '5000000',
 *     reference_code: 'BANK-12345'
 *   },
 *   invoiceId: 123,
 *   feeId: 456
 * })
 * ```
 */
export function useCreatePayment() {
  const queryClient = useQueryClient()

  return useMutation<
    Payment,
    AxiosError<ApiErrorResponse>,
    { data: PaymentCreateRequest; invoiceId: number; feeId?: number }
  >({
    mutationFn: ({ data }) => paymentsApi.createPayment(data),
    onSuccess: (payment, { invoiceId, feeId }) => {
      toast.success("Đã ghi nhận thanh toán. Chờ xác minh.")
      invalidatePaymentQueries(queryClient, payment.id, {
        byInvoice: invoiceId,
        invoiceDetail: invoiceId,
        feeDetail: feeId,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể ghi nhận thanh toán. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

/**
 * Verify a payment (Checker action)
 *
 * @example
 * ```tsx
 * const { mutate: verifyPayment, isPending } = useVerifyPayment()
 *
 * verifyPayment({ paymentId: 123, invoiceId: 456, feeId: 789 })
 * ```
 */
export function useVerifyPayment() {
  const queryClient = useQueryClient()

  return useMutation<
    Payment,
    AxiosError<ApiErrorResponse>,
    { paymentId: number; invoiceId: number; feeId?: number }
  >({
    mutationFn: ({ paymentId }) => paymentsApi.verifyPayment(paymentId),
    onSuccess: (payment, { invoiceId, feeId }) => {
      toast.success("Đã xác minh thanh toán thành công")
      invalidatePaymentQueries(queryClient, payment.id, {
        byInvoice: invoiceId,
        invoiceDetail: invoiceId,
        feeDetail: feeId,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể xác minh thanh toán. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

/**
 * Reject a payment (Checker action)
 *
 * @example
 * ```tsx
 * const { mutate: rejectPayment, isPending } = useRejectPayment()
 *
 * rejectPayment({
 *   paymentId: 123,
 *   invoiceId: 456,
 *   data: { rejection_reason: 'Không khớp số tiền' }
 * })
 * ```
 */
export function useRejectPayment() {
  const queryClient = useQueryClient()

  return useMutation<
    Payment,
    AxiosError<ApiErrorResponse>,
    { paymentId: number; invoiceId: number; feeId?: number; data: PaymentRejectRequest }
  >({
    mutationFn: ({ paymentId, data }) => paymentsApi.rejectPayment(paymentId, data),
    onSuccess: (payment, { invoiceId, feeId }) => {
      toast.success("Đã từ chối thanh toán")
      invalidatePaymentQueries(queryClient, payment.id, {
        byInvoice: invoiceId,
        invoiceDetail: invoiceId,
        feeDetail: feeId,
      })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể từ chối thanh toán. Vui lòng thử lại."
      toast.error(message)
    },
  })
}

// =====================================================================
// MUTATIONS (WRITE) - ONLINE PAYMENT
// =====================================================================

/**
 * Create payment intent for online payment
 *
 * @example
 * ```tsx
 * const { mutate: createIntent, isPending } = useCreatePaymentIntent()
 *
 * createIntent({
 *   data: {
 *     invoice_id: 123,
 *     method_id: 2, // VNPay
 *     amount: '5000000',
 *     idempotency_key: crypto.randomUUID(),
 *     return_url: window.location.origin + '/finance/payments/return'
 *   },
 *   onPayUrl: (url) => {
 *     window.location.href = url
 *   }
 * })
 * ```
 */
export function useCreatePaymentIntent() {
  const queryClient = useQueryClient()

  return useMutation<
    PaymentIntent,
    AxiosError<ApiErrorResponse>,
    { data: PaymentIntentCreateRequest; onPayUrl?: (url: string) => void }
  >({
    mutationFn: ({ data }) => paymentsApi.createPaymentIntent(data),
    onSuccess: (intent, { onPayUrl }) => {
      // Invalidate queries
      queryClient.invalidateQueries({ queryKey: paymentsKeys.intents() })

      // Redirect to payment gateway if pay_url is available
      if (intent.pay_url && onPayUrl) {
        onPayUrl(intent.pay_url)
      } else if (intent.pay_url) {
        window.location.href = intent.pay_url
      }
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message =
        typeof detail === "string" ? detail : "Không thể tạo thanh toán online. Vui lòng thử lại."
      toast.error(message)
    },
  })
}
