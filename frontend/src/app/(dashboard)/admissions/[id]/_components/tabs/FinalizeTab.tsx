/**
 * FinalizeTab — Step 8 submission-readiness surface (Phase 1).
 *
 * Layout: ReadinessHero (identity + 2 verdict signals + 3 metrics + CTA slot)
 *   → ActionItemsList ("Việc cần xử lý") → SectionReview ("Rà soát câu trả lời")
 *   → InspectionDetails (collapsible cockpit/details, default closed).
 *
 * The decision button cluster lives in ONE place only: the Hero `cta` slot via
 * `DecisionActionsPanel` (plan D2). Utility actions ("Kiểm tra toàn bộ" / "Gửi
 * link nộp") stay on the sticky AdmissionActions bar (plan D1/D3) — NOT here.
 *
 * Thin Client: all signals are read from the backend response + mapped by
 * `useSubmissionReadiness`. No eligibility/score/workflow recomputation.
 */

"use client"

import { useSubmissionReadiness } from "./finalize/useSubmissionReadiness"
import { ReadinessHero } from "./finalize/ReadinessHero"
import { ActionItemsList } from "./finalize/ActionItemsList"
import { SectionReview } from "./finalize/SectionReview"
import { ReviewerCockpit } from "./finalize/ReviewerCockpit"
import { InspectionDetails } from "./finalize/InspectionDetails"
import { DecisionActionsPanel } from "./finalize/DecisionActionsPanel"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface FinalizeTabProps {
  profile: AdmissionProfileResponse
  isEligible: boolean

  // Submit (officer/applicant — state draft)
  onSubmit: () => void
  isSubmitting: boolean
  canSubmit: boolean

  // Resubmit (officer — state rejected/revision_requested)
  onResubmit?: () => void
  isResubmitting?: boolean
  canResubmit: boolean

  // Approve (manager/admin — state submitted/resubmitted/reviewing)
  onApprove?: () => void
  isApproving?: boolean
  canApprove: boolean

  // Reject (manager/admin — state submitted/resubmitted/reviewing)
  onReject?: () => void
  isRejecting?: boolean
  canReject: boolean

  // Request revision (manager — yêu cầu officer sửa)
  onRequestRevision?: () => void
  isRequestingRevision?: boolean
  canRequestRevision: boolean

  // Publish result (manager/admin multi-NV — engine cascade)
  onPublishResult?: () => void
  isPublishingResult?: boolean
  canPublishResult: boolean

  // Enroll (manager — state confirmed/overridden post-approval)
  onEnroll?: () => void
  isEnrolling?: boolean
  canEnroll: boolean

  // ReviewDetails → UtEvidenceCards "Mở tab Giấy tờ để upload" CTA.
  onNavigateToDocuments: () => void

  // Deep-link to a pipeline step from ActionItems/SectionReview.
  // Routes through AdmissionDetailClient.handleStepChange (unsaved-changes guard).
  onNavigateToStep: (step: number) => void
}

export function FinalizeTab({
  profile,
  isEligible,
  onSubmit,
  isSubmitting,
  canSubmit,
  onResubmit,
  isResubmitting = false,
  canResubmit,
  onApprove,
  isApproving = false,
  canApprove,
  onReject,
  isRejecting = false,
  canReject,
  onRequestRevision,
  isRequestingRevision = false,
  canRequestRevision,
  onPublishResult,
  isPublishingResult = false,
  canPublishResult,
  onEnroll,
  isEnrolling = false,
  canEnroll,
  onNavigateToDocuments,
  onNavigateToStep,
}: FinalizeTabProps) {
  const readiness = useSubmissionReadiness({
    profile,
    isEligible,
    canSubmit,
    canResubmit,
    canApprove,
    canReject,
    canRequestRevision,
    canPublishResult,
    canEnroll,
  })

  const hasDecisionAction =
    canSubmit ||
    canResubmit ||
    canApprove ||
    canReject ||
    canRequestRevision ||
    canPublishResult ||
    canEnroll

  // Phase 2 — reviewer surface gate. Manager/Admin reviewer = holds any
  // decision/action permission (NOT submit/resubmit, which are officer/applicant
  // actions). Drives ReviewerCockpit visibility (decision-signal cockpit).
  // Permission flags only — NOT user.role, NOT override_priority_kv_mode (plan Phase 2).
  const isReviewer =
    canApprove || canReject || canRequestRevision || canPublishResult || canEnroll

  // Single action SURFACE — rendered ONLY inside the Hero CTA slot (plan D2).
  const decisionPanel = hasDecisionAction ? (
    <DecisionActionsPanel
      profile={profile}
      isEligible={isEligible}
      primaryAction={readiness.primaryAction}
      onSubmit={onSubmit}
      isSubmitting={isSubmitting}
      canSubmit={canSubmit}
      onResubmit={onResubmit}
      isResubmitting={isResubmitting}
      canResubmit={canResubmit}
      onApprove={onApprove}
      isApproving={isApproving}
      canApprove={canApprove}
      onReject={onReject}
      isRejecting={isRejecting}
      canReject={canReject}
      onRequestRevision={onRequestRevision}
      isRequestingRevision={isRequestingRevision}
      canRequestRevision={canRequestRevision}
      onPublishResult={onPublishResult}
      isPublishingResult={isPublishingResult}
      canPublishResult={canPublishResult}
      onEnroll={onEnroll}
      isEnrolling={isEnrolling}
      canEnroll={canEnroll}
    />
  ) : null

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-8">
      <ReadinessHero profile={profile} readiness={readiness} cta={decisionPanel} />

      {/* Officer / data-entry workflow surface: what to fix + per-step review.
          Reviewers don't get this main-surface clutter (issue count still shows
          in the sidebar/status summary). */}
      {!isReviewer && (
        <>
          <ActionItemsList items={readiness.actionItems} onNavigateToStep={onNavigateToStep} />
          <SectionReview profile={profile} onNavigateToStep={onNavigateToStep} />
        </>
      )}

      {/* Manager/Admin review cockpit — reviewer only, default open. */}
      {isReviewer && (
        <ReviewerCockpit profile={profile} readiness={readiness} onNavigateToStep={onNavigateToStep} />
      )}

      {/* Self-check detail — collapsed by default for all roles. */}
      <InspectionDetails profile={profile} onNavigateToDocuments={onNavigateToDocuments} />
    </div>
  )
}
