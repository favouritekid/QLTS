/**
 * ReviewDetails Component
 *
 * Section 3: Chi Tiết Xét Duyệt (Expandable)
 * Container for: ScoreSnapshot + DocumentChecklist
 */

"use client"

import { ScoreSnapshot } from "./ScoreSnapshot"
import { DocumentChecklist } from "./DocumentChecklist"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ReviewDetailsProps {
  profile: AdmissionProfileResponse
}

export function ReviewDetails({ profile }: ReviewDetailsProps) {
  return (
    <div className="space-y-3">
      {/* Score Snapshot */}
      <ScoreSnapshot profile={profile} />

      {/* Document Checklist */}
      <DocumentChecklist profile={profile} />
    </div>
  )
}
