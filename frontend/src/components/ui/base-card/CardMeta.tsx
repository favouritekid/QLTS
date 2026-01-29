// src/components/ui/base-card/CardMeta.tsx
import * as React from "react"
import { format, formatDistanceToNow } from "date-fns"
import { vi } from "date-fns/locale"
import { cn } from "@/lib/utils"
import { Clock, Calendar } from "lucide-react"

export interface CardMetaProps {
  children: React.ReactNode
  /** Additional className */
  className?: string
}

/**
 * CardMeta - Footer row for status badges, timestamps, and tags
 *
 * Layout: flex row with wrap, items centered, gap-2
 *
 * @example
 * ```tsx
 * <CardMeta>
 *   <Badge variant="success">Active</Badge>
 *   <CardTime date={createdAt} />
 *   <span className="text-xs text-muted-foreground">Tag</span>
 * </CardMeta>
 * ```
 */
export function CardMeta({ children, className }: CardMetaProps) {
  return (
    <div className={cn(
      "flex items-center gap-2 flex-wrap pt-1",
      className
    )}>
      {children}
    </div>
  )
}

CardMeta.displayName = "CardMeta"

// ---

export interface CardTimeProps {
  /** Date to display */
  date: Date | string | null | undefined
  /**
   * Display format:
   * - "relative": "2 giờ trước" (default)
   * - "date": "15/01/2025"
   * - "datetime": "15/01 14:30"
   * - "time": "14:30"
   */
  format?: "relative" | "date" | "datetime" | "time"
  /** Show icon */
  showIcon?: boolean
  /** Additional className */
  className?: string
}

/**
 * CardTime - Standardized time display for cards
 *
 * Standardized formats:
 * - relative: "2 giờ trước" (Vietnamese locale)
 * - date: "dd/MM/yyyy"
 * - datetime: "dd/MM HH:mm"
 * - time: "HH:mm"
 *
 * @example
 * ```tsx
 * <CardTime date={createdAt} format="relative" />
 * <CardTime date={updatedAt} format="date" showIcon />
 * ```
 */
export function CardTime({
  date,
  format: displayFormat = "relative",
  showIcon = false,
  className,
}: CardTimeProps) {
  if (!date) return null

  const dateObj = typeof date === "string" ? new Date(date) : date

  // Check for invalid date
  if (isNaN(dateObj.getTime())) return null

  let displayText: string
  let Icon = Clock

  switch (displayFormat) {
    case "relative":
      displayText = formatDistanceToNow(dateObj, {
        addSuffix: true,
        locale: vi
      })
      break
    case "date":
      displayText = format(dateObj, "dd/MM/yyyy")
      Icon = Calendar
      break
    case "datetime":
      displayText = format(dateObj, "dd/MM HH:mm")
      break
    case "time":
      displayText = format(dateObj, "HH:mm")
      break
    default:
      displayText = format(dateObj, "dd/MM/yyyy")
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs text-muted-foreground",
        className
      )}
      suppressHydrationWarning
    >
      {showIcon && <Icon className="h-3 w-3" />}
      <span suppressHydrationWarning>{displayText}</span>
    </span>
  )
}

CardTime.displayName = "CardTime"
