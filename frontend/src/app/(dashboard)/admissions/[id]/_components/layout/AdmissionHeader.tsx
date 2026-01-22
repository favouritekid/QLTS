"use client"

import { Badge } from "@/components/ui/badge"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { getStatusConfig } from "@/lib/status-config"

interface AdmissionHeaderProps {
  profile: AdmissionProfileResponse | null
  validation: {
    isEligible: boolean
    missingItems: { code: string; label: string; status: "error" | "warning" }[]
  }
}

export function AdmissionHeader({ profile }: AdmissionHeaderProps) {
  // Get status configuration from centralized config
  const statusConfig = profile?.status ? getStatusConfig(profile.status, "admission") : null

  return (
    <div className="h-12 px-6 flex items-center gap-3">
      {/* Profile ID */}
      <h1 className="text-base font-semibold">
        Hồ sơ #{profile?.lead_id || "---"}
      </h1>

      <span className="text-muted-foreground">·</span>

      {/* Status Badge */}
      {statusConfig && (
        <Badge
          variant={statusConfig.badgeVariant}
          className="text-xs"
        >
          {statusConfig.label}
        </Badge>
      )}

      <span className="text-muted-foreground">·</span>

      {/* Officer Name */}
      <span className="text-sm text-muted-foreground">
        Phụ trách: {profile?.lead?.assigned_officer_id || "---"}
      </span>
    </div>
  )
}
