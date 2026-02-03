// src/components/finance/FinanceStatusBadges.tsx
"use client"

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import {
  Clock,
  Calculator,
  FileText,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Ban,
  Percent,
  CreditCard,
  RefreshCw,
} from "lucide-react"
import {
  FEE_STATUS_LABELS,
  INVOICE_STATUS_LABELS,
  PAYMENT_STATUS_LABELS,
  type FeeStatus,
  type InvoiceStatus,
  type PaymentStatus,
} from "@/types/finance.types"

// =============================================================================
// BADGE VARIANTS
// =============================================================================

const financeBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        // Fee statuses
        "fee-pending": "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
        "fee-calculated": "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
        "fee-invoiced": "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400",
        "fee-partial": "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
        "fee-paid": "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
        "fee-overdue": "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
        "fee-waived": "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
        "fee-cancelled": "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400",

        // Invoice statuses
        "invoice-draft": "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
        "invoice-issued": "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
        "invoice-partial": "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
        "invoice-paid": "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
        "invoice-cancelled": "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400",
        "invoice-overdue": "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",

        // Payment statuses
        "payment-pending": "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
        "payment-verified": "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
        "payment-rejected": "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
        "payment-refunded": "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
      },
      size: {
        sm: "text-[10px] px-2 py-0.5",
        md: "text-xs px-2.5 py-0.5",
        lg: "text-sm px-3 py-1",
      },
    },
    defaultVariants: {
      size: "md",
    },
  }
)

// =============================================================================
// ICON MAPPINGS
// =============================================================================

const feeStatusIcons: Record<FeeStatus, React.ComponentType<{ className?: string }>> = {
  pending: Clock,
  calculated: Calculator,
  invoiced: FileText,
  partial: CreditCard,
  paid: CheckCircle2,
  overdue: AlertTriangle,
  waived: Percent,
  cancelled: Ban,
}

const invoiceStatusIcons: Record<InvoiceStatus, React.ComponentType<{ className?: string }>> = {
  draft: FileText,
  issued: FileText,
  partial: CreditCard,
  paid: CheckCircle2,
  cancelled: XCircle,
  overdue: AlertTriangle,
}

const paymentStatusIcons: Record<PaymentStatus, React.ComponentType<{ className?: string }>> = {
  pending: Clock,
  verified: CheckCircle2,
  rejected: XCircle,
  refunded: RefreshCw,
}

// =============================================================================
// TYPES
// =============================================================================

interface BaseBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Show icon */
  showIcon?: boolean
  /** Show dot indicator instead of icon */
  showDot?: boolean
  /** Size variant */
  size?: "sm" | "md" | "lg"
}

// =============================================================================
// FEE STATUS BADGE
// =============================================================================

export interface FeeStatusBadgeProps extends BaseBadgeProps {
  /** Fee status from API */
  status: FeeStatus
}

/**
 * Fee status badge with appropriate styling and icon
 *
 * @example
 * ```tsx
 * <FeeStatusBadge status="paid" />
 * <FeeStatusBadge status="overdue" showIcon />
 * ```
 */
export function FeeStatusBadge({
  status,
  showIcon = false,
  showDot = false,
  size = "md",
  className,
  ...props
}: FeeStatusBadgeProps) {
  const Icon = feeStatusIcons[status]
  const label = FEE_STATUS_LABELS[status] ?? status
  const variant = `fee-${status}` as const

  return (
    <span
      className={cn(financeBadgeVariants({ variant, size }), className)}
      {...props}
    >
      {showDot && !showIcon && (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      )}
      {showIcon && Icon && <Icon className="h-3 w-3" />}
      {label}
    </span>
  )
}

// =============================================================================
// INVOICE STATUS BADGE
// =============================================================================

export interface InvoiceStatusBadgeProps extends BaseBadgeProps {
  /** Invoice status from API */
  status: InvoiceStatus
}

/**
 * Invoice status badge with appropriate styling and icon
 *
 * @example
 * ```tsx
 * <InvoiceStatusBadge status="issued" />
 * <InvoiceStatusBadge status="overdue" showIcon />
 * ```
 */
export function InvoiceStatusBadge({
  status,
  showIcon = false,
  showDot = false,
  size = "md",
  className,
  ...props
}: InvoiceStatusBadgeProps) {
  const Icon = invoiceStatusIcons[status]
  const label = INVOICE_STATUS_LABELS[status] ?? status
  const variant = `invoice-${status}` as const

  return (
    <span
      className={cn(financeBadgeVariants({ variant, size }), className)}
      {...props}
    >
      {showDot && !showIcon && (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      )}
      {showIcon && Icon && <Icon className="h-3 w-3" />}
      {label}
    </span>
  )
}

// =============================================================================
// PAYMENT STATUS BADGE
// =============================================================================

export interface PaymentStatusBadgeProps extends BaseBadgeProps {
  /** Payment status from API */
  status: PaymentStatus
}

/**
 * Payment status badge with appropriate styling and icon
 *
 * @example
 * ```tsx
 * <PaymentStatusBadge status="pending" />
 * <PaymentStatusBadge status="verified" showIcon />
 * ```
 */
export function PaymentStatusBadge({
  status,
  showIcon = false,
  showDot = false,
  size = "md",
  className,
  ...props
}: PaymentStatusBadgeProps) {
  const Icon = paymentStatusIcons[status]
  const label = PAYMENT_STATUS_LABELS[status] ?? status
  const variant = `payment-${status}` as const

  return (
    <span
      className={cn(financeBadgeVariants({ variant, size }), className)}
      {...props}
    >
      {showDot && !showIcon && (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      )}
      {showIcon && Icon && <Icon className="h-3 w-3" />}
      {label}
    </span>
  )
}

// =============================================================================
// EXPORTS
// =============================================================================

export { financeBadgeVariants }
