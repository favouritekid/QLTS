/**
 * ReviewerCockpit — manager/admin decision cockpit (Step 8, reviewer-only).
 *
 * A SINGLE panel that answers "đủ duyệt chưa, vướng gì, vướng ở nhóm nào" in
 * 5-10 giây — NOT a Step 1-7 dashboard:
 *   - Header: "Cockpit duyệt" + readiness badge + one-line summary.
 *   - DecisionSummaryGrid: 4 tín hiệu (Điều kiện xét · Ưu tiên/KV · Điểm · Tài liệu).
 *   - Finance mini-row + latest audit one-line.
 * Per-step detail / evidence tables live in InspectionDetails (collapsed). Officers
 * never see this (FinalizeTab gates on isReviewer). Default OPEN; collapsible.
 *
 * Radix trigger is a real <button> with aria-expanded (a11y).
 */

"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, Gauge } from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Badge } from "@/components/ui/badge"
import { DecisionSummaryGrid } from "./DecisionSummaryGrid"
import { IssueLocator } from "./IssueLocator"
import { FeeReviewCard } from "../executive-summary/FeeReviewCard"
import { AuditReviewCard } from "../executive-summary/AuditReviewCard"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { ReadinessTone, SubmissionReadiness } from "./useSubmissionReadiness"

interface ReviewerCockpitProps {
  profile: AdmissionProfileResponse
  readiness: SubmissionReadiness
  /** Deep-link to a pipeline step from the "Cần yêu cầu sửa" locator chips. */
  onNavigateToStep: (step: number) => void
}

const TONE_VARIANT: Record<
  ReadinessTone,
  "success" | "warning" | "error" | "info" | "secondary"
> = {
  success: "success",
  warning: "warning",
  error: "error",
  info: "info",
  neutral: "secondary",
}

function cockpitSummary(r: SubmissionReadiness): string {
  if (r.eligibilityVerdict === "ineligible")
    return "Hồ sơ chưa đủ điều kiện — chưa thể phê duyệt."
  if (r.eligibilityVerdict === "pending")
    return "Hồ sơ chưa được xét điều kiện xét tuyển."
  if (r.hasOutstandingWarnings)
    return "Hồ sơ đủ điều kiện cơ bản, nhưng còn cảnh báo cần rà soát trước khi phê duyệt."
  return "Hồ sơ đủ điều kiện — có thể phê duyệt."
}

export function ReviewerCockpit({ profile, readiness, onNavigateToStep }: ReviewerCockpitProps) {
  const [open, setOpen] = useState(true) // default OPEN for reviewers

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-lg border bg-card" data-testid="reviewer-cockpit">
        <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 px-4 py-3 text-sm font-semibold transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <span className="flex min-w-0 items-center gap-2">
            <Gauge className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
            Bảng duyệt
          </span>
          <span className="flex shrink-0 items-center gap-2">
            <Badge
              variant={TONE_VARIANT[readiness.verdictTone]}
              className="max-w-[55vw] truncate sm:max-w-none"
            >
              {readiness.verdictLabel}
            </Badge>
            {open ? (
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            )}
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-3 border-t px-4 py-3">
          {/* Reuse the hook's decisionSummary (correctly orders bypass→ineligible,
              matching the verdict badge); fall back to a generic line only for
              null/clean states so the body never contradicts the badge. */}
          <p className="text-sm text-muted-foreground break-words">
            {readiness.decisionSummary ?? cockpitSummary(readiness)}
          </p>
          <DecisionSummaryGrid profile={profile} readiness={readiness} />
          <IssueLocator
            items={readiness.actionItems}
            hasOutstandingWarnings={readiness.hasOutstandingWarnings}
            onNavigateToStep={onNavigateToStep}
          />
          <div className="space-y-2 border-t pt-3">
            <FeeReviewCard profile={profile} />
            <AuditReviewCard profile={profile} />
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}
