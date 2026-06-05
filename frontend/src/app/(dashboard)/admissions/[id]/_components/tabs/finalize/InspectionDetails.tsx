/**
 * InspectionDetails — "CHI TIẾT KIỂM TRA" (collapsible, default CLOSED).
 *
 * Wraps the heavy review surfaces (HealthCheckGrid cockpit + ReviewDetails:
 * PrioritySummaryPanel / UtEvidenceCards / ScoreSnapshot / DocumentChecklist),
 * reused as-is, behind a Radix Collapsible so the primary readiness path stays
 * short. The Radix trigger is a real <button> with `aria-expanded` (plan P1-a).
 *
 * Phase 1 keeps both surfaces for every role; Phase 2 will gate HealthCheckGrid
 * by reviewer permission (out of scope here).
 */

"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { HealthCheckGrid } from "../executive-summary/HealthCheckGrid"
import { ReviewDetails } from "../executive-summary/ReviewDetails"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface InspectionDetailsProps {
  profile: AdmissionProfileResponse
  onNavigateToDocuments: () => void
}

export function InspectionDetails({ profile, onNavigateToDocuments }: InspectionDetailsProps) {
  const [open, setOpen] = useState(false)

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
          {open ? "Ẩn" : "Lưới cockpit + snapshot điểm / tài liệu / KV"}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-3 space-y-3">
        <HealthCheckGrid profile={profile} />
        <ReviewDetails profile={profile} onNavigateToDocuments={onNavigateToDocuments} />
      </CollapsibleContent>
    </Collapsible>
  )
}
