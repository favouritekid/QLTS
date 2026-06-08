import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { refundsApi, type RefundPaginatedResponse, type RefundRejectRequest } from "@/lib/api/refunds"
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
      toast.success("Da tao yeu cau hoan phi")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Khong the tao yeu cau hoan phi"))
    },
  })
}

export function useApproveRefund() {
  const queryClient = useQueryClient()
  return useMutation<RefundRequest, AxiosError<ApiErrorResponse>, number>({
    mutationFn: refundsApi.approveRefund,
    onSuccess: (refund) => {
      toast.success("Da phe duyet hoan phi")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: refundsKeys.detail(refund.id) })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Khong the phe duyet hoan phi"))
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
      toast.success("Da tu choi hoan phi")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: refundsKeys.detail(refund.id) })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Khong the tu choi hoan phi"))
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
      toast.success("Da xu ly hoan phi")
      queryClient.invalidateQueries({ queryKey: refundsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: refundsKeys.detail(refund.id) })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
      // Processing a refund can auto-close a linked overpayment (F4), so refresh
      // the overpayments cache too.
      queryClient.invalidateQueries({ queryKey: ["overpayments"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Khong the xu ly hoan phi"))
    },
  })
}
