// src/components/ui/base-card/CardHeader.tsx
import * as React from "react"
import { cn } from "@/lib/utils"

export interface CardHeaderProps {
  /** Primary text - main identifier (name, title) */
  title: React.ReactNode
  /** Secondary text - supporting info (ID, email) */
  subtitle?: React.ReactNode
  /** Badge to display next to title (status, priority) */
  badge?: React.ReactNode
  /** Additional className */
  className?: string
}

/**
 * CardHeader - Title row with optional subtitle and badge
 *
 * Layout:
 * ┌────────────────────────────────┐
 * │ Title [Badge]                  │
 * │ Subtitle                       │
 * └────────────────────────────────┘
 *
 * Typography:
 * - Title: font-medium text-sm (14px)
 * - Subtitle: text-xs text-muted-foreground (12px)
 *
 * @example
 * ```tsx
 * <CardHeader
 *   title="Nguyễn Văn A"
 *   subtitle="Lead #123"
 *   badge={<Badge variant="success">Hot</Badge>}
 * />
 * ```
 */
export function CardHeader({
  title,
  subtitle,
  badge,
  className,
}: CardHeaderProps) {
  return (
    <div className={cn("space-y-0.5", className)}>
      {/* Title row */}
      <div className="flex items-center gap-2 pr-8">
        <span className="font-medium text-sm truncate">
          {title}
        </span>
        {badge}
      </div>

      {/* Subtitle */}
      {subtitle && (
        <div className="text-xs text-muted-foreground truncate">
          {subtitle}
        </div>
      )}
    </div>
  )
}

CardHeader.displayName = "CardHeader"
