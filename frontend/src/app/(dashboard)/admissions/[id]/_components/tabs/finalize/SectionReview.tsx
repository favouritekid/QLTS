/**
 * SectionReview — "RÀ SOÁT CÂU TRẢ LỜI".
 *
 * 7 compact rows (Step 1-7), each a <button> deep-linking via `onNavigateToStep`.
 * Step 1-6 read `step_status[n]` for the status badge. Step 7 (Học phí) is
 * OVERRIDDEN to `displayStatus="info"` (neutral) and never reads `step_status[7]`
 * (hard-coded "success" — plan B4/I5): no green/success badge, does NOT contribute
 * to ready/completed, CTA only navigates. Detailed tables live in InspectionDetails.
 */

"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ChevronRight } from "lucide-react"
import { ADMISSION_STEPS } from "@/lib/constants/admission-steps"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface SectionReviewProps {
  profile: AdmissionProfileResponse
  onNavigateToStep: (step: number) => void
}

type DisplayStatus = "success" | "warning" | "error" | "locked" | "info" | "unknown"

const STATUS_META: Record<
  DisplayStatus,
  { variant: "success" | "warning" | "error" | "secondary" | "info"; label: string }
> = {
  success: { variant: "success", label: "Đầy đủ" },
  warning: { variant: "warning", label: "Cần bổ sung" },
  error: { variant: "error", label: "Cần xử lý" },
  locked: { variant: "secondary", label: "Chưa mở" },
  info: { variant: "info", label: "Tham khảo" },
  unknown: { variant: "secondary", label: "—" },
}

/** Step 7 is display-only — never read step_status[7]. */
function resolveDisplayStatus(
  step: number,
  stepStatus: Record<string, string> | null | undefined,
): DisplayStatus {
  if (step === 7) return "info"
  const raw = stepStatus?.[String(step)]
  if (raw === "success" || raw === "warning" || raw === "error" || raw === "locked") {
    return raw
  }
  return "unknown"
}

function resolveMetric(
  step: number,
  status: DisplayStatus,
  profile: AdmissionProfileResponse,
): string {
  if (step === 7) return "Dữ liệu học phí xem tại Step 7"
  if (step === 5 && profile.total_score != null) {
    // Format to 2 decimals so a float artifact (e.g. 7.333333333333333) never
    // renders raw; mirrors the other score surfaces.
    const total =
      typeof profile.total_score === "number"
        ? profile.total_score.toFixed(2)
        : profile.total_score
    return `Tổng điểm: ${total}`
  }
  if (step === 6 && profile.document_stats) {
    const s = profile.document_stats
    return `${s.submitted_count}/${s.mandatory_count} tài liệu`
  }
  return STATUS_META[status].label
}

export function SectionReview({ profile, onNavigateToStep }: SectionReviewProps) {
  const stepStatus = profile.step_status
  // Steps 1-7 only (Step 8 is the current tab itself).
  const rows = ADMISSION_STEPS.filter((s) => s.id <= 7)

  return (
    <Card data-testid="section-review">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Rà soát câu trả lời</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {rows.map((step) => {
          const status = resolveDisplayStatus(step.id, stepStatus)
          const meta = STATUS_META[status]
          const metric = resolveMetric(step.id, status, profile)
          // Step 7 only navigates ("Xem Step 7"); editable rows say "Sửa" when
          // they need work, "Xem" otherwise.
          const ctaLabel =
            step.id === 7
              ? "Xem Step 7"
              : status === "error" || status === "warning"
                ? "Sửa"
                : "Xem"

          return (
            <button
              key={step.id}
              type="button"
              onClick={() => onNavigateToStep(step.id)}
              className="w-full flex items-center justify-between gap-3 rounded-lg border p-2.5 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex items-center gap-3 min-w-0">
                <Badge variant={meta.variant} className="shrink-0">
                  {step.id}
                </Badge>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-foreground break-words">
                    {step.label}
                  </span>
                  <span className="block text-xs text-muted-foreground break-words">
                    {metric}
                  </span>
                </span>
              </span>
              <span className="flex items-center gap-1 text-sm font-medium text-primary shrink-0">
                {ctaLabel}
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </span>
            </button>
          )
        })}
      </CardContent>
    </Card>
  )
}
