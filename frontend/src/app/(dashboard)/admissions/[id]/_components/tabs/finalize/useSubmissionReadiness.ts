/**
 * useSubmissionReadiness — Step 8 readiness derivation (Thin Client).
 *
 * Pure READ + MAP over backend-computed fields. NEVER recomputes eligibility,
 * scores, or workflow state. All inputs come from the backend response or the
 * permission flags FinalizeTab already received (single source — no second
 * `usePermissions`/role check).
 *
 * Two Hero signals (STEP8 plan B3/B5):
 *   1. eligibilityVerdict — "Đủ điều kiện xét" vs "Chưa đủ" — reads
 *      `eligibility_status` (xét-tuyển state, independent of any action).
 *   2. primaryAction + readinessLabel/Tone — tracks the ACTUAL primary action
 *      currently surfaced (submit/resubmit/approve/publish/enroll/...). It only
 *      drives Hero label/tone; it NEVER filters the decision button cluster.
 *
 * ActionItems source (Phase 3 — structured-first, heuristic fallback):
 *   - PREFERRED: `executive_summary.critical_blockers` / `warnings` when they are
 *     structured objects with a numeric `.step` (BE Phase 3) → route each to its
 *     exact step; severity from the item (blocker→error, warning→warning).
 *   - FALLBACK (legacy string[] / missing step / no executive_summary):
 *     `grouped_validation_errors` (personal_info→1, scores→5, documents→6) +
 *     `step_status[2|3]` (family/academic).
 *   - `derivePriorityIssues`→Step 4 is FE-derived (never in executive_summary) and
 *     is ALWAYS added (deduped against any Step 4 already present).
 *   - Step 7 (Học phí) is display-only → BE emits no item + heuristic never adds
 *     one → NEVER an ActionItem.
 */

import { useMemo } from "react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { derivePriorityIssues } from "../../layout/priorityIssues"
import { getStatusConfig } from "@/lib/status-config"
import {
  GROUPED_SECTION_TO_STEP,
  getAdmissionStepLabel,
  type GroupedSectionKey,
} from "@/lib/constants/admission-steps"

export type PrimaryAction =
  | "submit"
  | "resubmit"
  | "approve"
  | "publish_result"
  | "enroll"
  | "request_revision"
  | "reject"
  | "none"

export type ReadinessTone = "success" | "warning" | "error" | "info" | "neutral"

export type EligibilityVerdict = "eligible" | "ineligible" | "pending"

export interface ReadinessActionItem {
  /** Stable key — one item per step (steps never collide). */
  id: string
  /** Pipeline step this item routes to via "Sửa Step X". */
  step: number
  severity: "error" | "warning"
  /** Short summary line for THIS section (not the tab's granular FormMessages). */
  message: string
  /** message-level (grouped/priority) vs section-level (step_status). */
  source: "message" | "section"
}

export interface SubmissionReadiness {
  eligibilityVerdict: EligibilityVerdict
  eligibilityLabel: string
  eligibilityTone: ReadinessTone
  primaryAction: PrimaryAction
  readinessLabel: string
  readinessTone: ReadinessTone
  actionItems: ReadinessActionItem[]
  /** N = number of action items (≈ sections needing work, NOT total errors). */
  actionItemCount: number
  /** Optional "next action" hint from executive_summary (null when absent). */
  summaryLine: string | null
  hasExecutiveSummary: boolean
}

export interface UseSubmissionReadinessParams {
  profile: AdmissionProfileResponse
  isEligible: boolean
  canSubmit: boolean
  canResubmit: boolean
  canApprove: boolean
  canReject: boolean
  canRequestRevision: boolean
  canPublishResult: boolean
  canEnroll: boolean
}

// ---------------------------------------------------------------------------
// Pure helpers (no React) — exported for unit testing.
// ---------------------------------------------------------------------------

function severityFromStep(
  stepStatus: Record<string, string> | null | undefined,
  step: number,
): "error" | "warning" {
  return stepStatus?.[String(step)] === "error" ? "error" : "warning"
}

function summarizeMany(messages: string[]): string {
  const first = messages[0] ?? ""
  const extra = messages.length > 1 ? ` (+${messages.length - 1} mục khác)` : ""
  return `${first}${extra}`
}

function itemFromGrouped(
  step: number,
  group: { category: string; errors: string[]; count: number },
  severity: "error" | "warning",
): ReadinessActionItem {
  const first = group.errors?.[0]
  const message = first
    ? summarizeMany(group.errors)
    : `${group.category}: ${group.count} mục cần xử lý`
  return { id: `step-${step}`, step, severity, message, source: "message" }
}

/** One element of `executive_summary.critical_blockers` / `warnings` (Phase 3). */
type ExecSummaryItem = NonNullable<
  AdmissionProfileResponse["executive_summary"]
