/**
 * InspectionDetails — "Chi tiết kiểm tra" (collapsible, default CLOSED, all roles).
 *
 * Wraps the read-only self-check detail surfaces (ReviewDetails: PrioritySummaryPanel
 * / UtEvidenceCards / ScoreSnapshot / DocumentChecklist) behind a single collapsible
 * that is CLOSED by default for every role — so neither officer nor reviewer faces a
 * "wall of information" up front. The manager review cockpit lives in its own
 * `ReviewerCockpit` (DecisionSummaryGrid + IssueLocator; reviewer-only, default
 * open), NOT here.
 *
 * Radix trigger is a real <button> with aria-expanded (a11y, plan P1-a).
 */

"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ReviewDetails } from "../executive-summary/ReviewDetails"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface InspectionDetailsProps {
  profile: AdmissionProfileResponse
  onNavigateToDocuments: () => void
}

export function InspectionDetails({ profile, onNavigateToDocuments }: InspectionDetailsProps) {
  const [open, setOpen] = useState(false) // default CLOSED for all roles

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 rounded-lg border bg-muted/40 px-4 py-3 text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="flex items-center gap-2">
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" />
          )}
          Chi tiết kiểm tra
        </span>
        <span className="hidden text-xs text-muted-foreground sm:inline">
          {open ? "Ẩn" : "Snapshot điểm / tài liệu / KV-UT"}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-3">
        <ReviewDetails profile={profile} onNavigateToDocuments={onNavigateToDocuments} />
      </CollapsibleContent>
    </Collapsible>
  )
}
