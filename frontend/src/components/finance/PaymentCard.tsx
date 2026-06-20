// src/components/finance/PaymentCard.tsx
"use client"

import * as React from "react"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  MoreHorizontal,
  Eye,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  Globe,
  CreditCard,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { AmountDisplay } from "./AmountDisplay"
import { PaymentStatusBadge } from "./FinanceStatusBadges"
import type { PaymentStatus } from "@/types/finance.types"
import type {
  PaymentListItemViewModel,
  PendingPaymentViewModel,
} from "@/hooks/finance/usePaymentViewModel"

// =============================================================================
// TYPES
// =============================================================================

export interface PaymentCardProps {
  /** Payment data from ViewModel */
  payment: PaymentListItemViewModel
  /** Click handler for view action */
  onView?: (payment: PaymentListItemViewModel) => void
  /** Click handler for verify action */
  onVerify?: (payment: PaymentListItemViewModel) => void
  /** Click handler for reject action */
  onReject?: (payment: PaymentListItemViewModel) => void
  /** Additional class name */
  className?: string
}

// =============================================================================
// PAYMENT CARD (General)
// =============================================================================

/**
 * PaymentCard - Mobile-friendly card display for Payment items
 *
 * Used in list views and mobile layouts.
 * Shows payment summary with Maker-Checker actions.
 *
 * @example
 * ```tsx
 * <PaymentCard
 *   payment={paymentViewModel}
 *   onVerify={(p) => openVerifyDialog(p)}
 *   onReject={(p) => openRejectDialog(p)}
 * />
 * ```
 */