>["critical_blockers"][number]

/**
 * Phase 3 — turn STRUCTURED executive_summary items (objects with a numeric
 * `.step`) into routed ActionItems. Legacy `string` items and objects without a
 * step are skipped here; the caller's heuristic then recovers their sections (so
 * a mixed/partial response never drops a blocker). Severity comes from the item
 * (`blocker`→error, `warning`→warning); falls back to the list's default.
 */
export function buildStructuredActionItems(
  es: AdmissionProfileResponse["executive_summary"],
): ReadinessActionItem[] {
  if (!es) return []
  const out: ReadinessActionItem[] = []
  const consume = (list: ExecSummaryItem[] | undefined, fallback: "error" | "warning") => {
    for (const it of list ?? []) {
      if (typeof it === "string" || typeof it.step !== "number") continue
      const severity: "error" | "warning" =
        it.severity === "blocker" ? "error" : it.severity === "warning" ? "warning" : fallback
      out.push({
        id: it.code || `step-${it.step}-${it.message}`,
        step: it.step,
        severity,
        message: it.message,
        source: "message",
      })
    }
  }
  consume(es.critical_blockers, "error")
  consume(es.warnings, "warning")
  return out
}

/**
 * Build the ActionItems list. Phase 3: route STRUCTURED executive_summary
 * blockers/warnings (objects with `.step`) precisely, THEN run the heuristic
 * (grouped_validation_errors → Step 1/5/6, step_status → Step 2/3) for any step
 * NOT already covered by a structured item. Running the heuristic unconditionally
 * (not only when structured is empty) means a mixed/partial response — some
 * legacy `string` items, or objects missing `.step` — still surfaces every
 * section instead of silently dropping the un-routable ones. Priority (Step 4) is
 * FE-derived and always added. Result is deduped + sorted. Works even when
 * executive_summary is null (R1 fallback). Step 7 (Học phí) is display-only: the
 * BE emits no item and the heuristic never adds one → never an ActionItem.
 */
export function buildReadinessActionItems(
  profile: AdmissionProfileResponse,
): ReadinessActionItem[] {
  const stepStatus = profile.step_status

  // Precise: structured BE items (objects with a numeric step).
  const structured = buildStructuredActionItems(profile.executive_summary)
  const coveredSteps = new Set<number>(structured.map((i) => i.step))
  const items: ReadinessActionItem[] = [...structured]

  // Heuristic recovery — fill ONLY the steps structured items did not cover.
  // grouped_validation_errors → Step 1/5/6.
  const grouped = profile.grouped_validation_errors
  const groupedBuckets: Array<
    [GroupedSectionKey, { category: string; errors: string[]; count: number } | undefined]
  > = [
    ["personal_info", grouped?.personal_info],
    ["scores", grouped?.scores],
    ["documents", grouped?.documents],
  ]
  for (const [key, bucket] of groupedBuckets) {
    if (!bucket || bucket.count <= 0) continue
    const step = GROUPED_SECTION_TO_STEP[key]
    if (coveredSteps.has(step)) continue // structured already routed this step
    items.push(itemFromGrouped(step, bucket, severityFromStep(stepStatus, step)))
  }
  // section-level: ONLY Step 2 (Gia đình) + Step 3 (Học tập).
  for (const step of [2, 3]) {
    if (coveredSteps.has(step)) continue
    const s = stepStatus?.[String(step)]
    if (s === "error" || s === "warning") {
      items.push({
        id: `step-${step}`,
        step,
        severity: s,
        message: `${getAdmissionStepLabel(step)} cần được bổ sung.`,
        source: "section",
      })
    }
  }

  // Priority (Step 4) is FE-derived (derivePriorityIssues) — NEVER in
  // executive_summary. Add once, unless a Step 4 item is already present.
  if (!items.some((i) => i.step === 4)) {
    const priorityIssues = derivePriorityIssues(profile)
    if (priorityIssues.length > 0) {
      items.push({
        id: "step-4",
        step: 4,
        severity: severityFromStep(stepStatus, 4),
        message: summarizeMany(priorityIssues),
        source: "message",
      })
    }
  }

  // Dedupe (by id = code, or `step-…` key) — no duplicate step/code/message rows.
  const seenIds = new Set<string>()
  const deduped = items.filter((it) => {
    if (seenIds.has(it.id)) return false
    seenIds.add(it.id)
    return true
  })

  // error before warning, then ascending step.
  return deduped.sort((a, b) => {
    if (a.severity !== b.severity) return a.severity === "error" ? -1 : 1
    return a.step - b.step
  })
}

function eligibilityLabelFor(verdict: EligibilityVerdict): string {
  switch (verdict) {
    case "eligible":
      return "Đủ điều kiện xét"
    case "ineligible":
      return "Chưa đủ điều kiện"
    default:
      return "Chưa xét điều kiện"
  }
}

