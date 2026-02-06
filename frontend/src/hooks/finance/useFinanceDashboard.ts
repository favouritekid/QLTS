/**
 * React Query Hook for Finance Dashboard
 *
 * @see lib/api/payments.ts
 */

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { paymentsApi, type FinanceDashboardParams } from "@/lib/api/payments"
import type { ApiErrorResponse } from "@/types/api.types"
import type { FinanceDashboardStats } from "@/types/finance.types"
import { formatVND, parseAmount } from "@/lib/zod/finance"

// =====================================================================
// QUERY KEYS
// =====================================================================

export const financeDashboardKeys = {
  all: ["finance", "dashboard"] as const,
  stats: (params?: FinanceDashboardParams) => [...financeDashboardKeys.all, "stats", params ?? {}] as const,
}

// =====================================================================
// QUERIES
// =====================================================================

export interface UseFinanceDashboardOptions {
  enabled?: boolean
  startDate?: string // YYYY-MM-DD format
  endDate?: string // YYYY-MM-DD format
}

/**
 * Get finance dashboard statistics
 *
 * @example
 * ```tsx
 * // Basic usage
 * const { data: stats, isLoading } = useFinanceDashboard()
 *
 * // With date filtering
 * const { data: stats } = useFinanceDashboard({
 *   startDate: '2024-01-01',
 *   endDate: '2024-01-31'
 * })
 *
 * if (stats) {
 *   console.log(`Pending fees: ${stats.pending_fees_count}`)
 *   console.log(`Period collections: ${stats.period_collections}`)
 * }
 * ```
 */
export function useFinanceDashboard(options?: UseFinanceDashboardOptions) {
  const params: FinanceDashboardParams | undefined = options?.startDate || options?.endDate
    ? { start_date: options.startDate, end_date: options.endDate }
    : undefined

  return useQuery<FinanceDashboardStats, AxiosError<ApiErrorResponse>>({
    queryKey: financeDashboardKeys.stats(params),
    queryFn: () => paymentsApi.getFinanceDashboard(params),
    staleTime: 1000 * 60, // 1 minute
    gcTime: 1000 * 60 * 5, // 5 minutes
    enabled: options?.enabled ?? true,
    refetchInterval: 1000 * 60 * 2, // Refetch every 2 minutes
  })
}

// =====================================================================
// DASHBOARD VIEWMODEL
// =====================================================================

export interface FinanceDashboardViewModel {
  // Raw counts
  pending_fees_count: number
  pending_payments_count: number
  overdue_invoices_count: number
  pending_overpayments_count: number
  pending_refunds_count: number

  // Formatted amounts
  pending_fees_amount_formatted: string
  overdue_amount_formatted: string
  today_collections_formatted: string
  monthly_collections_formatted: string
  period_collections_formatted: string

  // Period info
  period_start: string | null
  period_end: string | null

  // Computed values
  total_pending_count: number
  has_pending_items: boolean
  has_overdue: boolean
  has_pending_payments: boolean

  // Cards data for rendering
  cards: DashboardCard[]
}

export interface DashboardCard {
  id: string
  title: string
  value: string | number
  subtitle?: string
  variant: "default" | "warning" | "destructive" | "success"
  href?: string
  icon?: string
}

/**
 * Transform dashboard stats to ViewModel
 */
function toFinanceDashboardViewModel(
  stats: FinanceDashboardStats
): FinanceDashboardViewModel {
  const totalPendingCount =
    stats.pending_fees_count +
    stats.pending_payments_count +
    stats.pending_overpayments_count +
    stats.pending_refunds_count

  return {
    // Raw counts
    pending_fees_count: stats.pending_fees_count,
    pending_payments_count: stats.pending_payments_count,
    overdue_invoices_count: stats.overdue_invoices_count,
    pending_overpayments_count: stats.pending_overpayments_count,
    pending_refunds_count: stats.pending_refunds_count,

    // Formatted amounts
    pending_fees_amount_formatted: formatVND(stats.pending_fees_amount),
    overdue_amount_formatted: formatVND(stats.overdue_amount),
    today_collections_formatted: formatVND(stats.today_collections),
    monthly_collections_formatted: formatVND(stats.monthly_collections),
    period_collections_formatted: formatVND(stats.period_collections),

    // Period info
    period_start: stats.period_start,
    period_end: stats.period_end,

    // Computed values
    total_pending_count: totalPendingCount,
    has_pending_items: totalPendingCount > 0,
    has_overdue: stats.overdue_invoices_count > 0,
    has_pending_payments: stats.pending_payments_count > 0,

    // Cards data
    cards: [
      {
        id: "pending_fees",
        title: "Phí chờ tính",
        value: stats.pending_fees_count,
        subtitle: formatVND(stats.pending_fees_amount),
        variant: stats.pending_fees_count > 0 ? "warning" : "default",
        href: "/finance/fees?status=pending",
        icon: "calculator",
      },
      {
        id: "pending_payments",
        title: "Thanh toán chờ xác minh",
        value: stats.pending_payments_count,
        variant: stats.pending_payments_count > 0 ? "warning" : "default",
        href: "/finance/payments?status=pending",
        icon: "credit-card",
      },
      {
        id: "overdue_invoices",
        title: "Hóa đơn quá hạn",
        value: stats.overdue_invoices_count,
        subtitle: formatVND(stats.overdue_amount),
        variant: stats.overdue_invoices_count > 0 ? "destructive" : "default",
        href: "/finance/invoices?overdue_only=true",
        icon: "alert-triangle",
      },
      {
        id: "today_collections",
        title: "Thu hôm nay",
        value: formatVND(stats.today_collections),
        variant: "success",
        icon: "trending-up",
      },
      {
        id: "monthly_collections",
        title: "Thu trong tháng",
        value: formatVND(stats.monthly_collections),
        variant: "default",
        icon: "calendar",
      },
    ],
  }
}

/**
 * Finance Dashboard ViewModel Hook
 *
 * @example
 * ```tsx
 * function FinanceDashboardClient() {
 *   const { data: dashboard, isLoading, error } = useFinanceDashboardViewModel()
 *
 *   if (isLoading) return <Skeleton />
 *   if (error) return <ErrorBoundary error={error} />
 *   if (!dashboard) return null
 *
 *   return (
 *     <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
 *       {dashboard.cards.map(card => (
 *         <DashboardCard key={card.id} {...card} />
 *       ))}
 *     </div>
 *   )
 * }
 * ```
 */
export function useFinanceDashboardViewModel(options?: UseFinanceDashboardOptions) {
  const query = useFinanceDashboard(options)

  const viewModel = useMemo(() => {
    if (!query.data) return null
    return toFinanceDashboardViewModel(query.data)
  }, [query.data])

  return {
    ...query,
    data: viewModel,
  }
}

// =====================================================================
// BADGE COUNTS (for navigation)
// =====================================================================

export interface FinanceBadgeCounts {
  pendingPayments: number
  overdueInvoices: number
  pendingRefunds: number
  total: number
}

/**
 * Get badge counts for navigation items
 */
export function useFinanceBadgeCounts(options?: { enabled?: boolean }) {
  const query = useFinanceDashboard(options)

  const counts = useMemo<FinanceBadgeCounts | null>(() => {
    if (!query.data) return null
    return {
      pendingPayments: query.data.pending_payments_count,
      overdueInvoices: query.data.overdue_invoices_count,
      pendingRefunds: query.data.pending_refunds_count,
      total:
        query.data.pending_payments_count +
        query.data.overdue_invoices_count +
        query.data.pending_refunds_count,
    }
  }, [query.data])

  return {
    ...query,
    data: counts,
  }
}
