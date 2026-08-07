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
import { paymentsApi } from "@/lib/api/payments"
import type { ApiErrorResponse } from "@/types/api.types"
import type {
  Payment,
  PaymentIntent,
  PaymentFilters,
  PaymentListPaginatedResponse,
  PaymentCreateRequest,
  PaymentIntentCreateRequest,
  PaymentRejectRequest,
} from "@/types/finance.types"
import { invoicesKeys } from "./useInvoices"
import { feesKeys } from "./useFees"
import { docThanLoi409 } from "@/lib/finance/duplicate-review"

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
  // PR2: the collection drawer aggregates a profile's fees + invoices +
  // payments. Any payment mutation changes it → refresh the open drawer (the
  // prefix matches every open collection; usually just the one).
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
  options?: { initialData?: PaymentListPaginatedResponse; enabled?: boolean }
) {
  return useQuery<PaymentListPaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: paymentsKeys.list(filters),
    queryFn: () => paymentsApi.getPayments(filters),
    staleTime: 1000 * 15, // 15 seconds - shorter for verification queue
    gcTime: 1000 * 60 * 5,
    initialData: options?.initialData,
    enabled: options?.enabled ?? true,
  })
}

/**
 * Maker-checker verification queue — manual payments only (intent_id IS NULL,
 * status=pending), oldest-first. Online/auto-verified payments never appear.
 * Used by the workspace "Chờ duyệt" tab.
 */
export function usePendingPayments(
  params?: { page?: number; page_size?: number },
  options?: { enabled?: boolean }
) {
  const filters: PaymentFilters = {
    pending_manual_only: true,
    page: params?.page ?? 1,
    page_size: params?.page_size ?? 50,
  }
  return useQuery<PaymentListPaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: paymentsKeys.list(filters),
    queryFn: () => paymentsApi.getPayments(filters),
    staleTime: 1000 * 15,
    gcTime: 1000 * 60 * 5,
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
/**
 * Phiếu thu TAY ĐANG CHỜ DUYỆT của một KHOẢN PHÍ (mọi đợt, không chỉ đợt đang mở).
 *
 * Dùng cho ô "đang chờ duyệt" ở form ghi tiền. Vì sao phải theo khoản phí chứ
 * không theo hoá đơn: `fee.paid_amount` chỉ tăng khi phiếu được DUYỆT, nên sau
 * khi nhập lần đầu mà chưa ai duyệt, mọi màn hình vẫn hiện y như chưa thu —
 * kế toán tưởng lần nhập trước trượt nên nhập lại. Mà phiếu vừa nhập rất dễ
 * nằm ở đợt khác với đợt đang mở, lọc theo `invoice_id` sẽ không thấy nó.
 *
 * `pending_manual_only` chứ KHÔNG phải `status: "pending"`: bộ lọc trạng thái
 * chung còn trả về phiếu ONLINE người học tự bấm rồi bỏ dở (`intent_id` khác
 * NULL). Ô này nói về việc *kế toán đã nhập mà chưa ai duyệt*, nên đếm phiếu
 * online vào đó là dựng cảnh báo trên dữ liệu sai loại.
 *
 * `staleTime: 0` là điều kiện sống của tính năng, không phải chỉnh tinh: mục
 * đích của ô này là chống nhập trùng, mà ca trùng kinh điển là đóng rồi mở
 * lại form ngay sau khi một kế toán khác vừa tạo phiếu. Cache dù chỉ vài giây
 * cũng dựng lại đúng màn hình nói dối mà B1 sinh ra để xoá. Một request thừa
 * rẻ hơn một phiếu thu trùng.
 *
 * `page_size` 100: một khoản phí thực tế có vài phiếu; đặt trần để nếu dữ liệu
 * bất thường thì cũng không kéo về cả nghìn dòng chỉ để đếm — người gọi đọc
 * `total` để biết danh sách có bị cắt hay không.
 */
export function usePendingPaymentsByFee(
  feeId: number | undefined,
  options?: { enabled?: boolean }
) {
  const filters: PaymentFilters = {
    fee_id: feeId,
    pending_manual_only: true,
    page: 1,
    page_size: 100,
  }
  return useQuery<PaymentListPaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: paymentsKeys.list(filters),
    queryFn: () => paymentsApi.getPayments(filters),
    enabled: (options?.enabled ?? true) && !!feeId,
    staleTime: 0,
  })
}

/*
 * `useDuplicatePreview` ĐÃ XOÁ (Duplicate Review Protocol).
 *
 * Nó hỏi `GET /api/payments?duplicate_amount=&duplicate_date=` trong lúc người
 * dùng đang gõ, để cảnh báo sớm. Khi quyền xác nhận còn nằm ở giao diện, kết
 * quả ấy còn được dùng làm bằng chứng "đã soát"; nay quyền ấy nằm trọn ở phiếu
 * có chữ ký do máy chủ cấp trong thân lỗi 409, nên preview không còn quyền gì —
 * mà chi phí thì vẫn nguyên: cache, debounce, đua request, kết quả rỗng đã cũ,
 * và hai bộ ứng viên cùng xuất hiện để giao diện phải chọn.
 *
 * Nó còn tạo một cảm giác sai: "không thấy cảnh báo nghĩa là an toàn". Preview
 * chạy ngoài giao dịch ghi, nên nó không bao giờ hứa được điều đó.
 *
 * Đường cũ nay trả 410 — xem `TestXemTruocDaGoFailClosed` ở backend. Đừng dựng
 * lại nó dưới một cái tên khác.
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
      // Ca "nghi trùng" KHÔNG phải lỗi để báo đỏ: form sẽ hiện khối cảnh báo
      // kèm danh sách phiếu và một ô xác nhận. Bắn thêm toast đỏ ở đây là vừa
      // doạ người dùng vừa che mất thứ họ cần đọc.
      //
      // Nhưng chỉ im lặng khi payload ĐÚNG cấu trúc — nếu nó méo thì form
      // không có gì để hiện, và im lặng biến thành "bấm Lưu mà không có phản
      // hồi nào". Payload méo ⇒ rơi về thông báo chung, tức fail-closed.
      if (docThanLoi409(error.response?.data)) return

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
