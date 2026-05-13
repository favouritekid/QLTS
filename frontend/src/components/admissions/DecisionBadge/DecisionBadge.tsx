/**
 * Phase 3 PR-3D-A Sub-2 — Choice-level DecisionBadge component.
 *
 * Candidate-facing badge shown on AdmissionProfileChoice rows post-engine
 * cascade. Distinct from `StatusBadge` (profile-level workflow state)
 * because:
 *   - Choice-level: rendered per NV row trong choice list
 *   - Candidate-facing: prominent styling cho thí sinh xem kết quả
 *   - Decision-specific copy: "Đậu NV1" vs generic "Đã duyệt"
 *
 * Variants supported (matching AdmissionProfileChoice.decision enum):
 *   - admitted     — Đậu NV{order} (green check)
 *   - waitlisted   — Chờ ghế (amber clock)
 *   - rejected     — Trượt (red x)
 *   - result_published — Đã công bố (info icon) — used as Profile-level
 *     when applied to AdmissionProfile.status='result_published' (pre-decision
 *     view); rare for choice-level
 *   - skip / pending — Chờ xét (neutral) — fallback variants
 *
 * Reuses styling tokens từ `status-badge.config.ts` (already configured
 * Phase 1 #11). NEW: candidate-facing larger size variant + optional
 * display_order suffix.
 */

import { cn } from "@/lib/utils"
import { CheckCircle2, Clock, XCircle, Send, Hourglass } from "lucide-react"
import type { ReactNode } from "react"

export type ChoiceDecision =
  | "pending"
  | "admitted"
  | "waitlisted"
  | "rejected"
  | "skip"

export type DecisionBadgeSize = "sm" | "md" | "lg"

interface DecisionBadgeProps {
  /** AdmissionProfileChoice.decision value */
  decision: ChoiceDecision
  /** Optional display_order for "Đậu NV{n}" suffix (admitted variant) */
  displayOrder?: number
  /** Size variant — `lg` cho candidate-facing announcement */
  size?: DecisionBadgeSize
  /** Override default className */
  className?: string
}

interface DecisionConfig {
  label: string
  icon: ReactNode
  className: string
}

const SIZE_CLASSES: Record<DecisionBadgeSize, string> = {
  sm: "text-xs px-2 py-0.5 gap-1",
  md: "text-sm px-2.5 py-1 gap-1.5",
  lg: "text-base px-3 py-1.5 gap-2 font-semibold",
}

function getIconSize(size: DecisionBadgeSize): string {
  return size === "lg" ? "h-5 w-5" : size === "md" ? "h-4 w-4" : "h-3 w-3"
}

function getConfig(
  decision: ChoiceDecision,
  displayOrder: number | undefined,
  iconSize: string,
): DecisionConfig {
  switch (decision) {
    case "admitted":
      return {
        label: displayOrder ? `Đậu NV${displayOrder}` : "Đậu",
        icon: <CheckCircle2 className={iconSize} />,
        className: "bg-green-50 text-green-700 border-green-200",
      }
    case "waitlisted":
      return {
        label: displayOrder ? `Chờ ghế NV${displayOrder}` : "Chờ ghế",
        icon: <Clock className={iconSize} />,
        className: "bg-amber-50 text-amber-700 border-amber-200",
      }
    case "rejected":
      return {
        label: "Trượt",
        icon: <XCircle className={iconSize} />,
        className: "bg-red-50 text-red-700 border-red-200",
      }
    case "skip":
      return {
        label: "Bỏ xét",
        icon: <XCircle className={iconSize} />,
        className: "bg-gray-50 text-gray-600 border-gray-200",
      }
    case "pending":
    default:
      return {
        label: "Chờ xét",
        icon: <Hourglass className={iconSize} />,
        className: "bg-blue-50 text-blue-700 border-blue-200",
      }
  }
}

/**
 * Candidate-facing choice decision badge.
 *
 * @example
 * <DecisionBadge decision="admitted" displayOrder={1} size="lg" />
 * → renders "✓ Đậu NV1" large green badge
 *
 * @example
 * <DecisionBadge decision="waitlisted" displayOrder={2} />
 * → renders "🕐 Chờ ghế NV2" medium amber badge
 */
export function DecisionBadge({
  decision,
  displayOrder,
  size = "md",
  className,
}: DecisionBadgeProps) {
  const iconSize = getIconSize(size)
  const config = getConfig(decision, displayOrder, iconSize)

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border font-medium",
        SIZE_CLASSES[size],
        config.className,
        className,
      )}
      role="status"
      aria-label={config.label}
    >
      {config.icon}
      <span>{config.label}</span>
    </span>
  )
}


/**
 * Profile-level result_published variant — distinct usage when the
 * candidate has not received per-choice decisions yet (post T6 publish
 * but before per-choice cascade visible). Renders as "Đã công bố" info
 * style.
 */
export function ResultPublishedBadge({
  size = "md",
  className,
}: Pick<DecisionBadgeProps, "size" | "className">) {
  const iconSize = getIconSize(size)
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border font-medium",
        SIZE_CLASSES[size],
        "bg-sky-50 text-sky-700 border-sky-200",
        className,
      )}
      role="status"
      aria-label="Đã công bố kết quả"
    >
      <Send className={iconSize} />
      <span>Đã công bố KQ</span>
    </span>
  )
}
