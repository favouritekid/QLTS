import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { refundsApi, type RefundPaginatedResponse, type RefundRejectRequest } from "@/lib/api/refunds"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import { feesKeys } from "@/hooks/finance/useFees"
import { invoicesKeys } from "@/hooks/finance/useInvoices"
import { leadsKeys } from "@/hooks/useLeads"
import { pipelineKeys } from "@/hooks/usePipeline"
import type { ApiErrorResponse } from "@/types/api.types"
import type {
  RefundCreateRequest,
  RefundFilters,
  RefundProcessRequest,
  RefundRequest,
} from "@/types/finance.types"

export const refundsKeys = {
  all: ["refunds"] as const,
  lists: () => [...refundsKeys.all, "list"] as const,
  list: (filters?: RefundFilters) => [...refundsKeys.lists(), filters] as const,
  details: () => [...refundsKeys.all, "detail"] as const,
  detail: (id: number) => [...refundsKeys.details(), id] as const,
}

function getErrorMessage(error: AxiosError<ApiErrorResponse>, fallback: string) {
  const detail = error.response?.data?.detail
  if (typeof detail === "string") return detail
  // FastAPI 422 returns detail as an array of {msg, loc, ...}; surface the first.
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown }
    if (first && typeof first.msg === "string") return first.msg
  }
  return fallback
}

export function useRefunds(filters?: RefundFilters, options?: { enabled?: boolean }) {
  return useQuery<RefundPaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: refundsKeys.list(filters),
    queryFn: () => refundsApi.getRefunds(filters),
    enabled: options?.enabled ?? true,
    staleTime: 1000 * 20,
  })
}

export function useRefundDetail(id: number, options?: { enabled?: boolean }) {
  return useQuery<RefundRequest, AxiosError<ApiErrorResponse>>({
    queryKey: refundsKeys.detail(id),
    queryFn: () => refundsApi.getRefund(id),
    enabled: (options?.enabled ?? true) && !!id,
  })
}

export function useCreateRefund() {
  const queryClient = useQueryClient()
  return useMutation<RefundRequest, AxiosError<ApiErrorResponse>, RefundCreateRequest>({
    mutationFn: refundsApi.createRefund,
    onSuccess: () => {
      toast.success("Đã tạo yêu cầu hoàn phí")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Không thể tạo yêu cầu hoàn phí"))
    },
  })
}

export function useApproveRefund() {
  const queryClient = useQueryClient()
  return useMutation<RefundRequest, AxiosError<ApiErrorResponse>, number>({
    mutationFn: refundsApi.approveRefund,
    onSuccess: (refund) => {
      toast.success("Đã phê duyệt hoàn phí")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: refundsKeys.detail(refund.id) })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Không thể phê duyệt hoàn phí"))
    },
  })
}

export function useRejectRefund() {
  const queryClient = useQueryClient()
  return useMutation<
    RefundRequest,
    AxiosError<ApiErrorResponse>,
    { id: number; data: RefundRejectRequest }
  >({
    mutationFn: ({ id, data }) => refundsApi.rejectRefund(id, data),
    onSuccess: (refund) => {
      toast.success("Đã từ chối hoàn phí")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: refundsKeys.detail(refund.id) })
      // Rejecting a pending refund drops it from the "chờ hoàn" totals, so the
      // dashboard stat must refresh too (parity with useCreateRefund, which
      // increments the same counter on the way in).
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Không thể từ chối hoàn phí"))
    },
  })
}

export function useProcessRefund() {
  const queryClient = useQueryClient()
  return useMutation<
    RefundRequest,
    AxiosError<ApiErrorResponse>,
    { id: number; data: RefundProcessRequest }
  >({
    mutationFn: ({ id, data }) => refundsApi.processRefund(id, data),
    onSuccess: (refund) => {
      toast.success("Đã xử lý hoàn phí")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: refundsKeys.detail(refund.id) })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
      // Processing a refund can auto-close a linked overpayment (F4), so refresh
      // the overpayments cache too.
      queryClient.invalidateQueries({ queryKey: ["overpayments"] })
      // Processing the LAST refundable payment finalizes a pending withdrawal
      // (admission_service.process_approved_refund → _finalize_withdrawn):
      // admission status withdrawal_pending → withdrawn AND the lead advances to
      // sts08. An ordinary HK1-tuition refund likewise projects the lead to
      // sts18 (sync_lead_tuition_refunded). Neither is reflected in the response
      // (a bare RefundRequest), so refresh the admission + lead + pipeline caches
      // to keep those views in sync.
      queryClient.invalidateQueries({ queryKey: admissionsKeys.all })
      queryClient.invalidateQueries({ queryKey: leadsKeys.lists() })
      // pipelineKeys.all — NOT fullPipeline(): the board mounts with concrete
      // params, so fullPipeline()'s trailing `undefined` fails React Query's
      // partial match and the invalidation would be a silent no-op.
      queryClient.invalidateQueries({ queryKey: pipelineKeys.all })
      // Processing a refund reverses fee.paid_amount (reverse_payment_balances)
      // and, on the withdrawal-finalize path, cancels the reopened fees/invoices.
      // The RefundRequest response carries only payment_id (no profile/fee id),
      // so invalidate the fee + invoice roots — the admission Tuition tab /
      // "Còn nợ" badge (feesKeys.profileSummary) and /finance/invoices otherwise
      // keep showing the money as still collected / the invoice as payable.
      queryClient.invalidateQueries({ queryKey: feesKeys.all })
      queryClient.invalidateQueries({ queryKey: invoicesKeys.all })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Không thể xử lý hoàn phí"))
    },
  })
}
