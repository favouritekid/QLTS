// src/components/finance/FeeCard.tsx
"use client"

import * as React from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { MoreHorizontal, Eye, Percent, XCircle, RefreshCw } from "lucide-react"
import { cn } from "@/lib/utils"
import { AmountDisplay, RemainingAmount } from "./AmountDisplay"
import { FeeStatusBadge } from "./FinanceStatusBadges"
import { FEE_TYPE_LABELS, type FeeType, type FeeStatus } from "@/types/finance.types"
import type { FeeListItemViewModel } from "@/hooks/finance/useFeeViewModel"

// =============================================================================
// TYPES
// =============================================================================

export interface FeeCardProps {
  /** Fee data from ViewModel */
  fee: FeeListItemViewModel
  /** Click handler for view action */
  onView?: (fee: FeeListItemViewModel) => void
  /** Click handler for waive action */
  onWaive?: (fee: FeeListItemViewModel) => void
  /** Click handler for cancel action */
  onCancel?: (fee: FeeListItemViewModel) => void
  /** Click handler for recalculate action */
  onRecalculate?: (fee: FeeListItemViewModel) => void
  /** Additional class name */
  className?: string
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * FeeCard - Mobile-friendly card display for Fee items
 *
 * Used in list views and mobile layouts.
 * Shows fee summary with payment progress and available actions.
 *
 * @example
 * ```tsx
 * <FeeCard
 *   fee={feeViewModel}
 *   onView={(fee) => router.push(`/finance/fees/${fee.id}`)}
 *   onWaive={(fee) => openWaiveDialog(fee)}
 * />
 * ```
 */
export function FeeCard({
  fee,
  onView,
  onWaive,
  onCancel,
  onRecalculate,
  className,
}: FeeCardProps) {
  const hasActions = fee.can_waive || fee.can_cancel || fee.can_recalculate

  return (
    <Card className={cn("hover:shadow-md transition-shadow", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <p className="font-medium text-sm truncate">
              {FEE_TYPE_LABELS[fee.fee_type as FeeType] ?? fee.fee_type}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Năm học: {fee.academic_year}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <FeeStatusBadge status={fee.status as FeeStatus} size="sm" />
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
                  <DropdownMenuItem onClick={() => onView?.(fee)}>
                    <Eye className="h-4 w-4 mr-2" />
                    Xem chi tiết
                  </DropdownMenuItem>
                  {fee.can_waive && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={() => onWaive?.(fee)}>
                        <Percent className="h-4 w-4 mr-2" />
                        Miễn giảm
                      </DropdownMenuItem>
                    </>
                  )}
                  {fee.can_recalculate && (
                    <DropdownMenuItem onClick={() => onRecalculate?.(fee)}>
                      <RefreshCw className="h-4 w-4 mr-2" />
                      Tính lại
                    </DropdownMenuItem>
                  )}
                  {fee.can_cancel && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => onCancel?.(fee)}
                        className="text-destructive focus:text-destructive"
                      >
                        <XCircle className="h-4 w-4 mr-2" />
                        Hủy
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Amount summary */}
        <div className="flex justify-between items-end">
          <div>
            <p className="text-xs text-muted-foreground">Tổng cộng</p>
            <AmountDisplay
              amount={fee.final_amount_formatted}
              size="lg"
              showCurrency={false}
              className="text-foreground"
            />
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground">Còn lại</p>
            <RemainingAmount
              amount={fee.remaining_amount_formatted}
              size="md"
              showCurrency={false}
            />
          </div>
        </div>

        {/* Payment progress */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Tiến độ thanh toán</span>
            <span className="font-medium">{fee.payment_progress}%</span>
          </div>
          <Progress
            value={fee.payment_progress}
            className="h-2"
            aria-label={`Đã thanh toán ${fee.payment_progress}%`}
          />
        </div>

        {/* Due date if available */}
        {fee.due_date_formatted && (
          <div className="flex justify-between text-xs pt-1 border-t">
            <span className="text-muted-foreground">Hạn thanh toán</span>
            <span className={cn(fee.is_overdue && "text-destructive font-medium")}>
              {fee.due_date_formatted}
            </span>
          </div>
        )}

        {/* View detail button - touch friendly */}
        <Button
          variant="outline"
          className="w-full min-h-[44px] mt-2"
          onClick={() => onView?.(fee)}
        >
          Xem chi tiết
        </Button>
      </CardContent>
    </Card>
  )
}

// =============================================================================
// FEE SUMMARY CARD (for cross-reference)
// =============================================================================

export interface FeeSummaryCardProps {
  /** Profile ID to link to */
  profileId: number
  /** Fee status */
  status: FeeStatus
  /** Total amount */
  totalAmount: string
  /** Paid amount */
  paidAmount: string
  /** Remaining amount */
  remainingAmount: string
  /** Show link to finance module */
  showLink?: boolean
  /** Additional class name */
  className?: string
}

/**
 * FeeSummaryCard - Compact fee summary for Admission profile
 *
 * Shows read-only fee status with optional link to Finance module.
 * Used in Admission Detail page for cross-reference.
 */
export function FeeSummaryCard({
  profileId,
  status,
  totalAmount,
  paidAmount,
  remainingAmount,
  showLink = true,
  className,
}: FeeSummaryCardProps) {
  const content = (
    <Card className={cn("hover:shadow-sm transition-shadow", className)}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium">Thông tin học phí</span>
          <FeeStatusBadge status={status} size="sm" />
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-xs text-muted-foreground">Tổng</p>
            <AmountDisplay amount={totalAmount} size="sm" showCurrency={false} />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Đã nộp</p>
            <AmountDisplay amount={paidAmount} size="sm" showCurrency={false} />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Còn lại</p>
            <RemainingAmount amount={remainingAmount} size="sm" showCurrency={false} />
          </div>
        </div>
      </CardContent>
    </Card>
  )

  if (showLink) {
    return (
      <Link href={`/finance/fees?profile_id=${profileId}`} className="block">
        {content}
      </Link>
    )
  }

  return content
}

export default FeeCard
