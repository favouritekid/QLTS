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
  return typeof detail === "string" ? detail : fallback
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
      toast.success("Da ap dung tien thua")
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.detail(overpayment.id) })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Khong the ap dung tien thua"))
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
      toast.success("Da tao yeu cau hoan tien thua")
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.detail(overpayment.id) })
      queryClient.invalidateQueries({ queryKey: ["refunds"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Khong the tao yeu cau hoan tien thua"))
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
      toast.success("Da xoa so tien thua")
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: overpaymentsKeys.detail(overpayment.id) })
      queryClient.invalidateQueries({ queryKey: ["finance", "dashboard"] })
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "Khong the xoa so tien thua"))
    },
  })
}
