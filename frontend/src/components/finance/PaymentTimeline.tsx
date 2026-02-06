// src/components/finance/PaymentTimeline.tsx
"use client"

import * as React from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  CheckCircle,
  Clock,
  XCircle,
  RefreshCcw,
  CreditCard,
  User,
  Calendar,
} from "lucide-react"
import { AmountDisplay, PaymentStatusBadge } from "@/components/finance"
import { cn } from "@/lib/utils"
import type { Payment, PaymentSummary, PaymentStatus } from "@/types/finance.types"

// =============================================================================
// TYPES
// =============================================================================

export interface PaymentTimelineProps {
  /** List of payments to display */
  payments: (Payment | PaymentSummary)[]
  /** Show header with title */
  showHeader?: boolean
  /** Header title */
  title?: string
  /** Empty state message */
  emptyMessage?: string
  /** Additional class name */
  className?: string
}

export interface PaymentTimelineItemProps {
  payment: Payment | PaymentSummary
  isLast?: boolean
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function formatDateTime(dateString: string | null): string {
  if (!dateString) return "-"
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(dateString))
}

function formatDate(dateString: string | null): string {
  if (!dateString) return "-"
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(dateString))
}

function getStatusIcon(status: PaymentStatus) {
  switch (status) {
    case "verified":
      return <CheckCircle className="h-4 w-4 text-success-600" />
    case "pending":
      return <Clock className="h-4 w-4 text-warning-600" />
    case "rejected":
      return <XCircle className="h-4 w-4 text-destructive" />
    case "refunded":
      return <RefreshCcw className="h-4 w-4 text-muted-foreground" />
    default:
      return <CreditCard className="h-4 w-4 text-muted-foreground" />
  }
}

function getStatusColor(status: PaymentStatus): string {
  switch (status) {
    case "verified":
      return "border-success-500 bg-success-50/50 dark:bg-success-950/20"
    case "pending":
      return "border-warning-500 bg-warning-50/50 dark:bg-warning-950/20"
    case "rejected":
      return "border-destructive bg-destructive/5"
    case "refunded":
      return "border-muted-foreground bg-muted/50"
    default:
      return ""
  }
}

// =============================================================================
// TIMELINE ITEM COMPONENT
// =============================================================================

function PaymentTimelineItem({ payment, isLast = false }: PaymentTimelineItemProps) {
  // Determine if this is a full Payment or PaymentSummary
  const isFullPayment = "created_by_name" in payment

  return (
    <div className="relative flex gap-4">
      {/* Timeline line */}
      {!isLast && (
        <div className="absolute left-[19px] top-10 bottom-0 w-[2px] bg-border" />
      )}

      {/* Status icon */}
      <div
        className={cn(
          "relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 bg-background",
          getStatusColor(payment.status)
        )}
      >
        {getStatusIcon(payment.status)}
      </div>

      {/* Content */}
      <div className="flex-1 pb-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <AmountDisplay
                amount={payment.amount}
                size="md"
                className="font-semibold"
              />
              <PaymentStatusBadge status={payment.status} size="sm" />
            </div>

            <div className="mt-1 space-y-1 text-sm text-muted-foreground">
              {/* Payment date */}
              <div className="flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                <span>
                  {formatDate(payment.payment_date || payment.created_at)}
                </span>
              </div>

              {/* Created by (if full Payment) */}
              {isFullPayment && (payment as Payment).created_by_name && (
                <div className="flex items-center gap-1">
                  <User className="h-3 w-3" />
                  <span>Ghi nhận: {(payment as Payment).created_by_name}</span>
                </div>
              )}

              {/* Verified by (if full Payment and verified) */}
              {isFullPayment &&
                payment.status === "verified" &&
                (payment as Payment).verified_by_name && (
                  <div className="flex items-center gap-1">
                    <CheckCircle className="h-3 w-3" />
                    <span>Xác minh: {(payment as Payment).verified_by_name}</span>
                  </div>
                )}

              {/* Reference code (if full Payment) */}
              {isFullPayment && (payment as Payment).reference_code && (
                <div className="text-xs">
                  Mã GD: <span className="font-mono">{(payment as Payment).reference_code}</span>
                </div>
              )}

              {/* Rejection reason */}
              {isFullPayment &&
                payment.status === "rejected" &&
                (payment as Payment).rejection_reason && (
                  <div className="text-xs text-destructive">
                    Lý do: {(payment as Payment).rejection_reason}
                  </div>
                )}
            </div>
          </div>

          {/* Timestamp */}
          <div className="text-xs text-muted-foreground">
            {formatDateTime(payment.created_at)}
          </div>
        </div>
      </div>
    </div>
  )
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

/**
 * PaymentTimeline - Display payment history as a vertical timeline
 *
 * Features:
 * - Shows payment amount, status, date
 * - Color-coded status indicators
 * - Shows who created/verified the payment
 * - Reference code display
 * - Rejection reason for rejected payments
 *
 * @example
 * ```tsx
 * <PaymentTimeline
 *   payments={invoice.payments}
 *   title="Lịch sử thanh toán"
 * />
 * ```
 */
export function PaymentTimeline({
  payments,
  showHeader = true,
  title = "Lịch sử thanh toán",
  emptyMessage = "Chưa có thanh toán nào",
  className,
}: PaymentTimelineProps) {
  // Sort payments by created_at descending (newest first)
  const sortedPayments = React.useMemo(() => {
    return [...payments].sort((a, b) => {
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })
  }, [payments])

  if (payments.length === 0) {
    return (
      <Card className={className}>
        {showHeader && (
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              {title}
            </CardTitle>
          </CardHeader>
        )}
        <CardContent>
          <div className="text-center py-8 text-muted-foreground">
            <CreditCard className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>{emptyMessage}</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={className}>
      {showHeader && (
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            {title}
            <Badge variant="secondary" className="ml-2">
              {payments.length}
            </Badge>
          </CardTitle>
        </CardHeader>
      )}
      <CardContent>
        <div className="space-y-0">
          {sortedPayments.map((payment, index) => (
            <PaymentTimelineItem
              key={payment.id}
              payment={payment}
              isLast={index === sortedPayments.length - 1}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default PaymentTimeline