function eligibilityToneFor(verdict: EligibilityVerdict): ReadinessTone {
  switch (verdict) {
    case "eligible":
      return "success"
    case "ineligible":
      return "error"
    default:
      return "neutral"
  }
}

function resolvePrimaryAction(p: UseSubmissionReadinessParams): PrimaryAction {
  // first-match wins (plan B5 precedence). approve beats reject/request_revision
  // in the review cluster — they remain visible in the panel regardless.
  if (p.canSubmit) return "submit"
  if (p.canResubmit) return "resubmit"
  if (p.canApprove) return "approve"
  if (p.canPublishResult) return "publish_result"
  if (p.canEnroll) return "enroll"
  if (p.canRequestRevision) return "request_revision"
  if (p.canReject) return "reject"
  return "none"
}

function resolveReadiness(
  primaryAction: PrimaryAction,
  params: UseSubmissionReadinessParams,
  actionItemCount: number,
  hasError: boolean,
): { label: string; tone: ReadinessTone } {
  const { profile, isEligible } = params
  const issueTone: ReadinessTone = hasError ? "error" : "warning"

  switch (primaryAction) {
    case "submit":
      if (isEligible) return { label: "Có thể nộp ngay", tone: "success" }
      // Fallback (plan chốt #3): never say "0 mục cần xử lý".
      if (actionItemCount > 0)
        return { label: `${actionItemCount} mục cần xử lý`, tone: issueTone }
      return { label: "Chưa đủ điều kiện nộp", tone: "warning" }

    case "resubmit":
      // resubmit does NOT depend on eligibility (plan B3 gate / invariant I2).
      if (actionItemCount > 0)
        return { label: `Nộp lại — ${actionItemCount} mục cần xử lý`, tone: issueTone }
      return { label: "Có thể nộp lại", tone: "success" }

    case "approve":
      // Mirror the ApprovalDecisionButton gate (disabled when
      // `!isEligible && !bypass_warning`): when approve is blocked the Hero must
      // NOT show a positive/info "ready to approve" signal.
      if (profile.bypass_warning)
        return { label: "Phê duyệt — hồ sơ chưa đủ điều kiện", tone: "warning" }
      if (!isEligible)
        return { label: "Chưa thể phê duyệt — chưa đủ điều kiện", tone: "warning" }
      return { label: "Chờ bạn phê duyệt", tone: "info" }

    case "publish_result":
      return { label: "Sẵn sàng công bố kết quả", tone: "info" }

    case "enroll":
      return { label: "Sẵn sàng ghi danh", tone: "info" }

    case "request_revision":
      return { label: "Có thể yêu cầu sửa", tone: "neutral" }

    case "reject":
      return { label: "Chờ xử lý phê duyệt", tone: "neutral" }

    case "none":
    default:
      // No action available → reflect read-only status, do NOT imply "nộp được".
      return { label: getStatusConfig(profile.status).label, tone: "neutral" }
  }
}

export function useSubmissionReadiness(
  params: UseSubmissionReadinessParams,
): SubmissionReadiness {
  const {
    profile,
    isEligible,
    canSubmit,
    canResubmit,
    canApprove,
    canReject,
    canRequestRevision,
    canPublishResult,
    canEnroll,
  } = params

  return useMemo<SubmissionReadiness>(() => {
    const verdict = (profile.eligibility_status ?? "pending") as EligibilityVerdict

    const actionItems = buildReadinessActionItems(profile)
    const hasError = actionItems.some((i) => i.severity === "error")

    const primaryAction = resolvePrimaryAction(params)
    const { label: readinessLabel, tone: readinessTone } = resolveReadiness(
      primaryAction,
      params,
      actionItems.length,
      hasError,
    )

    const es = profile.executive_summary
    // summaryLine hint — extract message from the first blocker (string or object).
    const firstBlocker = es?.critical_blockers?.[0]
    const firstBlockerMsg =
      firstBlocker == null
        ? null
        : typeof firstBlocker === "string"
          ? firstBlocker
          : firstBlocker.message
    const summaryLine = es ? es.next_action || firstBlockerMsg || null : null

    return {
      eligibilityVerdict: verdict,
      eligibilityLabel: eligibilityLabelFor(verdict),
      eligibilityTone: eligibilityToneFor(verdict),
      primaryAction,
      readinessLabel,
      readinessTone,
      actionItems,
      actionItemCount: actionItems.length,
      summaryLine,
      hasExecutiveSummary: !!es,
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- params object is reconstructed each render; depend on its stable members
  }, [
    profile,
    isEligible,
    canSubmit,
    canResubmit,
    canApprove,
    canReject,
    canRequestRevision,
    canPublishResult,
    canEnroll,
  ])
}
