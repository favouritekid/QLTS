// src/components/finance/AmountDisplay.tsx
"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { formatVND } from "@/lib/zod/finance"

// =============================================================================
// TYPES
// =============================================================================

export interface AmountDisplayProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Amount as string (from API) or number */
  amount: string | number
  /** Show currency suffix (default: true) */
  showCurrency?: boolean
  /** Currency code (default: VND) */
  currency?: string
  /** Size variant */
  size?: "sm" | "md" | "lg" | "xl"
  /** Color variant based on amount */
  colorize?: boolean
  /** Highlight negative/overdue amounts */
  highlightNegative?: boolean
}

// =============================================================================
// SIZE CLASSES
// =============================================================================

const sizeClasses = {
  sm: "text-xs",
  md: "text-sm",
  lg: "text-base font-medium",
  xl: "text-lg font-semibold",
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * AmountDisplay - Formatted currency display for Finance module
 *
 * @example
 * ```tsx
 * <AmountDisplay amount="15000000" />
 * // Output: 15.000.000 ₫
 *
 * <AmountDisplay amount={0} colorize />
 * // Output: 0 ₫ (muted color)
 *
 * <AmountDisplay amount="5000000" size="xl" />
 * // Output: 5.000.000 ₫ (large, semibold)
 * ```
 */
export function AmountDisplay({
  amount,
  showCurrency = true,
  currency = "₫",
  size = "md",
  colorize = false,
  highlightNegative = false,
  className,
  ...props
}: AmountDisplayProps) {
  // Parse amount to number for comparison
  const numericAmount = typeof amount === "string"
    ? parseFloat(amount.replace(/[^\d.-]/g, "")) || 0
    : amount

  // Format the amount
  const formattedAmount = formatVND(amount)

  // Remove the default ₫ suffix if we're adding our own
  const displayAmount = showCurrency
    ? formattedAmount
    : formattedAmount.replace(/\s*₫$/, "")

  // Determine color classes
  const colorClasses = colorize
    ? numericAmount > 0
      ? "text-foreground"
      : numericAmount === 0
        ? "text-muted-foreground"
        : "text-destructive"
    : ""

  const negativeClasses = highlightNegative && numericAmount < 0
    ? "text-destructive font-medium"
    : ""

  return (
    <span
      className={cn(
        "tabular-nums",
        sizeClasses[size],
        colorClasses,
        negativeClasses,
        className
      )}
      {...props}
    >
      {displayAmount}
    </span>
  )
}

// =============================================================================
// CONVENIENCE COMPONENTS
// =============================================================================

/**
 * Display remaining amount with appropriate styling
 */
export function RemainingAmount({
  amount,
  className,
  ...props
}: Omit<AmountDisplayProps, "colorize" | "highlightNegative">) {
  const numericAmount = typeof amount === "string"
    ? parseFloat(amount.replace(/[^\d.-]/g, "")) || 0
    : amount

  return (
    <AmountDisplay
      amount={amount}
      className={cn(
        numericAmount > 0 && "text-warning-600 dark:text-warning-400",
        numericAmount === 0 && "text-success-600 dark:text-success-400",
        className
      )}
      {...props}
    />
  )
}

/**
 * Display paid amount with success styling when complete
 */
export function PaidAmount({
  amount,
  totalAmount,
  className,
  ...props
}: Omit<AmountDisplayProps, "colorize"> & { totalAmount?: string | number }) {
  const paid = typeof amount === "string"
    ? parseFloat(amount.replace(/[^\d.-]/g, "")) || 0
    : amount
  const total = totalAmount
    ? typeof totalAmount === "string"
      ? parseFloat(totalAmount.replace(/[^\d.-]/g, "")) || 0
      : totalAmount
    : null

  const isFullyPaid = total !== null && paid >= total

  return (
    <AmountDisplay
      amount={amount}
      className={cn(
        isFullyPaid && "text-success-600 dark:text-success-400 font-medium",
        className
      )}
      {...props}
    />
  )
}

export default AmountDisplay
