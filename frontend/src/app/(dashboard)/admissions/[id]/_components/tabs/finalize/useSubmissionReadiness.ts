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
 *   2. primaryAction + verdictLabel/Tone — tracks the ACTUAL primary action
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
  /** Number of underlying issues at this step (≥1) — for the reviewer locator chip. */
  count?: number
  /** True only when the backend currently allows the missing-doc debt flow. */
  canDeferAsDocumentDebt?: boolean
}

export interface SubmissionReadiness {
  eligibilityVerdict: EligibilityVerdict
  eligibilityLabel: string
  eligibilityTone: ReadinessTone
  primaryAction: PrimaryAction
  /** Single SHORT Hero verdict badge ("Có thể nộp"/"Chưa thể phê duyệt"/…). The
   *  one decisive signal — eligibility is folded in, NOT a separate badge. */
  verdictLabel: string
  verdictTone: ReadinessTone
  /** One-line decision summary under the badge; null when the badge says it all
   *  (never a pure restatement of the badge — plan Hero rule #3). */
  decisionSummary: string | null
  actionItems: ReadinessActionItem[]
  /** N = number of action items (≈ sections needing work, NOT total errors). */
  actionItemCount: number
  /** Label for the 3rd Hero metric: "Mục cần xử lý" (submit/resubmit) | "Cảnh báo". */
  outstandingLabel: string
  /** Optional "next action" hint from executive_summary (null when absent). */
  summaryLine: string | null
  hasExecutiveSummary: boolean
  /** Tone for the "Tài liệu bắt buộc" metric (warning when submitted < mandatory). */
  documentTone: ReadinessTone
  /** True when docs incomplete OR there are warnings/action items still open. */
  hasOutstandingWarnings: boolean
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
  return { id: `step-${step}`, step, severity, message, source: "message", count: Math.max(1, group.count) }
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
        count: 1,
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
  const grouped = profile.grouped_validation_errors
  const structured = buildStructuredActionItems(profile.executive_summary).map((item) => {
    if (item.id !== "personal_info_missing" || !grouped?.personal_info?.count) {
      return item
    }
    return {
      ...item,
      message: summarizeMany(grouped.personal_info.errors),
      count: Math.max(1, grouped.personal_info.count),
    }
  })
  const coveredSteps = new Set<number>(structured.map((i) => i.step))
  const items: ReadinessActionItem[] = [...structured]

