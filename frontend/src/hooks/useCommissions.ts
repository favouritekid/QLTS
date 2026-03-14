import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import * as commissionsApi from "@/lib/api/commissions"
import type {
  CommissionPoliciesPage,
  CommissionPolicy,
  CommissionPolicyCreate,
  CommissionPolicyUpdate,
  CommissionRecord,
  CommissionRecordsPage,
  CommissionReject,
  CommissionPay,
  CommissionStats,
} from "@/types/commission.types"

// ============================================================================
// QUERY KEYS
// ============================================================================

export const commissionPolicyKeys = {
  all: ["commission-policies"] as const,
  lists: () => [...commissionPolicyKeys.all, "list"] as const,
  list: (params?: Record<string, unknown>) => [...commissionPolicyKeys.lists(), params] as const,
  details: () => [...commissionPolicyKeys.all, "detail"] as const,
  detail: (id: number) => [...commissionPolicyKeys.details(), id] as const,
}

export const commissionRecordKeys = {
  all: ["commissions"] as const,
  lists: () => [...commissionRecordKeys.all, "list"] as const,
  list: (params?: Record<string, unknown>) => [...commissionRecordKeys.lists(), params] as const,
  details: () => [...commissionRecordKeys.all, "detail"] as const,
  detail: (id: number) => [...commissionRecordKeys.details(), id] as const,
}

export const ctvCommissionKeys = {
  list: (params?: Record<string, unknown>) => ["ctv", "commissions", params] as const,
  stats: ["ctv", "commission-stats"] as const,
}

// ============================================================================
// ADMIN: POLICY QUERIES
// ============================================================================

export function useCommissionPolicies(params?: { skip?: number; limit?: number; is_active?: boolean; trigger_status_id?: string }) {
  return useQuery<CommissionPoliciesPage>({
    queryKey: commissionPolicyKeys.list(params),
    queryFn: () => commissionsApi.getCommissionPolicies(params),
    staleTime: 1000 * 10,
  })
}

export function useCommissionPolicy(id: number) {
  return useQuery<CommissionPolicy>({
    queryKey: commissionPolicyKeys.detail(id),
    queryFn: () => commissionsApi.getCommissionPolicy(id),
    enabled: !!id,
  })
}

// ============================================================================
// ADMIN: POLICY MUTATIONS
// ============================================================================

export function useCreateCommissionPolicy() {
  const queryClient = useQueryClient()
  return useMutation<CommissionPolicy, AxiosError<{ detail: string }>, CommissionPolicyCreate>({
    mutationFn: commissionsApi.createCommissionPolicy,
    onSuccess: () => {
      toast.success("Tạo chính sách hoa hồng thành công")
      queryClient.invalidateQueries({ queryKey: commissionPolicyKeys.lists() })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi tạo chính sách")
    },
  })
}

export function useUpdateCommissionPolicy() {
  const queryClient = useQueryClient()
  return useMutation<CommissionPolicy, AxiosError<{ detail: string }>, { id: number; data: CommissionPolicyUpdate }>({
    mutationFn: ({ id, data }) => commissionsApi.updateCommissionPolicy(id, data),
    onSuccess: (_, { id }) => {
      toast.success("Cập nhật chính sách thành công")
      queryClient.invalidateQueries({ queryKey: commissionPolicyKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: commissionPolicyKeys.lists() })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi cập nhật chính sách")
    },
  })
}

// ============================================================================
// ADMIN: RECORD QUERIES
// ============================================================================

export function useCommissionRecords(params?: { skip?: number; limit?: number; collaborator_id?: number; status?: string }) {
  return useQuery<CommissionRecordsPage>({
    queryKey: commissionRecordKeys.list(params),
    queryFn: () => commissionsApi.getCommissionRecords(params),
    staleTime: 1000 * 5,
  })
}

export function useCommissionRecord(id: number) {
  return useQuery<CommissionRecord>({
    queryKey: commissionRecordKeys.detail(id),
    queryFn: () => commissionsApi.getCommissionRecord(id),
    enabled: !!id,
  })
}

// ============================================================================
// ADMIN: RECORD MUTATIONS
// ============================================================================

export function useApproveCommission() {
  const queryClient = useQueryClient()
  return useMutation<CommissionRecord, AxiosError<{ detail: string }>, number>({
    mutationFn: commissionsApi.approveCommission,
    onSuccess: () => {
      toast.success("Đã duyệt hoa hồng")
      queryClient.invalidateQueries({ queryKey: commissionRecordKeys.lists() })
      queryClient.invalidateQueries({ queryKey: ctvCommissionKeys.list() })
      queryClient.invalidateQueries({ queryKey: ctvCommissionKeys.stats })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi duyệt hoa hồng")
    },
  })
}

export function useRejectCommission() {
  const queryClient = useQueryClient()
  return useMutation<CommissionRecord, AxiosError<{ detail: string }>, { id: number; data: CommissionReject }>({
    mutationFn: ({ id, data }) => commissionsApi.rejectCommission(id, data),
    onSuccess: () => {
      toast.success("Đã từ chối hoa hồng")
      queryClient.invalidateQueries({ queryKey: commissionRecordKeys.lists() })
      queryClient.invalidateQueries({ queryKey: ctvCommissionKeys.list() })
      queryClient.invalidateQueries({ queryKey: ctvCommissionKeys.stats })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi từ chối hoa hồng")
    },
  })
}

export function usePayCommission() {
  const queryClient = useQueryClient()
  return useMutation<CommissionRecord, AxiosError<{ detail: string }>, { id: number; data?: CommissionPay }>({
    mutationFn: ({ id, data }) => commissionsApi.payCommission(id, data),
    onSuccess: () => {
      toast.success("Đã thanh toán hoa hồng")
      queryClient.invalidateQueries({ queryKey: commissionRecordKeys.lists() })
      queryClient.invalidateQueries({ queryKey: ctvCommissionKeys.list() })
      queryClient.invalidateQueries({ queryKey: ctvCommissionKeys.stats })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi thanh toán")
    },
  })
}

// ============================================================================
// CTV: OWN COMMISSIONS
// ============================================================================

export function useCTVCommissions(params?: { skip?: number; limit?: number; status?: string }) {
  return useQuery<CommissionRecordsPage>({
    queryKey: ctvCommissionKeys.list(params),
    queryFn: () => commissionsApi.getMyCommissions(params),
    staleTime: 1000 * 5,
  })
}

export function useCTVCommissionStats() {
  return useQuery<CommissionStats>({
    queryKey: ctvCommissionKeys.stats,
    queryFn: commissionsApi.getMyCommissionStats,
  })
}
