import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { overpaymentsApi, type OverpaymentPaginatedResponse } from "@/lib/api/overpayments"
import type { ApiErrorResponse } from "@/types/api.types"
import type {
  OverpaymentApplyRequest,
  OverpaymentFilters,
  OverpaymentRecord,
  OverpaymentRefundRequest,
  OverpaymentWriteOffRequest,
} from "@/types/finance.types"

export const overpaymentsKeys = {
  all: ["overpayments"] as const,
  lists: () => [...overpaymentsKeys.all, "list"] as const,
  list: (filters?: OverpaymentFilters) => [...overpaymentsKeys.lists(), filters] as const,
  details: () => [...overpaymentsKeys.all, "detail"] as const,
  detail: (id: number) => [...overpaymentsKeys.details(), id] as const,
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

export function useOverpayments(filters?: OverpaymentFilters, options?: { enabled?: boolean }) {
  return useQuery<OverpaymentPaginatedResponse, AxiosError<ApiErrorResponse>>({
    queryKey: overpaymentsKeys.list(filters),
    queryFn: () => overpaymentsApi.getOverpayments(filters),
    enabled: options?.enabled ?? true,
    staleTime: 1000 * 20,
  })
}

export function useApplyOverpayment() {
  const queryClient = useQueryClient()
  return useMutation<
    OverpaymentRecord,
    AxiosError<ApiErrorResponse>,
    { id: number; data: OverpaymentApplyRequest }
  >({
    mutationFn: ({ id, data }) => overpaymentsApi.applyOverpayment(id, data),
    onSuccess: (overpayment) => {
      toast.success("Đã áp dụng tiền nộp thừa")
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.detail(overpayment.id) })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Không thể áp dụng tiền nộp thừa"))
    },
  })
}

export function useRefundOverpayment() {
  const queryClient = useQueryClient()
  return useMutation<
    OverpaymentRecord,
    AxiosError<ApiErrorResponse>,
    { id: number; data: OverpaymentRefundRequest }
  >({
    mutationFn: ({ id, data }) => overpaymentsApi.refundOverpayment(id, data),
    onSuccess: (overpayment) => {
      toast.success("Đã tạo yêu cầu hoàn tiền nộp thừa")
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.detail(overpayment.id) })
      queryClient.invalidateQueries({ queryKey: ["refunds"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Không thể tạo yêu cầu hoàn tiền nộp thừa"))
    },
  })
}

export function useWriteOffOverpayment() {
  const queryClient = useQueryClient()
  return useMutation<
    OverpaymentRecord,
    AxiosError<ApiErrorResponse>,
    { id: number; data: OverpaymentWriteOffRequest }
  >({
    mutationFn: ({ id, data }) => overpaymentsApi.writeOffOverpayment(id, data),
    onSuccess: (overpayment) => {
      toast.success("Đã xóa sổ tiền nộp thừa")
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.detail(overpayment.id) })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Không thể xóa sổ tiền nộp thừa"))
    },
  })
}
