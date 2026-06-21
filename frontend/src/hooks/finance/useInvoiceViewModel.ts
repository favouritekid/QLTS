/**
 * Invoice ViewModel Hook
 *
 * Transforms Invoice API data into UI-ready display values.
 * Implements FRONTEND_ARCHITECTURE_V3 Section 2.6.6 ViewModel Pattern.
 *
 * Rules:
 * - Computes display values (labels, variants)
 * - Uses API-provided can_* permission flags (Thin Client compliance)
 * - Memoizes to prevent re-renders
 * - NO business logic - only presentation
 */

import { useMemo } from "react"
import { useInvoiceDetail } from "./useInvoices"
import {
  INVOICE_STATUS_LABELS,
  INVOICE_STATUS_VARIANTS,
} from "@/types/finance.types"
import type { InvoiceDetail, InvoiceListItem } from "@/types/finance.types"
import { formatVND, parseAmount } from "@/lib/zod/finance"

// =====================================================================
// VIEWMODEL TYPE
// =====================================================================

export interface InvoiceViewModel extends Omit<InvoiceDetail, "status"> {
  // Original values
  status: InvoiceDetail["status"]

  // Computed display values
  status_label: string
  status_variant: "default" | "secondary" | "destructive" | "outline"

  // Formatted amounts
  amount_formatted: string
  paid_amount_formatted: string
  remaining_amount_formatted: string
  penalty_amount_formatted: string
  total_due_formatted: string

  // Progress percentage (0-100)
  payment_progress: number

  // Formatted dates
  due_date_formatted: string
  issued_at_formatted: string | null

  // UI-ready boolean flags (from API can_* permission flags)
  show_issue_button: boolean
  show_cancel_button: boolean
  show_record_payment_button: boolean
  show_penalty_button: boolean
  is_paid: boolean
  is_overdue: boolean
  is_draft: boolean
  is_cancelled: boolean
  has_payments: boolean

  // Days until/past due
  days_until_due: number | null
  is_due_soon: boolean // Due within 7 days
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
    }).format(new Date(dateStr))
  } catch {
    return dateStr
  }
}

function calculateDaysUntilDue(dueDate: string): number | null {
  try {
    const due = new Date(dueDate)
    const now = new Date()
    const diffTime = due.getTime() - now.getTime()
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    return diffDays
  } catch {
    return null
  }
}

/**
 * Whole days a due date is in the PAST (today − due_date), date-only.
 * Returns 0 when the date is today or in the future. Display-only: the overdue
 * STATE itself is backend-owned (`is_overdue`); this only formats "quá N ngày".
 */
export function calculateOverdueDays(dueDate: string): number {
  try {
    const due = new Date(dueDate)
    if (Number.isNaN(due.getTime())) return 0
    const startOfDue = Date.UTC(due.getFullYear(), due.getMonth(), due.getDate())
    const now = new Date()
    const startOfToday = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
    const diffDays = Math.floor((startOfToday - startOfDue) / (1000 * 60 * 60 * 24))
    return diffDays > 0 ? diffDays : 0
  } catch {
    return 0
  }
}

// =====================================================================
// TRANSFORM FUNCTION
// =====================================================================

/**
 * Transform InvoiceDetail to InvoiceViewModel
 * Pure function for testing and reuse
 */
export function toInvoiceViewModel(invoice: InvoiceDetail): InvoiceViewModel {
  const amount = parseAmount(invoice.amount)
  const paidAmount = parseAmount(invoice.paid_amount)
  const paymentProgress = amount > 0 ? Math.min(100, Math.round((paidAmount / amount) * 100)) : 0
  const daysUntilDue = calculateDaysUntilDue(invoice.due_date)

  return {
    ...invoice,
    // Computed display values
    status_label: INVOICE_STATUS_LABELS[invoice.status] ?? invoice.status,
    status_variant: INVOICE_STATUS_VARIANTS[invoice.status] ?? "secondary",

    // Formatted amounts
    amount_formatted: formatVND(invoice.amount),
    paid_amount_formatted: formatVND(invoice.paid_amount),
    remaining_amount_formatted: formatVND(invoice.remaining_amount),
    penalty_amount_formatted: formatVND(invoice.penalty_amount),
    total_due_formatted: formatVND(invoice.total_due),

    // Progress
    payment_progress: paymentProgress,

    // Formatted dates
    due_date_formatted: formatDate(invoice.due_date) ?? "",
    issued_at_formatted: formatDate(invoice.issued_at),

    // UI-ready boolean flags (from API can_* permission flags - Thin Client)
    show_issue_button: invoice.can_issue,
    show_cancel_button: invoice.can_cancel,
    show_record_payment_button: invoice.can_record_payment,
    show_penalty_button: invoice.can_apply_penalty,
    is_paid: invoice.status === "paid",
    // Backend-owned derived flag (issued/partial AND due<today). Do NOT infer
    // from the enum status — the `overdue` enum lags the job, so trust `is_overdue`.
    is_overdue: invoice.is_overdue ?? false,
    is_draft: invoice.status === "draft",
    is_cancelled: invoice.status === "cancelled",
    has_payments: invoice.payments.length > 0,

    // Due date calculations
    days_until_due: daysUntilDue,
    is_due_soon: daysUntilDue !== null && daysUntilDue > 0 && daysUntilDue <= 7,
  }
}

