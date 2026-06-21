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
import type { Payment, PaymentListItem } from "@/types/finance.types"
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

const RELATIVE_TIME = new Intl.RelativeTimeFormat("vi", { numeric: "auto" })

/**
 * Human "age" of a payment relative to `now`, in Vietnamese, via
 * Intl.RelativeTimeFormat (no hardcoded "x giờ trước" strings). Returns the
 * label + the age in hours (for the >24h "needs attention" flag).
 */
function formatRelativeAge(
  createdAtIso: string,
  now: Date,
): { label: string; ageHours: number } {
  const created = new Date(createdAtIso)
  const ageMs = now.getTime() - created.getTime()
  const ageMinutes = Math.floor(ageMs / (1000 * 60))
  const ageHours = Math.floor(ageMs / (1000 * 60 * 60))
  const ageDays = Math.floor(ageHours / 24)
  let label: string
  if (ageMinutes < 1) {
    label = "vừa xong"
  } else if (ageHours < 1) {
    label = RELATIVE_TIME.format(-ageMinutes, "minute")
  } else if (ageHours < 24) {
    label = RELATIVE_TIME.format(-ageHours, "hour")
  } else {
    label = RELATIVE_TIME.format(-ageDays, "day")
  }
  return { label, ageHours }
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
    rejected_by_display: null, // Backend does not provide rejected_by_name yet
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
  profile_name: string | null
  // From API denormalized names
  created_by_display: string
  created_at_formatted: string
  is_pending: boolean
  is_online: boolean
  is_own: boolean
  // Permission flags from API (with Maker-Checker)
  can_verify: boolean
  can_reject: boolean
}

/**
 * Transform a list of payments for table display.
 *
 * Takes the LIST contract (`PaymentListItem`), NOT the detail `Payment`: the
 * backend list endpoint returns `is_online` + `created_by_name` directly (the
 * summary has no `intent_id` / `created_by_id` to recompute from).
 */
export function toPaymentListViewModel(
  payments: PaymentListItem[],
): PaymentListItemViewModel[] {
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
      profile_name: payment.profile_name,
      // From API denormalized name (no created_by_id on the list contract).
      created_by_display: payment.created_by_name ?? "Không rõ",
      created_at_formatted: formatDate(payment.created_at) ?? "",
      is_pending: payment.status === "pending",
      is_online: payment.is_online,
      is_own: payment.is_own,
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
 * Transform pending payments for the maker-checker verification queue.
 *
 * Takes the LIST contract (`PaymentListItem`). The "age" is rendered with
 * `Intl.RelativeTimeFormat` (vi), never a hardcoded "x giờ trước" string.
 * `now` is injected so callers can keep it stable across a render.
 */
export function toPendingPaymentListViewModel(
  payments: PaymentListItem[],
  now: Date = new Date(),
): PendingPaymentViewModel[] {
  return payments
    .filter((p) => p.status === "pending")
    .map((payment) => {
      const { label: ageDisplay, ageHours } = formatRelativeAge(payment.created_at, now)

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
        profile_name: payment.profile_name,
        // From API denormalized name (no created_by_id on the list contract).
        created_by_display: payment.created_by_name ?? "Không rõ",
        created_at_formatted: formatDate(payment.created_at) ?? "",
        is_pending: true,
        is_online: payment.is_online,
        is_own: payment.is_own,
        // Permission flags from API (with Maker-Checker)
        can_verify: payment.can_verify,
        can_reject: payment.can_reject,
        needs_attention: ageHours >= 24, // Older than 24 hours
        age_hours: ageHours,
        age_display: ageDisplay,
      }
    })
}
