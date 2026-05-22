/**
 * HealthCheckGrid Component — Manager/Admin Review Cockpit (Commit 4)
 *
 * 8 compact cards trên grid 4-col (lg) / 2-col (md) / 1-col (mobile) cho
 * manager scan nhanh state hồ sơ trước khi quyết định. Không gọi API mới
 * — đọc từ profile snapshot + checklist BE-canonical.
 *
 * Legacy 3 cards (Legal/Academic/Admin) đọc step_status[1-6] theo
 * mapping cũ pre-Phase-E.4 — drift đã ghi nhận, defer audit riêng.
 * Commit 4 chỉ thêm 5 card mới (Priority, Score, Document, Fee, Audit)
 * đọc trực tiếp BE fields đã verify trong Commit 3.
 */

"use client"

import { LegalDocsCard } from "./LegalDocsCard"
import { AcademicCard } from "./AcademicCard"
import { AdminCard } from "./AdminCard"
import { PriorityReviewCard } from "./PriorityReviewCard"
import { ScoreReviewCard } from "./ScoreReviewCard"
import { DocumentReviewCard } from "./DocumentReviewCard"
import { FeeReviewCard } from "./FeeReviewCard"
import { AuditReviewCard } from "./AuditReviewCard"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface HealthCheckGridProps {
  profile: AdmissionProfileResponse
}

export function HealthCheckGrid({ profile }: HealthCheckGridProps) {
  return (
    <div
      className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3"
      data-testid="health-check-grid"
    >
      <LegalDocsCard profile={profile} />
      <AcademicCard profile={profile} />
      <PriorityReviewCard profile={profile} />
      <ScoreReviewCard profile={profile} />
      <DocumentReviewCard profile={profile} />
      <FeeReviewCard profile={profile} />
      <AdminCard profile={profile} />
      <AuditReviewCard profile={profile} />
    </div>
  )
}
