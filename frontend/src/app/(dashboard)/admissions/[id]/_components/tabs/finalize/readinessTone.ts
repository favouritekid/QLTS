/**
 * Shared ReadinessTone → presentation maps (badge variant / icon / text colour).
 *
 * Single source for the tone styling consumed by ReadinessHero + ReviewerCockpit
 * so a tone rename / new tier is edited once instead of per-component (the
 * "Hero and cockpit must agree" invariant the readiness hook works to preserve
 * is then also true at the presentation layer). SignalCell uses its own SignalTone
 * (no `info` tier) so it intentionally keeps a separate map.
 */

import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Info,
  CircleDot,
  type LucideIcon,
} from "lucide-react"
import type { ReadinessTone } from "./useSubmissionReadiness"

export type ReadinessBadgeVariant = "success" | "warning" | "error" | "info" | "secondary"

export const READINESS_TONE_VARIANT: Record<ReadinessTone, ReadinessBadgeVariant> = {
  success: "success",
  warning: "warning",
  error: "error",
  info: "info",
  neutral: "secondary",
}

export const READINESS_TONE_ICON: Record<ReadinessTone, LucideIcon> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
  info: Info,
  neutral: CircleDot,
}

export const READINESS_TONE_TEXT: Record<ReadinessTone, string> = {
  success: "text-success-700",
  warning: "text-warning-700",
  error: "text-error-600",
  info: "text-info-700",
  neutral: "text-foreground",
}