export function PaymentCard({
  payment,
  onView,
  onVerify,
  onReject,
  className,
}: PaymentCardProps) {
  const hasActions = payment.can_verify || payment.can_reject

  return (
    <Card className={cn("hover:shadow-md transition-shadow", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              {payment.is_online ? (
                <Globe className="h-4 w-4 text-muted-foreground" />
              ) : (
                <CreditCard className="h-4 w-4 text-muted-foreground" />
              )}
              <p className="font-medium text-sm">
                {payment.reference_code || `#${payment.id}`}
              </p>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {payment.payer_name || "Không rõ người nộp"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <PaymentStatusBadge status={payment.status as PaymentStatus} size="sm" />
            {hasActions && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    aria-label="Thao tác"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onView?.(payment)}>
                    <Eye className="h-4 w-4 mr-2" />
                    Xem chi tiết
                  </DropdownMenuItem>
                  {payment.can_verify && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => onVerify?.(payment)}
                        className="text-success-600"
                      >
                        <CheckCircle className="h-4 w-4 mr-2" />
                        Xác minh
                      </DropdownMenuItem>
                    </>
                  )}
                  {payment.can_reject && (
                    <DropdownMenuItem
                      onClick={() => onReject?.(payment)}
                      className="text-destructive focus:text-destructive"
                    >
                      <XCircle className="h-4 w-4 mr-2" />
                      Từ chối
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Amount */}
        <div className="flex justify-between items-center">
          <span className="text-xs text-muted-foreground">Số tiền</span>
          <AmountDisplay amount={payment.amount_formatted} size="lg" showCurrency={false} />
        </div>

        {/* Creator info */}
        <div className="flex justify-between text-xs pt-2 border-t">
          <span className="text-muted-foreground">Người tạo</span>
          <span>{payment.created_by_display}</span>
        </div>

        {/* Date */}
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">Ngày tạo</span>
          <span>{payment.created_at_formatted}</span>
        </div>

        {/* Payment date if different */}
        {payment.payment_date_formatted && (
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Ngày thanh toán</span>
            <span>{payment.payment_date_formatted}</span>
          </div>
        )}

        {/* Action buttons for Maker-Checker */}
        {hasActions && (
          <div className="flex gap-2 pt-2 border-t">
            {payment.can_verify && (
              <Button
                variant="default"
                size="sm"
                className="flex-1 min-h-[44px] bg-success-600 hover:bg-success-700"
                onClick={() => onVerify?.(payment)}
              >
                <CheckCircle className="h-4 w-4 mr-2" />
                Xác minh
              </Button>
            )}
            {payment.can_reject && (
              <Button
                variant="destructive"
                size="sm"
                className="flex-1 min-h-[44px]"
                onClick={() => onReject?.(payment)}
              >
                <XCircle className="h-4 w-4 mr-2" />
                Từ chối
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// =============================================================================
// PENDING PAYMENT CARD (Verification Queue)
// =============================================================================

export interface PendingPaymentCardProps {
  /** Pending payment data from ViewModel */
  payment: PendingPaymentViewModel
  /** Click handler for view action */
  onView?: (payment: PendingPaymentViewModel) => void
  /** Click handler for verify action */
  onVerify?: (payment: PendingPaymentViewModel) => void
  /** Click handler for reject action */
  onReject?: (payment: PendingPaymentViewModel) => void
  /** Additional class name */
  className?: string
}

/**
 * PendingPaymentCard - Card for verification queue
 *
 * Shows additional age information and highlights payments needing attention.
 * Used in the Payments verification queue.
 */
export function PendingPaymentCard({
  payment,
  onView,
  onVerify,
  onReject,
  className,
}: PendingPaymentCardProps) {
  return (
    <Card
      className={cn(
        "hover:shadow-md transition-shadow",
        payment.needs_attention && "border-warning-500 bg-warning-50/50 dark:bg-warning-950/20",
        className
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              {payment.is_online ? (
                <Globe className="h-4 w-4 text-muted-foreground" />
              ) : (
                <CreditCard className="h-4 w-4 text-muted-foreground" />
              )}
              <p className="font-medium text-sm">
                {payment.reference_code || `#${payment.id}`}
              </p>
              {payment.needs_attention && (
                <Badge variant="outline" className="text-warning-600 border-warning-500 ml-auto">
                  <AlertTriangle className="h-3 w-3 mr-1" />
                  Cần xử lý
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {payment.payer_name || "Không rõ người nộp"}
            </p>
          </div>
          <PaymentStatusBadge status={payment.status as PaymentStatus} size="sm" />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Amount */}
        <div className="flex justify-between items-center">
          <span className="text-xs text-muted-foreground">Số tiền</span>
          <AmountDisplay amount={payment.amount_formatted} size="lg" showCurrency={false} />
        </div>

        {/* Creator and Age */}
        <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t">
          <div>
            <span className="text-muted-foreground">Người tạo</span>
            <p className="font-medium truncate">{payment.created_by_display}</p>
          </div>
          <div className="text-right">
            <span className="text-muted-foreground">Thời gian chờ</span>
            <p className={cn(
              "font-medium",
              payment.needs_attention && "text-warning-600"
            )}>
              <Clock className="h-3 w-3 inline mr-1" />
              {payment.age_display}
            </p>
          </div>
        </div>

        {/* Maker-checker reason: own payment cannot be self-verified. Shown
            instead of a hidden/dead verify button so the user understands why. */}
        {payment.is_own && payment.is_pending && (
          <p
            className="flex items-center gap-1.5 rounded-md bg-muted/60 px-2.5 py-1.5 text-xs text-muted-foreground"
            role="note"
          >
            <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Khoản bạn tạo — cần người khác duyệt
          </p>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 pt-2 border-t">
          {payment.can_verify && (
            <Button
              variant="default"
              size="sm"
              className="flex-1 min-h-[44px] bg-success-600 hover:bg-success-700"
              onClick={() => onVerify?.(payment)}
            >
              <CheckCircle className="h-4 w-4 mr-2" />
              Xác minh
            </Button>
          )}
          {payment.can_reject && (
            <Button
              variant="destructive"
              size="sm"
              className="flex-1 min-h-[44px]"
              onClick={() => onReject?.(payment)}
            >
              <XCircle className="h-4 w-4 mr-2" />
              Từ chối
            </Button>
          )}
          {!payment.can_verify && !payment.can_reject && (
            <Button
              variant="outline"
              size="sm"
              className="w-full min-h-[44px]"
              onClick={() => onView?.(payment)}
            >
              <Eye className="h-4 w-4 mr-2" />
              Xem chi tiết
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export default PaymentCard
