/**
 * IssueLocator — reviewer "Cần yêu cầu sửa" strip (ReviewerCockpit only).
 *
 * Lets a reviewer LOCATE which step to bounce back ("Yêu cầu sửa") WITHOUT pulling
 * the officer's full SectionReview table into the cockpit (that would re-create the
 * wall-of-information). Compact chips only: "Step X · N lỗi/cảnh báo", max 3 + "+N".
 *
 * Rules (plan #7 decision):
 *   - Only backend-derived issues that carry a step (readiness.actionItems — Step 7
 *     is never among them, B4). Grouped by step, error steps first.
 *   - CTA is "Xem Step X" (navigate), NOT "Sửa Step X" — reviewers don't edit the
 *     officer's data; navigation routes through AdmissionDetailClient's
 *     unsaved-changes guard via onNavigateToStep(step).
 *   - If there are warnings but NONE carry a step, show one line pointing to
 *     InspectionDetails — never a noisy "Mục cần xử lý: 0".
 *   - Renders nothing when there is no work to locate.
 */

"use client"

import { AlertCircle, AlertTriangle, ArrowRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { getAdmissionStepLabel } from "@/lib/constants/admission-steps"
import type { ReadinessActionItem } from "./useSubmissionReadiness"

interface IssueLocatorProps {
  items: ReadinessActionItem[]
  /** True when there are warning signals (e.g. docs/step-less es.warnings) open. */
  hasOutstandingWarnings: boolean
  onNavigateToStep: (step: number) => void
}

const MAX_CHIPS = 3

interface StepSummary {
  step: number
  count: number
  hasError: boolean
}

/** Collapse action items to one entry per step: total count + worst severity. */
function summarizeByStep(items: ReadinessActionItem[]): StepSummary[] {
  const byStep = new Map<number, StepSummary>()
  for (const it of items) {
    const cur = byStep.get(it.step) ?? { step: it.step, count: 0, hasError: false }
    cur.count += it.count ?? 1
    if (it.severity === "error") cur.hasError = true
    byStep.set(it.step, cur)
  }
  // error steps first, then ascending step (mirrors the action-item sort).
  return [...byStep.values()].sort((a, b) => {
    if (a.hasError !== b.hasError) return a.hasError ? -1 : 1
    return a.step - b.step
  })
}

export function IssueLocator({ items, hasOutstandingWarnings, onNavigateToStep }: IssueLocatorProps) {
  if (items.length === 0) {
    if (!hasOutstandingWarnings) return null
    // Warnings with no routable step → point to the detail, NOT a "0" metric.
    return (
      <p className="text-xs text-warning-700" data-testid="issue-locator-warning">
        Có cảnh báo cần rà soát trong phần “Chi tiết kiểm tra” bên dưới.
      </p>
    )
  }

  const steps = summarizeByStep(items)
  const shown = steps.slice(0, MAX_CHIPS)
  const overflow = steps.length - shown.length

  return (
    <div className="space-y-1.5" data-testid="issue-locator">
      <p className="text-xs font-medium text-muted-foreground">Cần yêu cầu sửa</p>
      <div className="flex flex-wrap items-center gap-2">
        {shown.map((s) => {
          const Icon = s.hasError ? AlertCircle : AlertTriangle
          return (
            <button
              key={s.step}
              type="button"
              onClick={() => onNavigateToStep(s.step)}
              aria-label={`Xem Bước ${s.step} — ${getAdmissionStepLabel(s.step)}`}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                s.hasError ? "border-error-200 text-error-700" : "border-warning-200 text-warning-700",
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="whitespace-nowrap">
                Bước {s.step} · {s.count} vấn đề
              </span>
              <ArrowRight className="h-3 w-3 shrink-0" aria-hidden="true" />
            </button>
          )
        })}
        {overflow > 0 && (
          <span className="text-xs text-muted-foreground">+{overflow} bước khác</span>
        )}
      </div>
    </div>
  )
}
