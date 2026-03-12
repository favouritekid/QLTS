/**
 * Fee ViewModel Hook
 *
 * Transforms Fee API data into UI-ready display values.
 * Implements FRONTEND_ARCHITECTURE_V3 Section 2.6.6 ViewModel Pattern.
 *
 * Rules:
 * - Computes display values (labels, variants)
 * - Uses API-provided can_* permission flags (Thin Client compliance)
 * - Memoizes to prevent re-renders
 * - NO business logic - only presentation
 */

import { useMemo } from "react"
import { useFeeDetail } from "./useFees"
import {
  FEE_STATUS_LABELS,
  FEE_STATUS_VARIANTS,
  FEE_TYPE_LABELS,
} from "@/types/finance.types"
import type { Fee, FeeDetail } from "@/types/finance.types"
import { formatVND, parseAmount } from "@/lib/zod/finance"

// =====================================================================
// VIEWMODEL TYPE
// =====================================================================

export interface FeeViewModel extends Omit<FeeDetail, "status" | "fee_type"> {
  // Original values
  status: FeeDetail["status"]
  fee_type: FeeDetail["fee_type"]

  // Computed display values
  status_label: string
  status_variant: "default" | "secondary" | "destructive" | "outline"
  fee_type_label: string

  // Formatted amounts
  base_amount_formatted: string
  total_discount_formatted: string
  final_amount_formatted: string
  paid_amount_formatted: string
  waived_amount_formatted: string
  remaining_amount_formatted: string

  // Progress percentage (0-100)
  payment_progress: number

  // UI-ready boolean flags (from API can_* permission flags)
  show_waive_button: boolean
  show_cancel_button: boolean
  show_recalculate_button: boolean
  is_paid: boolean
  is_overdue: boolean
  is_terminal: boolean
  has_invoices: boolean
  has_discounts: boolean
  has_installment_plan: boolean
}

// =====================================================================
// TRANSFORM FUNCTION
// =====================================================================

/**
 * Transform FeeDetail to FeeViewModel
 * Pure function for testing and reuse
 */
export function toFeeViewModel(fee: FeeDetail): FeeViewModel {
  const finalAmount = parseAmount(fee.final_amount)
  const paidAmount = parseAmount(fee.paid_amount)
  const paymentProgress = finalAmount > 0 ? Math.min(100, Math.round((paidAmount / finalAmount) * 100)) : 0

  return {
    ...fee,
    // Computed display values
    status_label: FEE_STATUS_LABELS[fee.status] ?? fee.status,
    status_variant: FEE_STATUS_VARIANTS[fee.status] ?? "secondary",
    fee_type_label: FEE_TYPE_LABELS[fee.fee_type] ?? fee.fee_type,

    // Formatted amounts
    base_amount_formatted: formatVND(fee.base_amount),
    total_discount_formatted: formatVND(fee.total_discount),
    final_amount_formatted: formatVND(fee.final_amount),
    paid_amount_formatted: formatVND(fee.paid_amount),
    waived_amount_formatted: formatVND(fee.waived_amount),
    remaining_amount_formatted: formatVND(fee.remaining_amount),

    // Progress
    payment_progress: paymentProgress,

    // UI-ready boolean flags (from API can_* permission flags - Thin Client)
    show_waive_button: fee.can_waive,
    show_cancel_button: fee.can_cancel,
    show_recalculate_button: fee.can_recalculate,
    is_paid: fee.status === "paid",
    is_overdue: fee.status === "overdue",
    is_terminal: ["paid", "cancelled", "waived"].includes(fee.status),
    has_invoices: fee.invoices.length > 0,
    has_discounts: fee.applied_discounts.length > 0,
    has_installment_plan: fee.installment_plan !== null,
  }
}

// =====================================================================
// VIEWMODEL HOOK
// =====================================================================

/**
 * Fee ViewModel Hook
 *
 * @param feeId - The fee ID to fetch and transform
 * @param options - Query options
 *
 * @example
 * ```tsx
 * function FeeDetailClient({ feeId }: { feeId: number }) {
 *   const { data: fee, isLoading, error } = useFeeViewModel(feeId)
 *
 *   if (isLoading) return <Skeleton />
 *   if (error) return <ErrorBoundary error={error} />
 *   if (!fee) return null
 *
 *   return (
 *     <div>
 *       <Badge variant={fee.status_variant}>{fee.status_label}</Badge>
 *       <p>{fee.fee_type_label}</p>
 *       <p>Tổng cộng: {fee.final_amount_formatted}</p>
 *       <Progress value={fee.payment_progress} />
 *       {fee.show_waive_button && <Button>Miễn giảm</Button>}
 *       {fee.show_cancel_button && <Button variant="destructive">Hủy</Button>}
 *     </div>
 *   )
 * }
 * ```
 */
export function useFeeViewModel(
  feeId: number,
  options?: { enabled?: boolean }
) {
  const query = useFeeDetail(feeId, options)

  const viewModel = useMemo(() => {
    if (!query.data) return null
    return toFeeViewModel(query.data)
  }, [query.data])

  return {
    ...query,
    data: viewModel,
  }
}

// =====================================================================
// LIST VIEWMODEL HOOK
// =====================================================================

/**
 * Transform Fee list items for table/card display
 */
export interface FeeListItemViewModel {
  id: number
  admission_profile_id: number
  fee_type: string
  fee_type_label: string
  academic_year: string
  status: string
  status_label: string
  status_variant: "default" | "secondary" | "destructive" | "outline"
  final_amount_formatted: string
  paid_amount_formatted: string
  remaining_amount_formatted: string
  payment_progress: number
  is_overdue: boolean
  due_date: string | null
  due_date_formatted: string | null
  // Permission flags from API
  can_waive: boolean
  can_cancel: boolean
  can_recalculate: boolean
}

/**
 * Transform a list of fees for table display
 */
export function toFeeListViewModel(fees: Fee[]): FeeListItemViewModel[] {
  return fees.map((fee) => {
    const finalAmount = parseAmount(fee.final_amount)
    const paidAmount = parseAmount(fee.paid_amount)
    const paymentProgress = finalAmount > 0 ? Math.min(100, Math.round((paidAmount / finalAmount) * 100)) : 0

    // Format due date
    let dueDateFormatted: string | null = null
    if (fee.due_date) {
      try {
        dueDateFormatted = new Intl.DateTimeFormat("vi-VN", {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
        }).format(new Date(fee.due_date))
      } catch {
        dueDateFormatted = fee.due_date
      }
    }

    return {
      id: fee.id,
      admission_profile_id: fee.admission_profile_id,
      fee_type: fee.fee_type,
      fee_type_label: FEE_TYPE_LABELS[fee.fee_type] ?? fee.fee_type,
      academic_year: fee.academic_year,
      status: fee.status,
      status_label: FEE_STATUS_LABELS[fee.status] ?? fee.status,
      status_variant: FEE_STATUS_VARIANTS[fee.status] ?? "secondary",
      final_amount_formatted: formatVND(fee.final_amount),
      paid_amount_formatted: formatVND(fee.paid_amount),
      remaining_amount_formatted: formatVND(fee.remaining_amount),
      payment_progress: paymentProgress,
      is_overdue: fee.status === "overdue",
      due_date: fee.due_date,
      due_date_formatted: dueDateFormatted,
      // Permission flags from API
      can_waive: fee.can_waive,
      can_cancel: fee.can_cancel,
      can_recalculate: fee.can_recalculate,
    }
  })
}
