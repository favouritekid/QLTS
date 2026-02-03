// src/components/finance/PaymentMethodSelect.tsx
"use client"

import * as React from "react"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { CreditCard, Wifi, WifiOff, Loader2 } from "lucide-react"
import { usePaymentMethodOptions } from "@/hooks/finance/usePaymentMethods"
import { cn } from "@/lib/utils"

// =============================================================================
// TYPES
// =============================================================================

export interface PaymentMethodSelectProps {
  /** Selected method ID */
  value: number | null
  /** Callback when selection changes */
  onChange: (value: number | null) => void
  /** Filter: all, online, or manual methods */
  filter?: "all" | "online" | "manual"
  /** Placeholder text */
  placeholder?: string
  /** Disabled state */
  disabled?: boolean
  /** Error state */
  error?: boolean
  /** Additional class name */
  className?: string
  /** Hide online/manual indicator */
  hideIndicator?: boolean
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * PaymentMethodSelect - Dropdown for selecting payment method
 *
 * Features:
 * - Fetches payment methods from API
 * - Filter by online/manual methods
 * - Shows online/offline indicator
 * - Loading state with skeleton
 * - Disabled methods are grayed out
 *
 * @example
 * ```tsx
 * // All methods
 * <PaymentMethodSelect
 *   value={methodId}
 *   onChange={setMethodId}
 * />
 *
 * // Online methods only
 * <PaymentMethodSelect
 *   value={methodId}
 *   onChange={setMethodId}
 *   filter="online"
 *   placeholder="Chọn cổng thanh toán..."
 * />
 * ```
 */
export function PaymentMethodSelect({
  value,
  onChange,
  filter = "all",
  placeholder = "Chọn phương thức thanh toán...",
  disabled = false,
  error = false,
  className,
  hideIndicator = false,
}: PaymentMethodSelectProps) {
  const { options, isLoading, isError } = usePaymentMethodOptions(filter)

  // Handle value change
  const handleValueChange = (newValue: string) => {
    if (newValue === "none") {
      onChange(null)
    } else {
      onChange(parseInt(newValue, 10))
    }
  }

  // Loading state
  if (isLoading) {
    return (
      <div className={cn("relative", className)}>
        <Skeleton className="h-10 w-full" />
        <div className="absolute inset-y-0 right-3 flex items-center">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      </div>
    )
  }

  // Error state
  if (isError) {
    return (
      <Select disabled>
        <SelectTrigger className={cn("text-destructive", className)}>
          <SelectValue placeholder="Lỗi tải dữ liệu" />
        </SelectTrigger>
      </Select>
    )
  }

  // Empty state
  if (options.length === 0) {
    return (
      <Select disabled>
        <SelectTrigger className={className}>
          <SelectValue placeholder="Không có phương thức nào" />
        </SelectTrigger>
      </Select>
    )
  }

  return (
    <Select
      value={value?.toString() ?? "none"}
      onValueChange={handleValueChange}
      disabled={disabled}
    >
      <SelectTrigger
        className={cn(
          error && "border-destructive focus:ring-destructive",
          className
        )}
      >
        <SelectValue placeholder={placeholder}>
          {value !== null && (
            <div className="flex items-center gap-2">
              <CreditCard className="h-4 w-4 shrink-0" />
              <span>
                {options.find((opt) => opt.value === value)?.label ?? placeholder}
              </span>
            </div>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem
            key={option.value}
            value={option.value.toString()}
            disabled={option.disabled}
          >
            <div className="flex items-center gap-2">
              <CreditCard className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span>{option.label}</span>
              {!hideIndicator && (
                <Badge
                  variant="outline"
                  className={cn(
                    "ml-auto text-xs",
                    option.is_online
                      ? "border-success-500 text-success-600"
                      : "border-muted-foreground text-muted-foreground"
                  )}
                >
                  {option.is_online ? (
                    <>
                      <Wifi className="h-3 w-3 mr-1" />
                      Online
                    </>
                  ) : (
                    <>
                      <WifiOff className="h-3 w-3 mr-1" />
                      Thủ công
                    </>
                  )}
                </Badge>
              )}
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export default PaymentMethodSelect
