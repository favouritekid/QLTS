"use client"

import { ReactNode } from "react"
import { AdmissionHeader } from "./AdmissionHeader"
import { PipelineSidebar } from "./PipelineSidebar"
import { MobileStepStrip } from "./MobileStepStrip"
import { MobileIssueDrawer } from "./MobileIssueDrawer"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface AdmissionLayoutProps {
  children: ReactNode
  profile: AdmissionProfileResponse | null
  currentStep: number
  onStepChange: (step: number) => void
  /** Jump to the first blocking step (header CTA + Step-8 "Kiểm tra toàn bộ"). */
  onCheckCondition?: () => void
  stepsStatus: Record<number, "success" | "warning" | "error" | "locked">
  validationErrors?: string[]
  validationSummary?: {
    personal?: { has_error: boolean; count: number }
    gpa?: { has_error: boolean; count: number }
    documents?: { has_error: boolean; count: number }
  } | null
  // Derived from the zod contract (includes required_data) so buckets stay in sync.
  groupedValidationErrors?: NonNullable<AdmissionProfileResponse["grouped_validation_errors"]> | null
  // Commit 7 — pass-through cho ProfileActionMenu trong header.
  onClaim?: () => void
  onUnclaim?: () => void
  isClaiming?: boolean
  isUnclaiming?: boolean
  onDelete?: () => void
  isDeleting?: boolean
}

export function AdmissionLayout({
  children,
  profile,
  currentStep,
  onStepChange,
  onCheckCondition,
  stepsStatus,
  validationErrors = [],
  validationSummary,
  groupedValidationErrors,
  onClaim,
  onUnclaim,
  isClaiming = false,
  isUnclaiming = false,
  onDelete,
  isDeleting = false,
}: AdmissionLayoutProps) {
  return (
    <div className="flex flex-col min-h-screen bg-muted/50">
       <div className="sticky top-0 z-30 bg-background border-b shadow-sm">
          <AdmissionHeader
            profile={profile}
            onCheckCondition={onCheckCondition}
            onClaim={onClaim}
            onUnclaim={onUnclaim}
            isClaiming={isClaiming}
            isUnclaiming={isUnclaiming}
            onDelete={onDelete}
            isDeleting={isDeleting}
          />
          {/* Mobile-only step navigator — desktop uses the PipelineSidebar
              (hidden lg:block); on mobile this keeps step overview + direct
              jump reachable in the sticky header while content scrolls. */}
          <MobileStepStrip
            profile={profile}
            currentStep={currentStep}
            onStepChange={onStepChange}
            stepsStatus={stepsStatus}
          />
       </div>

       {/* Fill the app content area (already capped at --content-max-width by the
           shell) instead of the narrower max-w-7xl, and use a single px-4 — the
           app <main> already pads (p-6 on lg), so the old px-6 here double-padded. */}
       <div className="flex flex-1 px-4 pt-4 md:pt-6 gap-4 md:gap-8">
          <aside className="w-56 hidden lg:block flex-shrink-0 sticky top-24 h-fit">
             <PipelineSidebar
                profile={profile}
                currentStep={currentStep}
                onStepChange={onStepChange}
                stepsStatus={stepsStatus}
                validationErrors={validationErrors}
                validationSummary={validationSummary}
                groupedValidationErrors={groupedValidationErrors}
                completionPercent={profile?.completion_percent ?? 0}
             />
          </aside>

          {/* Mobile pb clears BOTH the bottom nav (--bottom-nav-height-safe)
              AND the sticky AdmissionActions bar (h-16) now stacked above it.
              Desktop keeps pb-20: nav hidden, action bar at bottom-0. */}
          <main className="flex-1 pb-[calc(var(--bottom-nav-height-safe)_+_4rem)] lg:pb-20">
             {children}
          </main>
       </div>

       <MobileIssueDrawer
          profile={profile}
          validationErrors={validationErrors}
          groupedValidationErrors={groupedValidationErrors}
       />
    </div>
  )
}
