/**
 * FeeReviewCard — compact "Học phí" cockpit mini-row.
 *
 * Cross-module signal via FeeStatusLink (Finance module). When finance data is
 * unavailable (error / not loaded) FeeStatusLink would render nothing; we pass an
 * explicit `unavailableFallback` so the row shows "Chưa có dữ liệu tài chính"
 * instead of silently disappearing.
 */

"use client"

import { Wallet } from "lucide-react"
import { FeeStatusLink } from "@/components/finance"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface FeeReviewCardProps {
  profile: AdmissionProfileResponse
}

export function FeeReviewCard({ profile }: FeeReviewCardProps) {
  return (
    <div
      data-testid="fee-review-card"
      className="flex items-center justify-between gap-2 rounded-lg border bg-card px-3 py-2"
    >
      <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <Wallet className="h-4 w-4 shrink-0" aria-hidden="true" />
        Học phí
      </span>
      <FeeStatusLink
        profileId={profile.id}
        variant="badge"
        unavailableFallback={
          <span className="text-xs text-muted-foreground">Chưa có dữ liệu tài chính</span>
        }
      />
    </div>
  )
}
