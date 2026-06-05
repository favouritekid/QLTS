/**
 * ReadinessHero — Step 8 first-viewport readiness summary.
 *
 * Replaces the old `ExecutiveSummaryHeader` at the top of Step 8 (it absorbs the
 * identity row + completion). Shows TWO separate signals (plan B3):
 *   1. Eligibility verdict  — "Đủ điều kiện xét" / "Chưa đủ" (xét-tuyển state).
 *   2. Action readiness     — label/tone for the ACTUAL primary action surfaced.
 *
 * Owns the visual shell of the CTA slot: `DecisionActionsPanel` is rendered via
 * the `cta` prop and is the ONLY decision surface (plan D2). The Hero does NOT
 * render utility actions ("Kiểm tra toàn bộ" / "Gửi link nộp") — those stay on
 * the sticky AdmissionActions bar (plan D1/D3).
 *
 * Thin Client: renders fields the backend computed + the hook mapped.
 */

"use client"

import type { ReactNode } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import {
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Info,
  CircleDot,
  type LucideIcon,
} from "lucide-react"
import { getAdmissionMethodLabel } from "@/lib/utils/admission-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { ReadinessTone, SubmissionReadiness } from "./useSubmissionReadiness"

interface ReadinessHeroProps {
  profile: AdmissionProfileResponse
  readiness: SubmissionReadiness
  /** DecisionActionsPanel (or null). Rendered as the single CTA surface. */
  cta?: ReactNode
}

type BadgeVariant = "success" | "warning" | "error" | "info" | "secondary"

const TONE_VARIANT: Record<ReadinessTone, BadgeVariant> = {
  success: "success",
  warning: "warning",
  error: "error",
  info: "info",
  neutral: "secondary",
}

const TONE_ICON: Record<ReadinessTone, LucideIcon> = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
  info: Info,
  neutral: CircleDot,
}

function ToneBadge({
  tone,
  label,
  className,
}: {
  tone: ReadinessTone
  label: string
  className?: string
}) {
  const Icon = TONE_ICON[tone]
  return (
    <Badge
      variant={TONE_VARIANT[tone]}
      className={cn("text-sm px-3 py-1 gap-1.5 max-w-full", className)}
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </Badge>
  )
}

function Metric({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <div className="text-sm font-semibold text-foreground break-words">{children}</div>
    </div>
  )
}

export function ReadinessHero({ profile, readiness, cta }: ReadinessHeroProps) {
  const methodLabel = getAdmissionMethodLabel(profile.applied_rules)
  const completion = profile.completion_percent ?? 0
  const stats = profile.document_stats
  const docMetric =
    stats && typeof stats.mandatory_count === "number"
      ? `${stats.submitted_count}/${stats.mandatory_count} đã nộp`
      : "—"

  return (
    <Card className="border-2 border-primary/20 shadow-sm">
      <CardHeader className="pb-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="text-xl sm:text-2xl break-words">
              {profile.full_name || "Chưa có tên"}
            </CardTitle>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span className="font-medium text-foreground">Mã hồ sơ:</span>
                <span className="font-mono font-semibold text-primary">#{profile.id}</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="font-medium text-foreground">CCCD:</span>
                <span className="font-mono">
                  {profile.citizen_id || <span className="text-error-500">Chưa nhập</span>}
                </span>
              </span>
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="font-medium text-foreground">Nguyện vọng:</span>
                <span className="font-semibold text-foreground break-words">{methodLabel}</span>
              </span>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Two separate verdict signals (plan B3). Side-by-side from mobile so
            the CTA below them sits higher (clear of the fixed sticky bar). */}
        <div className="flex flex-row flex-wrap items-center gap-2 sm:items-start sm:gap-x-4 sm:gap-y-2">
          <div className="min-w-0">
            {/* Captions hidden on mobile to keep the Hero short (the badge text
                is self-explanatory); shown on desktop where space allows. */}
            <p className="hidden sm:block text-xs text-muted-foreground mb-1">Điều kiện xét</p>
            <ToneBadge tone={readiness.eligibilityTone} label={readiness.eligibilityLabel} />
          </div>
          <div className="min-w-0">
            <p className="hidden sm:block text-xs text-muted-foreground mb-1">Việc của bạn</p>
            <ToneBadge tone={readiness.readinessTone} label={readiness.readinessLabel} />
          </div>
        </div>

        {/* Single CTA surface (DecisionActionsPanel) — placed directly under the
            verdict signals so it stays in the first viewport and clear of the
            fixed sticky AdmissionActions bar on mobile, where the identity +
            metrics wrap tall. Metrics/summary below are secondary. Hero owns the
            shell (plan D2). scroll-mb is a backstop for scroll-into-view. */}
        {cta && (
          <div className="border-t pt-3 scroll-mb-[calc(var(--bottom-nav-height-safe)_+_5rem)] lg:scroll-mb-6">
            {cta}
          </div>
        )}

        {/* 3 metrics — 3 columns from mobile to keep the Hero compact. */}
        <div className="grid grid-cols-3 gap-3 border-t pt-3">
          <Metric label="Hoàn thành">
            <div className="flex items-center gap-2">
              <Progress value={completion} className="h-2 flex-1" />
              <span className="text-primary font-bold tabular-nums">{completion}%</span>
            </div>
          </Metric>
          <Metric label="Tài liệu bắt buộc">{docMetric}</Metric>
          <Metric label="Điều kiện xét tuyển">{readiness.eligibilityLabel}</Metric>
        </div>

        {/* Optional next-action hint from executive_summary. Kept to one
            compact line. */}
        {readiness.summaryLine && (
          <p className="text-xs text-muted-foreground line-clamp-1 break-words">
            <span className="font-medium text-foreground">Gợi ý: </span>
            {readiness.summaryLine}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
