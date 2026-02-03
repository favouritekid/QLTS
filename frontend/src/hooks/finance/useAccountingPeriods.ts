/**
 * React Query Hooks for Accounting Period Management
 *
 * @see lib/api/accounting.ts
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import {
  accountingApi,
  type AccountingPeriodFilters,
  type AccountingPeriodCreateRequest,
  type AccountingPeriodSummary,
} from "@/lib/api/accounting"
import type { ApiErrorResponse } from "@/types/api.types"
import type { AccountingPeriod } from "@/types/finance.types"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const accountingKeys = {
  all: ["accounting"] as const,
  lists: () => [...accountingKeys.all, "list"] as const,
  list: (filters?: AccountingPeriodFilters) => [...accountingKeys.lists(), filters] as const,
  details: () => [...accountingKeys.all, "detail"] as const,
  detail: (id: number) => [...accountingKeys.details(), id] as const,
  summary: (id: number) => [...accountingKeys.all, "summary", id] as const,
  current: () => [...accountingKeys.all, "current"] as const,
}

// =====================================================================
// QUERIES (READ)
// =====================================================================

/**
 * Get list of accounting periods
 *
 * @param filters - Optional year and is_closed filters
 * @returns Query result with accounting periods
 *
 * @example
 * ```tsx
 * const { data: periods, isLoading } = useAccountingPeriods({ year: 2026 })
 * ```
 */
export function useAccountingPeriods(filters?: AccountingPeriodFilters) {
  return useQuery<AccountingPeriod[], AxiosError<ApiErrorResponse>>({
    queryKey: accountingKeys.list(filters),
    queryFn: () => accountingApi.getPeriods(filters),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

/**
 * Get current open accounting period
 *
 * @returns Query result with current period or null
 *
 * @example
 * ```tsx
 * const { data: currentPeriod } = useCurrentPeriod()
 * if (currentPeriod) {
 *   console.log(`Current period: ${currentPeriod.year}-${currentPeriod.month}`)
 * }
 * ```
 */
export function useCurrentPeriod() {
  return useQuery<AccountingPeriod | null, AxiosError<ApiErrorResponse>>({
    queryKey: accountingKeys.current(),
    queryFn: () => accountingApi.getCurrentPeriod(),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

/**
 * Get accounting period detail by ID
 *
 * @param periodId - The period ID
 * @returns Query result with period details
 */
export function useAccountingPeriod(periodId: number) {
  return useQuery<AccountingPeriod, AxiosError<ApiErrorResponse>>({
    queryKey: accountingKeys.detail(periodId),
    queryFn: () => accountingApi.getPeriod(periodId),
    staleTime: 5 * 60 * 1000,
    enabled: periodId > 0,
  })
}

/**
 * Get accounting period summary report
 *
 * @param periodId - The period ID
 * @returns Query result with period summary
 */
export function useAccountingPeriodSummary(periodId: number) {
  return useQuery<AccountingPeriodSummary, AxiosError<ApiErrorResponse>>({
    queryKey: accountingKeys.summary(periodId),
    queryFn: () => accountingApi.getPeriodSummary(periodId),
    staleTime: 2 * 60 * 1000, // 2 minutes
    enabled: periodId > 0,
  })
}

// =====================================================================
// MUTATIONS (WRITE)
// =====================================================================

/**
 * Create a new accounting period
 *
 * @returns Mutation for creating period
 *
 * @example
 * ```tsx
 * const createMutation = useCreatePeriod()
 *
 * const handleCreate = () => {
 *   createMutation.mutate({ month: 2, year: 2026 })
 * }
 * ```
 */
export function useCreatePeriod() {
  const queryClient = useQueryClient()

  return useMutation<AccountingPeriod, AxiosError<ApiErrorResponse>, AccountingPeriodCreateRequest>({
    mutationFn: (data) => accountingApi.createPeriod(data),
    onSuccess: () => {
      // Invalidate lists and current period
      queryClient.invalidateQueries({ queryKey: accountingKeys.lists() })
      queryClient.invalidateQueries({ queryKey: accountingKeys.current() })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message = typeof detail === "string" ? detail : "Không thể tạo kỳ kế toán"
      toast.error(message)
    },
  })
}

/**
 * Close an accounting period
 *
 * @returns Mutation for closing period
 *
 * @example
 * ```tsx
 * const closeMutation = useClosePeriod()
 *
 * const handleClose = (periodId: number) => {
 *   closeMutation.mutate({ periodId, notes: "Closed for month-end" })
 * }
 * ```
 */
export function useClosePeriod() {
  const queryClient = useQueryClient()

  return useMutation<
    AccountingPeriod,
    AxiosError<ApiErrorResponse>,
    { periodId: number; notes?: string }
  >({
    mutationFn: ({ periodId, notes }) => accountingApi.closePeriod(periodId, notes),
    onSuccess: (_, variables) => {
      // Invalidate all related queries
      queryClient.invalidateQueries({ queryKey: accountingKeys.lists() })
      queryClient.invalidateQueries({ queryKey: accountingKeys.current() })
      queryClient.invalidateQueries({ queryKey: accountingKeys.detail(variables.periodId) })
      queryClient.invalidateQueries({ queryKey: accountingKeys.summary(variables.periodId) })
    },
    onError: (error) => {
      const detail = error.response?.data?.detail
      const message = typeof detail === "string" ? detail : "Không thể đóng kỳ kế toán"
      toast.error(message)
    },
  })
}
