/**
 * ReadinessHero — Step 8 decision surface header (NOT a mini-dashboard).
 *
 * Answers exactly two questions: which decision state is the profile in, and what
 * should this user do next. Everything else lives in the cockpit / inspection.
 *
 * Structure (linear, same order on every viewport — plan Hero redesign):
 *   identity + ONE verdict badge → one-line decision summary (only when it adds
 *   info) → CTA group → 2-3 compact metrics (Hoàn thành · Tài liệu · Mục cần xử
 *   lý/Cảnh báo). NO separate eligibility badge, NO eligibility metric, NO helper
 *   alert that merely restates the badge. Owns NO utility actions (those stay on
 *   the sticky AdmissionActions bar).
 *
 * Thin Client: renders fields the backend computed + the hook mapped.
 */

"use client"

import type { ReactNode } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"
import { User } from "lucide-react"
import { getAdmissionMethodLabel, getChoiceSummaryLabel } from "@/lib/utils/admission-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import type { ReadinessTone, SubmissionReadiness } from "./useSubmissionReadiness"
import {
  READINESS_TONE_VARIANT,
  READINESS_TONE_ICON,
  READINESS_TONE_TEXT,
} from "./readinessTone"

interface ReadinessHeroProps {
  profile: AdmissionProfileResponse
  readiness: SubmissionReadiness
  /** DecisionActionsPanel (or null). The single decision CTA surface. */
  cta?: ReactNode
}

function ToneBadge({ tone, label }: { tone: ReadinessTone; label: string }) {
  const Icon = READINESS_TONE_ICON[tone]
  return (
    <Badge variant={READINESS_TONE_VARIANT[tone]} className="gap-1.5 px-3 py-1 text-sm max-w-full">
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </Badge>
  )
}

function Metric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <div className="text-sm font-semibold break-words">{children}</div>
    </div>
  )
}

export function ReadinessHero({ profile, readiness, cta }: ReadinessHeroProps) {
  // "Nguyện vọng" = the candidate's actual choice(s) (program/degree), NOT the
  // method. "Phương thức" shows the humanized method separately (never a raw code).
  const choiceLabel = getChoiceSummaryLabel(profile)
  const methodLabel = getAdmissionMethodLabel(profile.applied_rules)
  const completion = profile.completion_percent ?? 0
  const stats = profile.document_stats
  const docMetric =
    !stats || typeof stats.mandatory_count !== "number"
      ? "—"
      : stats.mandatory_count === 0
        ? "Không yêu cầu"
        : `${stats.submitted_count}/${stats.mandatory_count} đã nộp`
  // Display code formatted FE-side from year + id (no dedicated BE field).
  const code = profile.academic_year
    ? `HS-${profile.academic_year}-${String(profile.id).padStart(5, "0")}`
    : `#${profile.id}`
  const outstanding = readiness.actionItemCount

  return (
    <Card className="border-2 border-primary/20 shadow-sm">
      <CardContent className="p-4 sm:p-6 space-y-4">
        {/* Identity (left) + the SINGLE verdict badge (right desktop / below mobile). */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3 min-w-0">
            <div
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary"
              aria-hidden="true"
            >
              <User className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg sm:text-2xl font-semibold leading-tight break-words">
                {profile.full_name || "Chưa có tên"}
              </h2>
              <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-sm text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="font-medium text-foreground">Mã hồ sơ:</span>
                  <span className="font-mono">{code}</span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="font-medium text-foreground">CCCD:</span>
                  <span className="font-mono">
                    {profile.citizen_id || <span className="text-error-500">Chưa nhập</span>}
                  </span>
                </span>
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="font-medium text-foreground">Nguyện vọng:</span>
                  <span className="font-semibold text-foreground break-words">{choiceLabel}</span>
                </span>
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="font-medium text-foreground">Phương thức:</span>
                  <span className="break-words">{methodLabel}</span>
                </span>
              </div>
            </div>
          </div>

          <div className="shrink-0 sm:pt-0.5">
            <ToneBadge tone={readiness.verdictTone} label={readiness.verdictLabel} />
          </div>
        </div>

        {/* One-line decision summary — only when it adds info beyond the badge. */}
        {readiness.decisionSummary && (
          <p className="text-sm text-muted-foreground break-words">{readiness.decisionSummary}</p>
        )}

        {/* CTA — the single decision action surface (DecisionActionsPanel). */}
        {cta && (
          <div className="scroll-mb-[calc(var(--bottom-nav-height-safe)_+_5rem)] lg:scroll-mb-6">
            {cta}
          </div>
        )}

        {/* Secondary metrics — 1 column on narrow phones, 2-3 columns from 520px.
            The "Mục cần xử lý" metric is HIDDEN when 0: a "0" under a warning verdict
            badge is noise — the doc/eligibility warning already shows via the Tài
            liệu metric tone + the verdict badge. */}
        <div
          className={cn(
            "grid grid-cols-1 gap-3 border-t pt-4",
            outstanding > 0 ? "min-[520px]:grid-cols-3" : "min-[520px]:grid-cols-2",
          )}
        >
          <Metric label="Hoàn thành">
            <div className="flex items-center gap-2">
              <Progress value={completion} className="h-2 flex-1" />
              <span className="text-primary font-bold tabular-nums">{completion}%</span>
            </div>
          </Metric>
          <Metric label="Tài liệu">
            <span className={READINESS_TONE_TEXT[readiness.documentTone]}>{docMetric}</span>
          </Metric>
          {outstanding > 0 && (
            <Metric label={readiness.outstandingLabel}>
              <span className="tabular-nums text-warning-700">{outstanding}</span>
            </Metric>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
