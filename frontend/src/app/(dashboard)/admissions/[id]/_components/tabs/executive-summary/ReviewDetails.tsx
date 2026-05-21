/**
 * ReviewDetails Component
 *
 * Section 3 (Step 8): Chi Tiết Xét Duyệt
 * Commit 4 — gom Priority/UT (read-only) vào Step 8 để manager/admin
 * không phải nhảy sang Tab Trình độ & Ưu tiên để verify KV/UT trước
 * khi duyệt.
 */

"use client"

import { ScoreSnapshot } from "./ScoreSnapshot"
import { DocumentChecklist } from "./DocumentChecklist"
import { PrioritySummaryPanel } from "../../priority/PrioritySummaryPanel"
import { UtEvidenceCards } from "../../priority/UtEvidenceCards"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ReviewDetailsProps {
  profile: AdmissionProfileResponse
}

export function ReviewDetails({ profile }: ReviewDetailsProps) {
  return (
    <div className="space-y-3">
      {/* Priority KV summary (read-only at Step 8). */}
      <PrioritySummaryPanel profile={profile} preview={null} />

      {/* UT evidence read-only — canVerify=false + isEditable=false ép
          component render display-only. onNavigateToDocuments no-op vì
          ở Step 8 manager đã có DocumentChecklist bên dưới. */}
      <UtEvidenceCards
        profile={profile}
        canVerify={false}
        isEditable={false}
        onNavigateToDocuments={() => {}}
      />

      <ScoreSnapshot profile={profile} />

      <DocumentChecklist profile={profile} />
    </div>
  )
}
