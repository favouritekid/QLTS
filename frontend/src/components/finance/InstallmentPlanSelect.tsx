// src/components/finance/InstallmentPlanSelect.tsx
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
import { Calendar, AlertTriangle, Loader2, CheckCircle } from "lucide-react"
import { useInstallmentPlanOptions } from "@/hooks/finance/useInstallmentPlans"
import { cn } from "@/lib/utils"

// =============================================================================
// TYPES
// =============================================================================

export interface InstallmentPlanSelectProps {
  /** Selected plan code (empty string for default/one-time payment) */
  value: string
  /** Callback when selection changes */
  onChange: (value: string) => void
  /** Placeholder text */
  placeholder?: string
  /** Disabled state */
  disabled?: boolean
  /** Error state */
  error?: boolean
  /** Show "One-time payment" as first option */
  showOneTimeOption?: boolean
  /** Label for one-time payment option */
  oneTimeLabel?: string
  /** Additional class name */
  className?: string
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * InstallmentPlanSelect - Dropdown for selecting installment plan
 *
 * Features:
 * - Fetches installment plans from API
 * - Shows installment count
 * - Shows penalty indicator
 * - Optional "One-time payment" first option
 * - Loading state with skeleton
 *
 * @example
 * ```tsx
 * <InstallmentPlanSelect
 *   value={planCode}
 *   onChange={setPlanCode}
 *   showOneTimeOption
 * />
 * ```
 */
export function InstallmentPlanSelect({
  value,
  onChange,
  placeholder = "Chọn kế hoạch trả góp...",
  disabled = false,
  error = false,
  showOneTimeOption = true,
  oneTimeLabel = "Thanh toán 1 lần (mặc định)",
  className,
}: InstallmentPlanSelectProps) {
  const { options, isLoading, isError } = useInstallmentPlanOptions()

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

  // Find selected option for display
  const selectedOption = options.find((opt) => opt.value === value)

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger
        className={cn(
          error && "border-destructive focus-visible:ring-destructive",
          className
        )}
      >
        <SelectValue placeholder={placeholder}>
          {value !== "" && (
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 shrink-0" />
              <span>
                {value === ""
                  ? oneTimeLabel
                  : selectedOption?.label ?? placeholder}
              </span>
            </div>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {/* One-time payment option */}
        {showOneTimeOption && (
          <SelectItem value="">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-4 w-4 shrink-0 text-success-600" />
              <span>{oneTimeLabel}</span>
            </div>
          </SelectItem>
        )}

        {/* Installment plan options */}
        {options.map((option) => (
          <SelectItem
            key={option.value}
            value={option.value}
            disabled={option.disabled}
          >
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span>{option.label}</span>
              {option.has_penalty && (
                <Badge
                  variant="outline"
                  className="ml-auto text-xs border-warning-500 text-warning-600"
                >
                  <AlertTriangle className="h-3 w-3 mr-1" />
                  Phí trễ hạn
                </Badge>
              )}
            </div>
          </SelectItem>
        ))}

        {/* Empty state */}
        {options.length === 0 && !showOneTimeOption && (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Không có kế hoạch trả góp nào
          </div>
        )}
      </SelectContent>
    </Select>
  )
}

export default InstallmentPlanSelect
