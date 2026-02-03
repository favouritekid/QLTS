/**
 * React Query Hooks for Installment Plans Lookup
 *
 * @see lib/api/payments.ts
 */

import { useQuery } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { paymentsApi } from "@/lib/api/payments"
import type { ApiErrorResponse } from "@/types/api.types"
import type { InstallmentPlan } from "@/types/finance.types"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const installmentPlansKeys = {
  all: ["installmentPlans"] as const,
  list: () => [...installmentPlansKeys.all, "list"] as const,
  detail: (id: number) => [...installmentPlansKeys.all, "detail", id] as const,
}

// =====================================================================
// QUERIES
// =====================================================================

/**
 * Get list of active installment plans
 *
 * @example
 * ```tsx
 * const { data: plans, isLoading } = useInstallmentPlans()
 *
 * // Display plan options
 * plans?.map(plan => (
 *   <option key={plan.code} value={plan.code}>
 *     {plan.name} ({plan.installment_count} đợt)
 *   </option>
 * ))
 * ```
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
 * Get single installment plan by ID
 *
 * @param id - Installment plan ID
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
// SELECT OPTIONS
// =====================================================================

export interface InstallmentPlanOption {
  value: string // code
  label: string
  // [TODO_BACKEND] Add description to InstallmentPlanResponse
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
 * [TODO_BACKEND] Add penalty_type, grace_period_days to InstallmentPlanResponse
 */
export function getPenaltyDescription(plan: InstallmentPlan | null | undefined): string {
  if (!plan) return ""

  const rate = parseFloat(plan.penalty_rate)
  if (rate <= 0) return "Không áp dụng phí trễ hạn"

  // [TODO_BACKEND] When penalty_type is available, format correctly
  // For now, assume percentage
  const rateFormatted = `${rate}%`

  return `Phí trễ hạn: ${rateFormatted}`
}
