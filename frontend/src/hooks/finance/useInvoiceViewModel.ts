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
import type { InvoiceDetail, Invoice } from "@/types/finance.types"
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
    is_overdue: invoice.status === "overdue",
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
  status: string
  status_label: string
  status_variant: "default" | "secondary" | "destructive" | "outline"
  amount_formatted: string
  paid_amount_formatted: string
  remaining_amount_formatted: string
  payment_progress: number
  due_date_formatted: string
  is_overdue: boolean
  is_due_soon: boolean
  days_until_due: number | null
  // Permission flags from API
  can_issue: boolean
  can_cancel: boolean
  can_record_payment: boolean
  can_apply_penalty: boolean
}

/**
 * Transform a list of invoices for table display
 */
export function toInvoiceListViewModel(invoices: Invoice[]): InvoiceListItemViewModel[] {
  return invoices.map((invoice) => {
    const amount = parseAmount(invoice.amount)
    const paidAmount = parseAmount(invoice.paid_amount)
    const paymentProgress = amount > 0 ? Math.min(100, Math.round((paidAmount / amount) * 100)) : 0
    const daysUntilDue = calculateDaysUntilDue(invoice.due_date)

    return {
      id: invoice.id,
      fee_id: invoice.fee_id,
      invoice_number: invoice.invoice_number,
      installment_no: invoice.installment_no,
      status: invoice.status,
      status_label: INVOICE_STATUS_LABELS[invoice.status] ?? invoice.status,
      status_variant: INVOICE_STATUS_VARIANTS[invoice.status] ?? "secondary",
      amount_formatted: formatVND(invoice.amount),
      paid_amount_formatted: formatVND(invoice.paid_amount),
      remaining_amount_formatted: formatVND(invoice.remaining_amount),
      payment_progress: paymentProgress,
      due_date_formatted: formatDate(invoice.due_date) ?? "",
      is_overdue: invoice.status === "overdue",
      is_due_soon: daysUntilDue !== null && daysUntilDue > 0 && daysUntilDue <= 7,
      days_until_due: daysUntilDue,
      // Permission flags from API
      can_issue: invoice.can_issue,
      can_cancel: invoice.can_cancel,
      can_record_payment: invoice.can_record_payment,
      can_apply_penalty: invoice.can_apply_penalty,
    }
  })
}
