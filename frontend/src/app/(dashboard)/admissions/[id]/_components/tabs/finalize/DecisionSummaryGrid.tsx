/**
 * DecisionSummaryGrid — the 4 decision signals of the reviewer cockpit.
 *
 * Điều kiện xét · Ưu tiên/KV · Điểm xét tuyển · Tài liệu. Each is a compact
 * SignalCell (NOT a full card) so the reviewer reads "đủ duyệt chưa, vướng ở
 * nhóm nào" at a glance. The eligibility cell is derived from the shared
 * `useSubmissionReadiness` result (readiness lives in the finalize tab, so the
 * executive-summary cards stay profile-only — no tab→tab coupling).
 */

"use client"

import { SignalCell, type SignalTone } from "../executive-summary/SignalCell"
import { PriorityReviewCard } from "../executive-summary/PriorityReviewCard"
import { ScoreReviewCard } from "../executive-summary/ScoreReviewCard"
import { DocumentReviewCard } from "../executive-summary/DocumentReviewCard"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { SubmissionReadiness } from "./useSubmissionReadiness"

interface DecisionSummaryGridProps {
  profile: AdmissionProfileResponse
  readiness: SubmissionReadiness
}

function eligibilityCell(readiness: SubmissionReadiness): { tone: SignalTone; secondary: string } {
  switch (readiness.eligibilityVerdict) {
    case "ineligible":
      return { tone: "error", secondary: "Chưa thể phê duyệt — chưa đủ điều kiện" }
    case "pending":
      return { tone: "neutral", secondary: "Chưa xét điều kiện" }
    default:
      return readiness.hasOutstandingWarnings
        ? { tone: "warning", secondary: "Còn cảnh báo cần rà soát" }
        : { tone: "success", secondary: "Có thể phê duyệt" }
  }
}

export function DecisionSummaryGrid({ profile, readiness }: DecisionSummaryGridProps) {
  const elig = eligibilityCell(readiness)

  return (
    <div
      data-testid="decision-summary-grid"
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
    >
      <SignalCell
        testId="eligibility-signal"
        title="Điều kiện xét"
        tone={elig.tone}
        primary={readiness.eligibilityLabel}
        secondary={elig.secondary}
      />
      <PriorityReviewCard profile={profile} />
      <ScoreReviewCard profile={profile} />
      <DocumentReviewCard profile={profile} />
    </div>
  )
}
