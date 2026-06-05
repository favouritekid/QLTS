/**
 * SignalCell — compact decision-signal cell for the reviewer cockpit.
 *
 * One tight box: a title + tone dot, a primary data line, an optional secondary
 * status line. Shared shell so every cockpit signal (eligibility / priority /
 * score / documents) reads the same. NOT a full Card (the cockpit panel owns the
 * outer shell — no card-in-card).
 *
 * Thin Client: pure presentation; callers pass already-derived BE fields.
 */

"use client"

import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  CircleDot,
  type LucideIcon,
} from "lucide-react"

export type SignalTone = "success" | "warning" | "error" | "neutral"

const TONE: Record<
  SignalTone,
  { icon: LucideIcon; dot: string; text: string; border: string }
> = {
  success: { icon: CheckCircle2, dot: "text-success-600", text: "text-success-700", border: "border-success-200" },
  warning: { icon: AlertTriangle, dot: "text-warning-600", text: "text-warning-700", border: "border-warning-200" },
  error: { icon: AlertCircle, dot: "text-error-600", text: "text-error-700", border: "border-error-200" },
  neutral: { icon: CircleDot, dot: "text-muted-foreground", text: "text-foreground", border: "border-border" },
}

interface SignalCellProps {
  title: string
  tone: SignalTone
  /** Key data point (bold). */
  primary: ReactNode
  /** Optional status detail line. */
  secondary?: ReactNode
  testId?: string
}

export function SignalCell({ title, tone, primary, secondary, testId }: SignalCellProps) {
  const t = TONE[tone]
  const Icon = t.icon
  return (
    <div
      data-testid={testId}
      className={cn("min-w-0 rounded-lg border bg-card p-3", t.border)}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium text-muted-foreground">{title}</span>
        <Icon className={cn("h-4 w-4 shrink-0", t.dot)} aria-hidden="true" />
      </div>
      <div className={cn("mt-1 text-sm font-semibold break-words", t.text)}>{primary}</div>
      {secondary != null && secondary !== "" && (
        <div className="mt-0.5 text-xs text-muted-foreground break-words">{secondary}</div>
      )}
    </div>
  )
}
