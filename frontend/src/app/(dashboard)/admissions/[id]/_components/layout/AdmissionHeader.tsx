"use client"

import { Badge } from "@/components/ui/badge"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { getStatusConfig } from "@/lib/status-config"
import { FeeStatusLink } from "@/components/finance"

interface AdmissionHeaderProps {
  profile: AdmissionProfileResponse | null
}

export function AdmissionHeader({ profile }: AdmissionHeaderProps) {
  // Get status configuration from centralized config
  const statusConfig = profile?.status ? getStatusConfig(profile.status, "admission") : null

  return (
    <div className="min-h-12 px-4 md:px-6 py-2 md:py-0 flex flex-wrap items-center gap-2 md:gap-3">
      {/* E2E #9 fix 2026-05-15 — heading shows profile.id (consistent with
          URL `/admissions/{id}`) + candidate full_name for UX. Prior shape
          `Hồ sơ #{lead_id}` confused officer because URL ID ≠ shown ID.
          full_name fallback chain: profile.full_name (Step 1 nhập) → null
          fallback "Chưa có tên" (officer chưa enter Step 1). */}
      <h1 className="text-sm md:text-base font-semibold font-display">
        Hồ sơ #{profile?.id ?? "---"}
        {profile?.full_name ? ` — ${profile.full_name}` : " — Chưa có tên"}
      </h1>

      <span className="text-muted-foreground hidden sm:inline">·</span>

      {/* Status Badge */}
      {statusConfig && (
        <Badge
          variant={statusConfig.badgeVariant}
          className="text-xs"
        >
          {statusConfig.label}
        </Badge>
      )}

      <span className="text-muted-foreground hidden md:inline">·</span>

      {/* Fee Status Badge - Cross-reference to Finance module */}
      {profile?.id && (
        <FeeStatusLink profileId={profile.id} variant="badge" />
      )}

      <span className="text-muted-foreground hidden md:inline">·</span>

      {/* Officer Name */}
      <span className="text-xs md:text-sm text-muted-foreground hidden md:inline">
        Phụ trách: {profile?.assigned_officer_name ?? "Chưa phân công"}
      </span>

      {profile?.assigned_reviewer_name && (
        <>
          <span className="text-muted-foreground hidden md:inline">·</span>
          <span className="text-xs md:text-sm text-muted-foreground hidden md:inline">
            Người duyệt: {profile.assigned_reviewer_name}
          </span>
        </>
      )}
    </div>
  )
}
