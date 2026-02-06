/**
 * Payment ViewModel Hook
 *
 * Transforms Payment API data into UI-ready display values.
 * Implements FRONTEND_ARCHITECTURE_V3 Section 2.6.6 ViewModel Pattern.
 *
 * Rules:
 * - Computes display values (labels, variants)
 * - Uses API-provided can_* permission flags with Maker-Checker (Thin Client compliance)
 * - Uses denormalized user names from API (created_by_name, verified_by_name)
 * - Memoizes to prevent re-renders
 * - NO business logic - only presentation
 */

import { useMemo } from "react"
import { usePaymentDetail } from "./usePayments"
import { PAYMENT_STATUS_LABELS, PAYMENT_STATUS_VARIANTS } from "@/types/finance.types"
import type { Payment } from "@/types/finance.types"
import { formatVND } from "@/lib/zod/finance"

// =====================================================================
// VIEWMODEL TYPE
// =====================================================================

export interface PaymentViewModel extends Omit<Payment, "status"> {
  // Original values
  status: Payment["status"]

  // Computed display values
  status_label: string
  status_variant: "default" | "secondary" | "destructive" | "outline"

  // Formatted amounts
  amount_formatted: string

  // Formatted dates
  payment_date_formatted: string | null
  created_at_formatted: string
  verified_at_formatted: string | null
  rejected_at_formatted: string | null

  // UI-ready boolean flags (from API can_* permission flags with Maker-Checker)
  show_verify_button: boolean
  show_reject_button: boolean
  is_pending: boolean
  is_verified: boolean
  is_rejected: boolean
  is_refunded: boolean
  is_online: boolean
  has_reference: boolean

  // Maker-Checker info (from API denormalized names)
  created_by_display: string
  verified_by_display: string | null
  rejected_by_display: string | null
}

// =====================================================================
// HELPER FUNCTIONS
// =====================================================================

