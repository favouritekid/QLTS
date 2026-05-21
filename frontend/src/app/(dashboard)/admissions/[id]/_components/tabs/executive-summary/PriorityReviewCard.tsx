"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ShieldCheck, CheckCircle2, AlertTriangle, XCircle } from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface PriorityReviewCardProps {
  profile: AdmissionProfileResponse
}

/**
 * Cockpit card cho § KV/UT review. BE-driven: đọc snapshot fields
 * (kv_resolved, requires_manual_override, ut_verified_bucket,
 * manual_override_reason, path_bonus_rule, frozen_at).
 */
export function PriorityReviewCard({ profile }: PriorityReviewCardProps) {
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const kv = typeof snapshot.kv_resolved === "string" ? snapshot.kv_resolved : null
  const requiresManualOverride = snapshot.requires_manual_override === true
  const hasOverride = Boolean(snapshot.manual_override_reason)
  const missingUtCount = profile.missing_priority_evidence_codes?.length ?? 0

  const utBucket = (() => {
    const b = snapshot.ut_verified_bucket
    if (b && typeof b === "object" && "applied_code" in b) {
      const code = (b as { applied_code?: string | null }).applied_code
      const rate = (b as { applied_rate?: number | null }).applied_rate
      if (typeof code === "string" && typeof rate === "number") return { code, rate }
    }
    return null
  })()

  const areaBonus = (() => {
    const bd = snapshot.breakdown
    if (bd && typeof bd === "object" && "area_bonus" in bd) {
      const v = (bd as Record<string, unknown>).area_bonus
      return typeof v === "number" ? v : 0
    }
    return 0
  })()

  const maxTotalBonus = (() => {
    const r = snapshot.path_bonus_rule
    if (r && typeof r === "object" && "max_total_bonus" in r) {
      const v = (r as { max_total_bonus?: number | null }).max_total_bonus
      return typeof v === "number" ? v : null
    }
    return null
  })()

  const totalBonus = areaBonus + (utBucket?.rate ?? 0)
  const isCapped = typeof maxTotalBonus === "number" && totalBonus > maxTotalBonus
  const appliedBonus = isCapped ? (maxTotalBonus as number) : totalBonus

  // Status: error nếu requires_manual_override; warning nếu missing UT;
  // success nếu KV resolved.
  const StatusIcon = requiresManualOverride
    ? XCircle
    : missingUtCount > 0
      ? AlertTriangle
      : kv
        ? CheckCircle2
        : AlertTriangle
  const statusColor = requiresManualOverride
    ? "text-error-600"
    : missingUtCount > 0
      ? "text-warning-600"
      : kv
        ? "text-success-600"
        : "text-warning-600"

  return (
    <Card data-testid="priority-review-card">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-muted-foreground" />
            <CardTitle className="text-lg">KV & Ưu tiên</CardTitle>
          </div>
          <StatusIcon className={`w-6 h-6 ${statusColor}`} />
        </div>
      </CardHeader>

      <CardContent className="space-y-2 text-sm">
        <div className="flex justify-between items-baseline">
          <span className="text-muted-foreground">KV:</span>
          <span className="font-semibold">{kv ?? "—"}</span>
        </div>
        <div className="flex justify-between items-baseline">
          <span className="text-muted-foreground">UT đã duyệt:</span>
          <span className="font-semibold">
            {utBucket ? `UT${utBucket.code} (+${utBucket.rate.toFixed(2)}đ)` : "—"}
          </span>
        </div>
        <div className="flex justify-between items-baseline">
          <span className="text-muted-foreground">Tổng cộng:</span>
          <span className="font-semibold tabular-nums">+{appliedBonus.toFixed(2)}đ</span>
        </div>
        {isCapped && (
          <Badge variant="outline" className="bg-warning-50 border-warning-200 text-warning-700 text-xs">
            Bị cap (max +{(maxTotalBonus as number).toFixed(2)}đ)
          </Badge>
        )}
        {hasOverride && (
          <Badge variant="outline" className="bg-purple-50 border-purple-200 text-purple-700 text-xs">
            Cán bộ đã ấn định
          </Badge>
        )}
        {requiresManualOverride && (
          <Badge variant="outline" className="bg-error-50 border-error-200 text-error-700 text-xs">
            Cần ấn định thủ công
          </Badge>
        )}
        {missingUtCount > 0 && (
          <Badge variant="outline" className="bg-warning-50 border-warning-200 text-warning-700 text-xs">
            Thiếu {missingUtCount} minh chứng UT
          </Badge>
        )}
      </CardContent>
    </Card>
  )
}
