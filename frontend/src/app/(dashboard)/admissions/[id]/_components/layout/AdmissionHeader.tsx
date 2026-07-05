"use client"

import type { ReactNode } from "react"
import { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { getStatusConfig } from "@/lib/status-config"
import { FeeStatusLink } from "@/components/finance"
import { GraduationCap, MapPin, Award, ArrowRight } from "lucide-react"
import { ProfileActionMenu } from "./ProfileActionMenu"
import { derivePriorityIssues, issueTotalCount } from "./priorityIssues"
import { getInitials } from "@/app/(dashboard)/admissions/_components/roster-parts"
import { cn } from "@/lib/utils"

interface AdmissionHeaderProps {
  profile: AdmissionProfileResponse | null
  /** Jump to the first blocking step — shared with the Step-8 "Kiểm tra toàn bộ". */
  onCheckCondition?: () => void
  onClaim?: () => void
  onUnclaim?: () => void
  isClaiming?: boolean
  isUnclaiming?: boolean
  onDelete?: () => void
  isDeleting?: boolean
}

function LedgerItem({ k, className, children }: { k: string; className?: string; children: ReactNode }) {
  return (
    <div className={cn("flex items-center gap-2 md:border-l md:border-border/60 md:pl-4", className)}>
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/80">{k}</span>
      {children}
    </div>
  )
}

/**
 * Dải trạng thái hồ sơ — the case status header.
 *
 * Reads top-to-bottom in the order an officer scans a case file: who · registered
 * major (nguyện vọng) · assigned officer · workflow status · eligibility verdict ·
 * what to do next. Eligibility is the page's mood colour (amber = chưa đủ, green =
 * đủ); the rest stays calm. 100% BE-driven (thin client) — no eligibility/scoring
 * computed here.
 */
export function AdmissionHeader({
  profile,
  onCheckCondition,
  onClaim,
  onUnclaim,
  isClaiming = false,
  isUnclaiming = false,
  onDelete,
  isDeleting = false,
}: AdmissionHeaderProps) {
  if (!profile) {
    return (
      <div className="min-h-12 px-4 md:px-6 py-3">
        <h1 className="text-sm md:text-base font-semibold font-display">Hồ sơ #--- — Đang tải…</h1>
      </div>
    )
  }

  const statusConfig = getStatusConfig(profile.status, "admission")
  const eligibility = profile.eligibility_status
  const isEligible = eligibility === "eligible"
  const verdictKnown = eligibility === "eligible" || eligibility === "ineligible"

  const choices = [...(profile.choices ?? [])].sort((a, b) => a.display_order - b.display_order)
  const firstChoice = choices[0]
  const extraChoices = Math.max(0, choices.length - 1)
  // Legacy single-NV profiles (uses_choice_engine=false) carry no choices[] but
  // still identify the selected program via the denormalized program_name. Fall
  // back to it ONLY for those — a real choice-engine profile with an empty
  // choices[] genuinely has no nguyện vọng yet (program_name may be a stale
  // lead/offering display value), so it must read "Chưa chọn nguyện vọng".
  const legacyProgram =
    firstChoice || profile.uses_choice_engine ? null : profile.program_name?.trim() || null

  // "Việc cần xử lý" = the same count the IssueSummary panel shows (validation +
  // priority + required-data), so the header and the panel never disagree.
  const workItems = issueTotalCount(
    profile.validation_errors?.length ?? 0,
    derivePriorityIssues(profile).length,
    profile.grouped_validation_errors,
  )

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
  const verified = profile.document_stats?.verified_count ?? 0
  const mandatory = profile.document_stats?.mandatory_count ?? 0
  const completion = profile.completion_percent ?? 0
  const owner = profile.assigned_officer_name

  const mood = verdictKnown ? (isEligible ? "eligible" : "ineligible") : "neutral"

  return (
    <div
      className={cn(
        "relative border-l-4 px-4 py-3",
        mood === "ineligible" && "border-l-warning-600 bg-gradient-to-b from-warning-50 to-transparent",
        mood === "eligible" && "border-l-success bg-gradient-to-b from-success-50 to-transparent",
        mood === "neutral" && "border-l-border",
      )}
    >
      <div className="space-y-2.5">
        {/* 1 · identity + verdict + overflow menu */}
        <div className="flex items-start justify-between gap-3">
          <h1 className="min-w-0 truncate text-base font-semibold font-display leading-tight md:text-lg">
            {profile.full_name ?? "Chưa có tên"}
            <span className="ml-1.5 text-sm font-medium text-muted-foreground">#{profile.id}</span>
          </h1>
          <div className="flex flex-shrink-0 items-center gap-2">
            {verdictKnown && (
              <span
                data-testid="header-chip-eligibility"
                className={cn(
                  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1 text-xs font-bold",
                  isEligible ? "bg-success-100 text-success-800" : "bg-warning-100 text-warning-800",
                )}
              >
                <span className={cn("h-2 w-2 rounded-full", isEligible ? "bg-success-600" : "bg-warning-600")} />
                <span className="md:hidden">{isEligible ? "Đủ ĐK" : "Chưa đủ ĐK"}</span>
                <span className="hidden md:inline">{isEligible ? "Đủ điều kiện" : "Chưa đủ điều kiện"}</span>
              </span>
            )}
            <ProfileActionMenu
              profile={profile}
              onClaim={onClaim}
              onUnclaim={onUnclaim}
              isClaiming={isClaiming}
              isUnclaiming={isUnclaiming}
              onDelete={onDelete}
              isDeleting={isDeleting}
            />
          </div>
        </div>

        {/* 2 · nguyện vọng — "đăng ký ngành gì" */}
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-indigo-50 text-indigo-600">
            <GraduationCap className="h-3.5 w-3.5" />
          </span>
          {firstChoice ? (
            <>
              <span className="flex-shrink-0 rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-extrabold tracking-wide text-indigo-700">
                NV{firstChoice.display_order}
              </span>
              <span className="truncate font-semibold text-foreground">
                {firstChoice.display_program_name || firstChoice.display_path_name}
              </span>
              {firstChoice.display_degree_level && (
                <span className="hidden flex-shrink-0 text-muted-foreground sm:inline">
                  · {firstChoice.display_degree_level}
                </span>
              )}
              {extraChoices > 0 && (
                <span className="flex-shrink-0 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-600">
                  +{extraChoices} NV
                </span>
              )}
            </>
          ) : legacyProgram ? (
            <span className="truncate font-semibold text-foreground">{legacyProgram}</span>
          ) : (
            <span className="text-muted-foreground">Chưa chọn nguyện vọng</span>
          )}
        </div>

        {/* 3 · phụ trách · trạng thái · hành động */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border/60 pt-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700">
              {owner ? getInitials(owner) : "—"}
            </span>
            <span className="truncate text-xs text-foreground md:text-sm">
              <span className="font-semibold">{owner ?? "Chưa phân công"}</span>
              <span className="text-muted-foreground"> · phụ trách</span>
            </span>
          </div>

          <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted px-2.5 py-1 text-xs font-semibold text-foreground/80">
            <span className="h-2 w-2 rounded-full bg-slate-400" />
            {statusConfig?.label ?? profile.status}
          </span>

          {profile.assigned_reviewer_name && (
            <span className="hidden text-xs text-muted-foreground lg:inline">
              Người duyệt: {profile.assigned_reviewer_name}
            </span>
          )}

          {workItems > 0 && (
            <button
              type="button"
              data-testid="header-chip-blockers"
              onClick={onCheckCondition}
              className="ml-auto inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground shadow-sm transition hover:brightness-105 active:translate-y-px"
            >
              <span className="tabular-nums">{workItems}</span>
              <span className="hidden sm:inline">việc cần xử lý</span>
              <span className="sm:hidden">việc</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* 4 · ledger */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-0.5 text-xs">
          <div className="flex min-w-[150px] flex-1 items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full",
                  mood === "eligible" ? "bg-success" : mood === "ineligible" ? "bg-warning-600" : "bg-primary",
                )}
                style={{ width: `${completion}%` }}
              />
            </div>
            <span data-testid="header-chip-completion" className="font-semibold tabular-nums text-foreground">
              {completion}%
            </span>
          </div>

          <LedgerItem k="Học phí">
            <FeeStatusLink profileId={profile.id} variant="badge" />
          </LedgerItem>

          {mandatory > 0 && (
            <LedgerItem k="Tài liệu">
              <span
                data-testid="header-chip-docs"
                className={cn("font-bold tabular-nums", verified >= mandatory ? "text-success-700" : "text-warning-700")}
              >
                {verified}/{mandatory}
              </span>
            </LedgerItem>
          )}

          {/* KV + Đối tượng UT stay visible on every breakpoint — a manager
              reviewing a case on mobile/tablet must not lose these priority
              cockpit signals (the ledger row wraps rather than hiding them). */}
          {kv && (
            <LedgerItem k="KV">
              <span data-testid="header-chip-kv" className="inline-flex items-center gap-1 font-bold text-info-700">
                <MapPin className="h-3 w-3" /> {kv}
              </span>
            </LedgerItem>
          )}

          {utBucket && (
            <LedgerItem k="Đối tượng UT">
              <span data-testid="header-chip-ut" className="inline-flex items-center gap-1 font-bold text-purple-700">
                <Award className="h-3 w-3" /> UT{utBucket}
              </span>
            </LedgerItem>
          )}
        </div>
      </div>
    </div>
  )
}
