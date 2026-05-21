"use client"

import { Badge } from "@/components/ui/badge"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { getStatusConfig } from "@/lib/status-config"
import { FeeStatusLink } from "@/components/finance"
import { AlertCircle, CheckCircle2, MapPin, Award, FileCheck } from "lucide-react"

interface AdmissionHeaderProps {
  profile: AdmissionProfileResponse | null
}

/**
 * Header chips — Commit 4 manager/admin cockpit.
 *
 * BE-driven, không tính FE. Mỗi chip thể hiện một signal duyệt nhanh để
 * manager/admin không phải mở từng tab xác minh.
 */
function HeaderChips({ profile }: { profile: AdmissionProfileResponse }) {
  const blockerCount = profile.validation_errors?.length ?? 0
  const eligibility = profile.eligibility_status ?? null
  const snapshot = profile.priority_resolution_snapshot ?? {}
  const kv = typeof snapshot.kv_resolved === "string" ? snapshot.kv_resolved : null
  const utBucket = (() => {
    const bucket = snapshot.ut_verified_bucket
    if (bucket && typeof bucket === "object" && "applied_code" in bucket) {
      const code = (bucket as { applied_code?: string | null }).applied_code
      return typeof code === "string" ? code : null
    }
    return null
  })()
  const verifiedCount = profile.document_stats?.verified_count ?? 0
  const mandatoryCount = profile.document_stats?.mandatory_count ?? 0
  const completionPercent = profile.completion_percent ?? 0

  return (
    <div className="flex flex-wrap items-center gap-1.5 ml-auto">
      {/* Completion */}
      <Badge
        variant="outline"
        className="text-xs gap-1"
        data-testid="header-chip-completion"
        title={`Hoàn thành ${completionPercent}%`}
      >
        <CheckCircle2 className="w-3 h-3" />
        {completionPercent}%
      </Badge>

      {/* Eligibility */}
      {eligibility && (
        <Badge
          variant={eligibility === "eligible" ? "default" : "outline"}
          className={`text-xs ${
            eligibility === "eligible"
              ? "bg-success-100 text-success-800 hover:bg-success-100"
              : "bg-warning-50 text-warning-700 border-warning-300"
          }`}
          data-testid="header-chip-eligibility"
          title={`Điều kiện: ${eligibility}`}
        >
          {eligibility === "eligible" ? "Đủ điều kiện" : "Chưa đủ điều kiện"}
        </Badge>
      )}

      {/* KV */}
      {kv && (
        <Badge
          variant="outline"
          className="text-xs gap-1 bg-info-50 border-info-200 text-info-700"
          data-testid="header-chip-kv"
          title="Khu vực ưu tiên"
        >
          <MapPin className="w-3 h-3" />
          {kv}
        </Badge>
      )}

      {/* UT bucket */}
      {utBucket && (
        <Badge
          variant="outline"
          className="text-xs gap-1 bg-purple-50 border-purple-200 text-purple-700"
          data-testid="header-chip-ut"
          title="Đối tượng ưu tiên đã duyệt"
        >
          <Award className="w-3 h-3" />
          UT{utBucket}
        </Badge>
      )}

      {/* Documents ratio */}
      {mandatoryCount > 0 && (
        <Badge
          variant="outline"
          className={`text-xs gap-1 ${
            verifiedCount >= mandatoryCount
              ? "bg-success-50 border-success-200 text-success-700"
              : "bg-muted text-muted-foreground"
          }`}
          data-testid="header-chip-docs"
          title="Tài liệu đã duyệt / bắt buộc"
        >
          <FileCheck className="w-3 h-3" />
          {verifiedCount}/{mandatoryCount}
        </Badge>
      )}

      {/* Blocker count */}
      {blockerCount > 0 && (
        <Badge
          variant="destructive"
          className="text-xs gap-1"
          data-testid="header-chip-blockers"
          title="Vấn đề cần sửa"
        >
          <AlertCircle className="w-3 h-3" />
          {blockerCount} vấn đề
        </Badge>
      )}
    </div>
  )
}

export function AdmissionHeader({ profile }: AdmissionHeaderProps) {
  const statusConfig = profile?.status ? getStatusConfig(profile.status, "admission") : null

  return (
    <div className="min-h-12 px-4 md:px-6 py-2 md:py-0 flex flex-wrap items-center gap-2 md:gap-3">
      {/* E2E #9 fix 2026-05-15 — heading shows profile.id (consistent with
          URL `/admissions/{id}`) + candidate full_name for UX. */}
      <h1 className="text-sm md:text-base font-semibold font-display">
        Hồ sơ #{profile?.id ?? "---"}
        {profile?.full_name ? ` — ${profile.full_name}` : " — Chưa có tên"}
      </h1>

      <span className="text-muted-foreground hidden sm:inline">·</span>

      {statusConfig && (
        <Badge variant={statusConfig.badgeVariant} className="text-xs">
          {statusConfig.label}
        </Badge>
      )}

      <span className="text-muted-foreground hidden md:inline">·</span>

      {profile?.id && <FeeStatusLink profileId={profile.id} variant="badge" />}

      <span className="text-muted-foreground hidden md:inline">·</span>

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

      {/* Commit 4 — review signal chips for manager/admin cockpit. */}
      {profile && <HeaderChips profile={profile} />}
    </div>
  )
}
