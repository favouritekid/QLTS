"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Wallet } from "lucide-react"
import { FeeStatusLink } from "@/components/finance"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface FeeReviewCardProps {
  profile: AdmissionProfileResponse
}

/**
 * Cockpit card cho § học phí. Cross-module signal qua FeeStatusLink
 * (Finance module). Hiển thị compact để manager scan nhanh.
 */
export function FeeReviewCard({ profile }: FeeReviewCardProps) {
  return (
    <Card data-testid="fee-review-card">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Wallet className="w-5 h-5 text-muted-foreground" />
          <CardTitle className="text-lg">Học phí</CardTitle>
        </div>
      </CardHeader>

      <CardContent className="space-y-2 text-sm">
        <FeeStatusLink profileId={profile.id} variant="badge" />
        <p className="text-xs text-muted-foreground">
          Trạng thái học phí từ module tài chính (click để xem chi tiết).
        </p>
      </CardContent>
    </Card>
  )
}
