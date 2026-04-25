// src/components/finance/FeeStatusLink.tsx
"use client"

import * as React from "react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Calculator,
  ExternalLink,
  AlertTriangle,
  CheckCircle,
  Clock,
} from "lucide-react"
import { useProfileFinanceSummary } from "@/hooks/finance/useFees"
import { AmountDisplay } from "./AmountDisplay"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/lib/stores/auth.store"
import { hasFinanceAccess } from "@/lib/config/roles"

// =============================================================================
// TYPES
// =============================================================================

export interface FeeStatusLinkProps {
  profileId: number
  className?: string
  /** Show detailed info or just badge */
  variant?: "badge" | "card"
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * FeeStatusLink - READ-ONLY component for Admission cross-reference
 *
 * Shows fee status for an admission profile and links to the Finance module.
 * This enables Phase separation: Admission Module shows status, Finance Module handles actions.
 *
 * @example
 * ```tsx
 * // In Admission Profile Detail
 * <FeeStatusLink profileId={123} variant="card" />
 * ```
 */
export function FeeStatusLink({
  profileId,
  className,
  variant = "badge",
}: FeeStatusLinkProps) {
  const { data: summary, isLoading, error } = useProfileFinanceSummary(profileId)
  const userRole = useAuthStore((s) => s.user?.role)
  const canAccessFinanceModule = hasFinanceAccess(userRole)

  if (isLoading) {
    return variant === "badge" ? (
      <Skeleton className="h-6 w-24" />
    ) : (
      <Skeleton className="h-20 w-full rounded-lg" />
    )
  }

  if (error || !summary) {
    return null // Don't show anything if finance data unavailable
  }

  const hasFee = summary.fees.length > 0
  const totalRemaining = parseFloat(summary.total_remaining.replace(/[^\d.-]/g, "")) || 0
  const isPaid = hasFee && totalRemaining === 0
  const hasOverdue = summary.overdue_invoices > 0

  // Badge variant - minimal display
  if (variant === "badge") {
    if (!hasFee) {
      const badge = (
        <Badge
          variant="outline"
          className={cn(
            canAccessFinanceModule ? "cursor-pointer hover:bg-muted" : "cursor-default",
            className
          )}
        >
          <Calculator className="h-3 w-3 mr-1" />
          Chưa tính phí
        </Badge>
      )
      return canAccessFinanceModule ? (
        <Link href={`/finance/fees?profile_id=${profileId}`}>{badge}</Link>
      ) : (
        badge
      )
    }

    const badge = (
      <Badge
        variant={isPaid ? "default" : hasOverdue ? "destructive" : "secondary"}
        className={cn(canAccessFinanceModule ? "cursor-pointer" : "cursor-default", className)}
      >
        {isPaid ? (
          <>
            <CheckCircle className="h-3 w-3 mr-1" />
            Đã thanh toán
          </>
        ) : hasOverdue ? (
          <>
            <AlertTriangle className="h-3 w-3 mr-1" />
            Quá hạn
          </>
        ) : (
          <>
            <Clock className="h-3 w-3 mr-1" />
            Còn nợ
          </>
        )}
      </Badge>
    )
    return canAccessFinanceModule ? (
      <Link href={`/finance/fees?profile_id=${profileId}`}>{badge}</Link>
    ) : (
      badge
    )
  }

  // Card variant - detailed display
  const card = (
    <div
      className={cn(
        "block p-4 rounded-lg border",
        canAccessFinanceModule && "hover:bg-muted/50 transition-colors",
        hasOverdue && "border-destructive/50 bg-destructive/5",
        isPaid && "border-success-500/50 bg-success-50/30 dark:bg-success-950/20",
        className
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calculator className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">Tài chính</span>
        </div>
        {canAccessFinanceModule && <ExternalLink className="h-4 w-4 text-muted-foreground" />}
      </div>

      {!hasFee ? (
        <p className="text-sm text-muted-foreground mt-2">
          Chưa tính phí cho hồ sơ này
        </p>
      ) : (
        <div className="mt-2 space-y-1">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Tổng phí:</span>
            <AmountDisplay amount={summary.total_fees} size="sm" />
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Đã thanh toán:</span>
            <AmountDisplay amount={summary.total_paid} size="sm" />
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Còn lại:</span>
            <AmountDisplay
              amount={summary.total_remaining}
              size="sm"
              className={cn(
                totalRemaining > 0 && "text-warning-600",
                hasOverdue && "text-destructive"
              )}
            />
          </div>
          {hasOverdue && (
            <div className="flex items-center gap-1 text-xs text-destructive mt-2">
              <AlertTriangle className="h-3 w-3" />
              {summary.overdue_invoices} hóa đơn quá hạn
            </div>
          )}
        </div>
      )}
    </div>
  )

  return canAccessFinanceModule ? (
    <Link href={`/finance/fees?profile_id=${profileId}`}>{card}</Link>
  ) : (
    card
  )
}

export default FeeStatusLink