function formatDate(dateStr: string | null): string | null {
  if (!dateStr) return null
  try {
    return new Intl.DateTimeFormat("vi-VN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(dateStr))
  } catch {
    return dateStr
  }
}

function formatDateShort(dateStr: string | null): string | null {
  if (!dateStr) return null
  try {
    return new Intl.DateTimeFormat("vi-VN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(dateStr))
  } catch {
    return dateStr
  }
}

// =====================================================================
// TRANSFORM FUNCTION
// =====================================================================

/**
 * Transform Payment to PaymentViewModel
 * Pure function for testing and reuse
 */
export function toPaymentViewModel(payment: Payment): PaymentViewModel {
  return {
    ...payment,
    // Computed display values
    status_label: PAYMENT_STATUS_LABELS[payment.status] ?? payment.status,
    status_variant: PAYMENT_STATUS_VARIANTS[payment.status] ?? "secondary",

    // Formatted amounts
    amount_formatted: formatVND(payment.amount),

    // Formatted dates
    payment_date_formatted: formatDateShort(payment.payment_date),
    created_at_formatted: formatDate(payment.created_at) ?? "",
    verified_at_formatted: formatDate(payment.verified_at),
    rejected_at_formatted: formatDate(payment.rejected_at),

    // UI-ready boolean flags (from API can_* permission flags with Maker-Checker)
    show_verify_button: payment.can_verify,
    show_reject_button: payment.can_reject,
    is_pending: payment.status === "pending",
    is_verified: payment.status === "verified",
    is_rejected: payment.status === "rejected",
    is_refunded: payment.status === "refunded",
    is_online: payment.intent_id !== null,
    has_reference: !!payment.reference_code,

    // Maker-Checker info (from API denormalized names)
    created_by_display: payment.created_by_name ?? `User #${payment.created_by_id}`,
    verified_by_display: payment.verified_by_name ?? (payment.verified_by_id ? `User #${payment.verified_by_id}` : null),
    rejected_by_display: payment.rejection_reason ?? null,
  }
}

// =====================================================================
// VIEWMODEL HOOK
// =====================================================================

/**
 * Payment ViewModel Hook
 *
 * @param paymentId - The payment ID to fetch and transform
 * @param options - Query options
 *
 * @example
 * ```tsx
 * function PaymentDetailClient({ paymentId }: { paymentId: number }) {
 *   const { data: payment, isLoading, error } = usePaymentViewModel(paymentId)
 *
 *   if (isLoading) return <Skeleton />
 *   if (error) return <ErrorBoundary error={error} />
 *   if (!payment) return null
 *
 *   return (
 *     <div>
 *       <Badge variant={payment.status_variant}>{payment.status_label}</Badge>
 *       <p>Số tiền: {payment.amount_formatted}</p>
 *       <p>Người tạo: {payment.created_by_display}</p>
 *       {payment.show_verify_button && <Button>Xác minh</Button>}
 *       {payment.show_reject_button && <Button variant="destructive">Từ chối</Button>}
 *     </div>
 *   )
 * }
 * ```
 */
export function usePaymentViewModel(
  paymentId: number,
  options?: { enabled?: boolean }
) {
  const query = usePaymentDetail(paymentId, options)

  const viewModel = useMemo(() => {
    if (!query.data) return null
    return toPaymentViewModel(query.data)
  }, [query.data])

  return {
    ...query,
    data: viewModel,
  }
}

// =====================================================================
// LIST VIEWMODEL
// =====================================================================

export interface PaymentListItemViewModel {
  id: number
  invoice_id: number
  status: string
  status_label: string
  status_variant: "default" | "secondary" | "destructive" | "outline"
  amount_formatted: string
  payment_date_formatted: string | null
  reference_code: string | null
  payer_name: string | null
  // From API denormalized names
  created_by_display: string
  created_at_formatted: string
  is_pending: boolean
  is_online: boolean
  // Permission flags from API (with Maker-Checker)
  can_verify: boolean
  can_reject: boolean
}

/**
 * Transform a list of payments for table display
 */
export function toPaymentListViewModel(payments: Payment[]): PaymentListItemViewModel[] {
  return payments.map((payment) => {
    return {
      id: payment.id,
      invoice_id: payment.invoice_id,
      status: payment.status,
      status_label: PAYMENT_STATUS_LABELS[payment.status] ?? payment.status,
      status_variant: PAYMENT_STATUS_VARIANTS[payment.status] ?? "secondary",
      amount_formatted: formatVND(payment.amount),
      payment_date_formatted: formatDateShort(payment.payment_date),
      reference_code: payment.reference_code,
      payer_name: payment.payer_name,
      // From API denormalized names
      created_by_display: payment.created_by_name ?? `User #${payment.created_by_id}`,
      created_at_formatted: formatDate(payment.created_at) ?? "",
      is_pending: payment.status === "pending",
      is_online: payment.intent_id !== null,
      // Permission flags from API (with Maker-Checker)
      can_verify: payment.can_verify,
      can_reject: payment.can_reject,
    }
  })
}

// =====================================================================
// VERIFICATION QUEUE VIEWMODEL
// =====================================================================

export interface PendingPaymentViewModel extends PaymentListItemViewModel {
  // Additional fields for verification queue
  needs_attention: boolean
  age_hours: number
  age_display: string
}

/**
 * Transform pending payments for verification queue
 */
export function toPendingPaymentListViewModel(payments: Payment[]): PendingPaymentViewModel[] {
  const now = new Date()

  return payments
    .filter((p) => p.status === "pending")
    .map((payment) => {
      const createdAt = new Date(payment.created_at)
      const ageMs = now.getTime() - createdAt.getTime()
      const ageHours = Math.floor(ageMs / (1000 * 60 * 60))

      let ageDisplay: string
      if (ageHours < 1) {
        const ageMinutes = Math.floor(ageMs / (1000 * 60))
        ageDisplay = `${ageMinutes} phút trước`
      } else if (ageHours < 24) {
        ageDisplay = `${ageHours} giờ trước`
      } else {
        const ageDays = Math.floor(ageHours / 24)
        ageDisplay = `${ageDays} ngày trước`
      }

      return {
        id: payment.id,
        invoice_id: payment.invoice_id,
        status: payment.status,
        status_label: PAYMENT_STATUS_LABELS[payment.status] ?? payment.status,
        status_variant: PAYMENT_STATUS_VARIANTS[payment.status] ?? "secondary",
        amount_formatted: formatVND(payment.amount),
        payment_date_formatted: formatDateShort(payment.payment_date),
        reference_code: payment.reference_code,
        payer_name: payment.payer_name,
        // From API denormalized names
        created_by_display: payment.created_by_name ?? `User #${payment.created_by_id}`,
        created_at_formatted: formatDate(payment.created_at) ?? "",
        is_pending: true,
        is_online: payment.intent_id !== null,
        // Permission flags from API (with Maker-Checker)
        can_verify: payment.can_verify,
        can_reject: payment.can_reject,
        needs_attention: ageHours >= 24, // Older than 24 hours
        age_hours: ageHours,
        age_display: ageDisplay,
      }
    })
}
