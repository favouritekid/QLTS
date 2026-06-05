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
 * ActionItems source (plan B2 — NOT flat `critical_blockers`):
 *   - message-level: `grouped_validation_errors` (personal_info→1, scores→5,
 *     documents→6) + `derivePriorityIssues`→4.
 *   - section-level: `step_status[2|3]` ∈ {error,warning} only.
 *   - Step 7 (Học phí) is display-only (`step_status[7]` hard-coded "success")
 *     → NEVER produces an ActionItem (plan B4).
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

/**
 * Build the ActionItems list from backend fields. Independent of
 * `executive_summary` (works even when it is null — plan R1 fallback).
 */
export function buildReadinessActionItems(
  profile: AdmissionProfileResponse,
): ReadinessActionItem[] {
  const stepStatus = profile.step_status
  const items: ReadinessActionItem[] = []
  const seen = new Set<number>()

  const grouped = profile.grouped_validation_errors

  // message-level: grouped_validation_errors → Step 1/5/6 (single source: the
  // section→step map). Each bucket maps to one short summary row.
  const groupedBuckets: Array<
    [GroupedSectionKey, { category: string; errors: string[]; count: number } | undefined]
  > = [
    ["personal_info", grouped?.personal_info],
    ["scores", grouped?.scores],
    ["documents", grouped?.documents],
  ]
  for (const [key, bucket] of groupedBuckets) {
    if (bucket && bucket.count > 0) {
      const step = GROUPED_SECTION_TO_STEP[key]
      items.push(itemFromGrouped(step, bucket, severityFromStep(stepStatus, step)))
      seen.add(step)
    }
  }

  // message-level: priority → Step 4 (derived, BE-flag driven)
  const priorityIssues = derivePriorityIssues(profile)
  if (priorityIssues.length > 0) {
    items.push({
      id: "step-4",
      step: 4,
      severity: severityFromStep(stepStatus, 4),
      message: summarizeMany(priorityIssues),
      source: "message",
    })
    seen.add(4)
  }

  // section-level: ONLY Step 2 (Gia đình) + Step 3 (Học tập) — no grouped detail.
  // (Step 7 excluded by design — plan B4. Steps 1/4/5/6 handled above.)
  for (const step of [2, 3]) {
    if (seen.has(step)) continue // defensive dedupe — message-level wins
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

  // error before warning, then ascending step.
  return items.sort((a, b) => {
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
      if (profile.bypass_warning)
        return { label: "Phê duyệt — hồ sơ chưa đủ điều kiện", tone: "warning" }
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
    const summaryLine = es ? es.next_action || es.critical_blockers[0] || null : null

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