// =====================================================================
// VIEWMODEL HOOK
// =====================================================================

/**
 * Invoice ViewModel Hook
 *
 * @param invoiceId - The invoice ID to fetch and transform
 * @param options - Query options
 *
 * @example
 * ```tsx
 * function InvoiceDetailClient({ invoiceId }: { invoiceId: number }) {
 *   const { data: invoice, isLoading, error } = useInvoiceViewModel(invoiceId)
 *
 *   if (isLoading) return <Skeleton />
 *   if (error) return <ErrorBoundary error={error} />
 *   if (!invoice) return null
 *
 *   return (
 *     <div>
 *       <Badge variant={invoice.status_variant}>{invoice.status_label}</Badge>
 *       <p>Còn lại: {invoice.remaining_amount_formatted}</p>
 *       <p>Hạn thanh toán: {invoice.due_date_formatted}</p>
 *       {invoice.is_due_soon && <Alert>Sắp đến hạn thanh toán!</Alert>}
 *       {invoice.show_record_payment_button && <Button>Ghi nhận thanh toán</Button>}
 *     </div>
 *   )
 * }
 * ```
 */
export function useInvoiceViewModel(
  invoiceId: number,
  options?: { enabled?: boolean }
) {
  const query = useInvoiceDetail(invoiceId, options)

  const viewModel = useMemo(() => {
    if (!query.data) return null
    return toInvoiceViewModel(query.data)
  }, [query.data])

  return {
    ...query,
    data: viewModel,
  }
}

// =====================================================================
// LIST VIEWMODEL
// =====================================================================

export interface InvoiceListItemViewModel {
  id: number
  fee_id: number
  invoice_number: string
  installment_no: number
  // List enrichment (who + what) from GET /api/invoices
  profile_id: number | null
  profile_name: string | null
  profile_code: string | null
  program_name: string | null
  officer_name: string | null
  fee_type: string | null
  semester_no: number | null
  status: string
  status_label: string
  status_variant: "default" | "secondary" | "destructive" | "outline"
  amount: string // raw Decimal string (for thresholds / re-format)
  amount_formatted: string
  paid_amount_formatted: string
  remaining_amount: string // raw Decimal string
  remaining_amount_formatted: string
  // Penalty (raw Decimal string), total due (amount + penalty) formatted, and a
  // convenience flag so the amount cell can switch its headline figure to
  // `total_due_formatted` + show a "(gồm … phạt)" subline when penalty > 0.
  penalty_amount: string
  total_due_formatted: string
  has_penalty: boolean
  due_date: string // raw ISO date
  due_date_formatted: string
  // Backend-owned overdue STATE (single source of truth). FE never recomputes it.
  is_overdue: boolean
  // Display-only: whole days past due (today − due_date), 0 when not past.
  overdue_days: number
  is_paid: boolean
  // Permission flags from API
  can_issue: boolean
  can_cancel: boolean
  can_record_payment: boolean
  can_apply_penalty: boolean
}

/**
 * Transform a list of invoices (`InvoiceListItem` from GET /api/invoices) for
 * table/card display. Uses the backend-owned `is_overdue` flag verbatim — the
 * derived `overdue_days` is presentation-only (formats "quá N ngày").
 */
export function toInvoiceListViewModel(invoices: InvoiceListItem[]): InvoiceListItemViewModel[] {
  return invoices.map((invoice) => {
    return {
      id: invoice.id,
      fee_id: invoice.fee_id,
      invoice_number: invoice.invoice_number,
      installment_no: invoice.installment_no,
      profile_id: invoice.profile_id ?? null,
      profile_name: invoice.profile_name ?? null,
      profile_code: invoice.profile_code ?? null,
      program_name: invoice.program_name ?? null,
      officer_name: invoice.officer_name ?? null,
      fee_type: invoice.fee_type ?? null,
      semester_no: invoice.semester_no ?? null,
      status: invoice.status,
      status_label: INVOICE_STATUS_LABELS[invoice.status] ?? invoice.status,
      status_variant: INVOICE_STATUS_VARIANTS[invoice.status] ?? "secondary",
      amount: invoice.amount,
      amount_formatted: formatVND(invoice.amount),
      paid_amount_formatted: formatVND(invoice.paid_amount),
      remaining_amount: invoice.remaining_amount,
      remaining_amount_formatted: formatVND(invoice.remaining_amount),
      penalty_amount: invoice.penalty_amount,
      total_due_formatted: formatVND(invoice.total_due),
      has_penalty: parseAmount(invoice.penalty_amount) > 0,
      due_date: invoice.due_date,
      due_date_formatted: formatDate(invoice.due_date) ?? "",
      is_overdue: invoice.is_overdue,
      overdue_days: invoice.is_overdue ? calculateOverdueDays(invoice.due_date) : 0,
      is_paid: invoice.status === "paid",
      // Permission flags from API
      can_issue: invoice.can_issue,
      can_cancel: invoice.can_cancel,
      can_record_payment: invoice.can_record_payment,
      can_apply_penalty: invoice.can_apply_penalty,
    }
  })
}
