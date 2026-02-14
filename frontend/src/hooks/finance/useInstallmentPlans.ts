/**
 * React Query Hooks for Installment Plans
 *
 * @see lib/api/payments.ts
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import { paymentsApi } from "@/lib/api/payments"
import type { ApiErrorResponse } from "@/types/api.types"
import type {
  InstallmentPlan,
  InstallmentPlanCreateRequest,
  InstallmentPlanUpdateRequest,
} from "@/types/finance.types"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const installmentPlansKeys = {
  all: ["installmentPlans"] as const,
  list: () => [...installmentPlansKeys.all, "list"] as const,
  adminList: () => [...installmentPlansKeys.all, "adminList"] as const,
  detail: (id: number) => [...installmentPlansKeys.all, "detail", id] as const,
}

// =====================================================================
// QUERIES
// =====================================================================

/**
 * Get list of active installment plans (public endpoint)
 */
export function useInstallmentPlans(options?: { enabled?: boolean }) {
  return useQuery<InstallmentPlan[], AxiosError<ApiErrorResponse>>({
    queryKey: installmentPlansKeys.list(),
    queryFn: () => paymentsApi.getInstallmentPlans(),
    staleTime: 1000 * 60 * 30, // 30 minutes - rarely changes
    gcTime: 1000 * 60 * 60, // 1 hour
    enabled: options?.enabled ?? true,
  })
}

/**
 * Get all installment plans (admin endpoint - includes inactive)
 */
export function useAdminInstallmentPlans(options?: { enabled?: boolean }) {
  return useQuery<InstallmentPlan[], AxiosError<ApiErrorResponse>>({
    queryKey: installmentPlansKeys.adminList(),
    queryFn: () => paymentsApi.getAdminInstallmentPlans(),
    staleTime: 1000 * 60 * 5, // 5 minutes for admin
    enabled: options?.enabled ?? true,
  })
}

/**
 * Get single installment plan by ID
 */
export function useInstallmentPlan(id: number, options?: { enabled?: boolean }) {
  return useQuery<InstallmentPlan, AxiosError<ApiErrorResponse>>({
    queryKey: installmentPlansKeys.detail(id),
    queryFn: () => paymentsApi.getInstallmentPlan(id),
    enabled: (options?.enabled ?? true) && !!id,
    staleTime: 1000 * 60 * 30,
  })
}

/**
 * Get installment plan by code
 */
export function useInstallmentPlanByCode(
  code: string | null,
  options?: { enabled?: boolean }
) {
  const query = useInstallmentPlans({
    enabled: (options?.enabled ?? true) && code !== null,
  })

  return {
    ...query,
    data: query.data?.find((p) => p.code === code) ?? null,
  }
}

// =====================================================================
// MUTATIONS (Admin CRUD)
// =====================================================================

/**
 * Create a new installment plan
 */
export function useCreateInstallmentPlan() {
  const queryClient = useQueryClient()

  return useMutation<InstallmentPlan, AxiosError<ApiErrorResponse>, InstallmentPlanCreateRequest>({
    mutationFn: (data) => paymentsApi.createInstallmentPlan(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: installmentPlansKeys.all })
      toast.success("Tạo phương án trả góp thành công")
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể tạo phương án trả góp"
      toast.error(typeof message === "string" ? message : "Không thể tạo phương án trả góp")
    },
  })
}

/**
 * Update an installment plan
 */
export function useUpdateInstallmentPlan() {
  const queryClient = useQueryClient()

  return useMutation<
    InstallmentPlan,
    AxiosError<ApiErrorResponse>,
    { id: number; data: InstallmentPlanUpdateRequest }
  >({
    mutationFn: ({ id, data }) => paymentsApi.updateInstallmentPlan(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: installmentPlansKeys.all })
      toast.success("Cập nhật phương án trả góp thành công")
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể cập nhật phương án trả góp"
      toast.error(typeof message === "string" ? message : "Không thể cập nhật phương án trả góp")
    },
  })
}

/**
 * Delete an installment plan
 */
export function useDeleteInstallmentPlan() {
  const queryClient = useQueryClient()

  return useMutation<void, AxiosError<ApiErrorResponse>, { id: number; hardDelete?: boolean }>({
    mutationFn: ({ id, hardDelete }) => paymentsApi.deleteInstallmentPlan(id, hardDelete),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: installmentPlansKeys.all })
      toast.success("Xóa phương án trả góp thành công")
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể xóa phương án trả góp"
      toast.error(typeof message === "string" ? message : "Không thể xóa phương án trả góp")
    },
  })
}

// =====================================================================
// SELECT OPTIONS
// =====================================================================

export interface InstallmentPlanOption {
  value: string // code
  label: string
  description: string | null
  installment_count: number
  has_penalty: boolean
  disabled: boolean
}

/**
 * Transform installment plans to select options
 */
export function toInstallmentPlanOptions(
  plans: InstallmentPlan[] | undefined
): InstallmentPlanOption[] {
  if (!plans) return []

  return plans
    .filter((p) => p.is_active)
    .sort((a, b) => a.installment_count - b.installment_count)
    .map((p) => ({
      value: p.code,
      label: `${p.name} (${p.installment_count} đợt)`,
      description: p.description,
      installment_count: p.installment_count,
      has_penalty: parseFloat(p.penalty_rate) > 0,
      disabled: !p.is_active,
    }))
}

/**
 * Hook that returns installment plan select options
 */
export function useInstallmentPlanOptions(options?: { enabled?: boolean }) {
  const query = useInstallmentPlans(options)

  return {
    ...query,
    options: toInstallmentPlanOptions(query.data),
  }
}

// =====================================================================
// SCHEDULE DISPLAY HELPERS
// =====================================================================

export interface ScheduleDisplayItem {
  installment_no: number
  percent: number
  percent_formatted: string
  due_days_offset: number
  due_description: string
}

/**
 * Transform schedule to display items
 */
export function toScheduleDisplay(
  plan: InstallmentPlan | null | undefined
): ScheduleDisplayItem[] {
  if (!plan) return []

  return plan.schedule.map((item) => ({
    installment_no: item.installment_no,
    percent: item.percent,
    percent_formatted: `${item.percent}%`,
    due_days_offset: item.due_days_offset,
    due_description:
      item.due_days_offset === 0
        ? "Khi tính phí"
        : `${item.due_days_offset} ngày sau`,
  }))
}

/**
 * Get penalty description for a plan
 */
export function getPenaltyDescription(plan: InstallmentPlan | null | undefined): string {
  if (!plan) return ""

  const rate = parseFloat(plan.penalty_rate)
  if (rate <= 0) return "Không áp dụng phí trễ hạn"

  const rateFormatted = plan.penalty_type === "fixed"
    ? new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND", maximumFractionDigits: 0 }).format(rate)
    : `${rate}%`

  const graceInfo = plan.grace_period_days > 0
    ? ` (sau ${plan.grace_period_days} ngày ân hạn)`
    : ""

  return `Phí trễ hạn: ${rateFormatted}${graceInfo}`
}
