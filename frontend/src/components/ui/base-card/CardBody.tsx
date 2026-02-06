// src/components/ui/base-card/CardBody.tsx
import * as React from "react"
import { cn } from "@/lib/utils"

export interface CardBodyProps {
  children: React.ReactNode
  /** Additional className */
  className?: string
}

/**
 * CardBody - Container for business data fields
 *
 * Contains CardField components for label:value pairs.
 * Recommended: 2-4 fields maximum for mobile readability.
 *
 * @example
 * ```tsx
 * <CardBody>
 *   <CardField label="Email" value="user@example.com" />
 *   <CardField label="Điện thoại" value="0901234567" />
 * </CardBody>
 * ```
 */
export function CardBody({ children, className }: CardBodyProps) {
  return (
    <div className={cn("space-y-1", className)}>
      {children}
    </div>
  )
}

CardBody.displayName = "CardBody"

// ---

export interface CardFieldProps {
  /** Field label */
  label: string
  /** Field value - can be string, number, or React node */
  value: React.ReactNode
  /** Icon to display before label */
  icon?: React.ReactNode
  /** Additional className */
  className?: string
}

/**
 * CardField - Single label:value pair
 *
 * Typography:
 * - Label: text-xs text-muted-foreground (12px)
 * - Value: text-sm (14px)
 *
 * @example
 * ```tsx
 * <CardField
 *   icon={<Mail className="h-3 w-3" />}
 *   label="Email"
 *   value="user@example.com"
 * />
 * ```
 */
export function CardField({ label, value, icon, className }: CardFieldProps) {
  return (
    <div className={cn("flex items-center gap-1.5 text-sm", className)}>
      {icon && (
        <span className="text-muted-foreground flex-shrink-0">
          {icon}
        </span>
      )}
      <span className="text-muted-foreground flex-shrink-0">
        {label}:
      </span>
      <span className="truncate">
        {value ?? "—"}
      </span>
    </div>
  )
}

CardField.displayName = "CardField"

// ---

export interface CardFieldRowProps {
  children: React.ReactNode
  /** Additional className */
  className?: string
}

/**
 * CardFieldRow - Horizontal row for multiple short fields
 *
 * Use when you have 2-3 short fields that fit on one line.
 *
 * @example
 * ```tsx
 * <CardFieldRow>
 *   <CardField label="Tuổi" value="22" />
 *   <CardField label="Giới tính" value="Nam" />
 * </CardFieldRow>
 * ```
 */
export function CardFieldRow({ children, className }: CardFieldRowProps) {
  return (
    <div className={cn("flex items-center gap-4 flex-wrap", className)}>
      {children}
    </div>
  )
}

CardFieldRow.displayName = "CardFieldRow"