  // Heuristic recovery — fill ONLY the steps structured items did not cover.
  // grouped_validation_errors → Step 1/5/6.
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
        count: 1,
      })
    }
  }

  // Priority (Step 4) is FE-derived (derivePriorityIssues) — NEVER in
  // executive_summary. The BE MAY also emit a structured Step-4 warning with a
  // DIFFERENT id (e.g. thcs_diploma_review): that must NOT suppress the
  // FE-derived priority issues (missing UT / manual-override / unresolved KV) —
  // they are distinct concerns and dedupe is by id (below). Guard only against
  // re-adding the SAME FE-derived "step-4" item, not against ANY Step-4 item.
  if (!items.some((i) => i.id === "step-4")) {
    const priorityIssues = derivePriorityIssues(profile)
    if (priorityIssues.length > 0) {
      items.push({
        id: "step-4",
        step: 4,
        severity: severityFromStep(stepStatus, 4),
        message: summarizeMany(priorityIssues),
        source: "message",
        count: priorityIssues.length,
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
  return deduped
    .map((item) => ({
      ...item,
      canDeferAsDocumentDebt: Boolean(
        profile.can_submit_with_document_debt && item.step === 6,
      ),
    }))
    .sort((a, b) => {
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

/**
 * Generic cockpit summary line — used by ReviewerCockpit ONLY as the fallback when
 * `readiness.decisionSummary` is null (clean/terminal states). Co-located with the
 * verdict wording so the cockpit body never drifts from the badge. The verdict's
 * own `decisionSummary` (when present) always wins, so this never contradicts it.
 */
export function cockpitFallbackSummary(r: SubmissionReadiness): string {
  if (r.eligibilityVerdict === "ineligible")
    return "Hồ sơ chưa đủ điều kiện — chưa thể phê duyệt."
  if (r.eligibilityVerdict === "pending")
    return "Hồ sơ chưa được xét điều kiện xét tuyển."
  if (r.hasOutstandingWarnings)
    return "Hồ sơ đủ điều kiện cơ bản, nhưng còn cảnh báo cần rà soát trước khi phê duyệt."
  return "Hồ sơ đủ điều kiện — có thể phê duyệt."
}

function resolvePrimaryAction(p: UseSubmissionReadinessParams): PrimaryAction {
  // first-match wins. publish_result / enroll OUTRANK approve: a multi-NV submitted
  // profile grants BOTH canApprove AND canPublishResult to a manager/admin
  // (admission_service.py:1673 approve on submitted/resubmitted; :1681 publish on
  // uses_choice_engine + submitted/reviewing). The simplified multi-NV flow makes
  // "Công bố kết quả" (engine cascade) the primary action, so it must win —
  // otherwise the panel's publish-only branch never fires and the publish CTA is
  // unreachable while the Hero mislabels the verdict as "Chờ phê duyệt".
  if (p.canSubmit) return "submit"
  if (p.canResubmit) return "resubmit"
  if (p.canPublishResult) return "publish_result"
  if (p.canEnroll) return "enroll"
  if (p.canApprove) return "approve"
  if (p.canRequestRevision) return "request_revision"
  if (p.canReject) return "reject"
  return "none"
}

/**
 * Map the current primary action + workflow state to ONE short Hero verdict
 * (badge label + tone) and an optional one-line `summary`. The badge is the single
 * decisive signal; the summary ADDS detail (count / why) and is null when the
 * badge already says everything (plan Hero rule #2/#3). Eligibility is folded in —
 * there is no separate eligibility badge.
 */
function resolveVerdict(
  primaryAction: PrimaryAction,
  params: UseSubmissionReadinessParams,
  actionItemCount: number,
  hasError: boolean,
  hasOutstandingWarnings: boolean,
): { label: string; tone: ReadinessTone; summary: string | null } {
  const { profile, isEligible } = params
  const issueTone: ReadinessTone = hasError ? "error" : "warning"

  switch (primaryAction) {
    case "submit":
      if (!isEligible)
        return {
          label: "Chưa thể nộp",
          tone: "warning",
          summary:
            actionItemCount > 0
              ? `Còn ${actionItemCount} mục cần xử lý trước khi nộp.`
              : "Chưa đủ điều kiện để nộp.",
        }
      if (hasOutstandingWarnings)
        return {
          label: "Còn cảnh báo",
          tone: "warning",
          summary: "Còn tài liệu/cảnh báo cần kiểm tra trước khi nộp.",
        }
      return { label: "Có thể nộp", tone: "success", summary: null }

    case "resubmit":
      // resubmit does NOT depend on eligibility (plan B3 gate / invariant I2).
      if (actionItemCount > 0)
        return {
          label: "Cần xử lý",
          tone: issueTone,
          summary: `Còn ${actionItemCount} mục cần xử lý trước khi nộp lại.`,
        }
      return { label: "Có thể nộp lại", tone: "success", summary: null }

    case "approve":
      if (profile.bypass_warning)
        return {
          label: "Phê duyệt vượt điều kiện",
          tone: "warning",
          summary: "Đợt cho phép nộp hồ sơ chưa đầy đủ — phê duyệt sẽ ghi dữ liệu thiếu.",
        }
      if (!isEligible)
        return {
          label: "Chưa thể phê duyệt",
          tone: "warning",
          summary: "Chưa đủ điều kiện — kiểm tra chi tiết từng nhóm bên dưới.",
        }
      if (hasOutstandingWarnings)
        return {
          label: "Còn cảnh báo rà soát",
          tone: "warning",
          summary:
            "Hồ sơ đủ điều kiện cơ bản, còn tài liệu/cảnh báo cần kiểm tra trước khi phê duyệt.",
        }
      return { label: "Chờ phê duyệt", tone: "info", summary: null }

    case "publish_result":
      return {
        label: "Sẵn sàng công bố",
        tone: "info",
        summary: "Chạy engine xét tuần tự các nguyện vọng theo thứ tự ưu tiên.",
      }

    case "enroll":
      return { label: "Sẵn sàng ghi danh", tone: "info", summary: null }

    case "request_revision":
      return { label: "Có thể yêu cầu sửa", tone: "neutral", summary: null }

    case "reject":
      return { label: "Chờ xử lý", tone: "neutral", summary: null }

    case "none":
    default:
      // No action available → reflect read-only status, do NOT imply "nộp được".
      return { label: getStatusConfig(profile.status).label, tone: "neutral", summary: null }
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

    const es = profile.executive_summary

    // Data-consistency: the Hero doc signal must not contradict the cockpit doc
    // cell. The Hero metric has only ONE "needs attention" tier (warning), so it
    // treats ANY incompleteness the cockpit flags as a warning — not-yet-submitted
    // (submitted < mandatory OR missing_count > 0) OR submitted-but-unverified
    // (unverified_count > 0, fallback submitted − verified). (The cockpit
    // DocumentReviewCard further splits missing→error vs unverified→warning; the
    // Hero collapses both to warning, so it never shows green while the cockpit
    // shows red/amber for the same profile.)
    const docStats = profile.document_stats
    const docUnverified =
      docStats?.unverified_count ??
      (docStats ? Math.max(0, docStats.submitted_count - docStats.verified_count) : 0)
    const docsIncomplete =
      !!docStats &&
      typeof docStats.mandatory_count === "number" &&
      docStats.mandatory_count > 0 &&
      (docStats.submitted_count < docStats.mandatory_count ||
        (docStats.missing_count ?? 0) > 0 ||
        docUnverified > 0)
    // The cockpit DocumentReviewCard folds missing UT priority evidence into its
    // "Tài liệu" tone (→ warning); mirror that here so the Hero "Tài liệu" metric
    // never shows green while the cockpit cell shows amber for the same profile.
    const missingUtCount = profile.missing_priority_evidence_codes?.length ?? 0
    const documentTone: ReadinessTone =
      docsIncomplete || missingUtCount > 0
        ? "warning"
        : docStats
          ? "success"
          : "neutral"
    const hasOutstandingWarnings =
      docsIncomplete || (es?.warnings?.length ?? 0) > 0 || actionItems.length > 0

    const primaryAction = resolvePrimaryAction(params)
    const {
      label: verdictLabel,
      tone: verdictTone,
      summary: verdictSummary,
    } = resolveVerdict(primaryAction, params, actionItems.length, hasError, hasOutstandingWarnings)

    // summaryLine hint — extract message from the first blocker (string or object).
    const firstBlocker = es?.critical_blockers?.[0]
    const firstBlockerMsg =
      firstBlocker == null
        ? null
        : typeof firstBlocker === "string"
          ? firstBlocker
          : firstBlocker.message
    const summaryLine = es ? es.next_action || firstBlockerMsg || null : null

    // One-line decision summary: the verdict's own summary takes priority; the BE
    // `next_action` hint (summaryLine) surfaces here whenever the verdict has NO
    // summary of its own — i.e. the info/neutral verdicts (approve-clean, enroll,
    // request_revision, reject, none) AND the clean submit/resubmit cases. For the
    // "has problems" verdicts that DO carry a summary (submit/approve when blocked or
    // with warnings), that count/why line is shown and the granular next_action lives
    // in ActionItemsList / cockpit below. Never a pure restatement of the badge (rule #3).
    const decisionSummary = verdictSummary ?? summaryLine

    // 3rd Hero metric label — one honest label for both roles. The value is
    // `actionItemCount` (sections needing work); labelling it "Cảnh báo" for
    // reviewers mislabels error-severity items and can read 0 under a warning
    // badge. Warning/severity nuance lives in the verdict badge, not this count.
    const outstandingLabel = "Mục cần xử lý"

    return {
      eligibilityVerdict: verdict,
      eligibilityLabel: eligibilityLabelFor(verdict),
      eligibilityTone: eligibilityToneFor(verdict),
      primaryAction,
      verdictLabel,
      verdictTone,
      decisionSummary,
      actionItems,
      actionItemCount: actionItems.length,
      outstandingLabel,
      summaryLine,
      hasExecutiveSummary: !!es,
      documentTone,
      hasOutstandingWarnings,
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
