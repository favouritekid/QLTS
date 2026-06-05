/**
 * InspectionDetails — collapsible detail surfaces below the readiness summary.
 *
 * Two independent collapsibles (both default CLOSED, Radix → trigger is a real
 * <button> with aria-expanded, plan P1-a):
 *   - "Cockpit duyệt" → HealthCheckGrid (8-card manager/admin review cockpit).
 *     GATED by `isReviewer` (Phase 2): only users holding a decision/action
 *     permission see it. Officers never see the cockpit.
 *   - "Chi tiết kiểm tra" → ReviewDetails (priority/UT/score/document self-check).
 *     Available to ALL roles.
 *
 * `isReviewer` is derived by FinalizeTab from BE permission flags
 * (approve/reject/request_revision/publish_result/enroll) — NOT user.role, NOT
 * override_priority_kv_mode (plan Phase 2).
 */

"use client"

import { useState, type ReactNode } from "react"
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
  /**
   * Reviewer-surface gate (Phase 2). True when the user holds any decision/
   * action permission. Officers (self-check only) do NOT see HealthCheckGrid.
   */
  isReviewer: boolean
}

function CollapsibleSection({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: ReactNode
}) {
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
          {title}
        </span>
        {hint && (
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {open ? "Ẩn" : hint}
          </span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-3 space-y-3">{children}</CollapsibleContent>
    </Collapsible>
  )
}

export function InspectionDetails({
  profile,
  onNavigateToDocuments,
  isReviewer,
}: InspectionDetailsProps) {
  return (
    <div className="space-y-3">
      {/* Manager/Admin reviewer cockpit — gated by decision/action permission
          (Phase 2). Officers never see this section. */}
      {isReviewer && (
        <CollapsibleSection title="Cockpit duyệt" hint="Lưới 8 thẻ review cho quản lý">
          <HealthCheckGrid profile={profile} />
        </CollapsibleSection>
      )}

      {/* Self-check detail — available to all roles. */}
      <CollapsibleSection title="Chi tiết kiểm tra" hint="Snapshot điểm / tài liệu / KV-UT">
        <ReviewDetails profile={profile} onNavigateToDocuments={onNavigateToDocuments} />
      </CollapsibleSection>
    </div>
  )
}
