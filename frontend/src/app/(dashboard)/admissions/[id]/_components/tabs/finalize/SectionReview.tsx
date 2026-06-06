/**
 * SectionReview — "Rà soát câu trả lời" (officer/default workflow surface).
 *
 * A 7-row table (Step 1-7): Bước · Nội dung · Trạng thái · Chi tiết · Thao tác.
 * Step 1-6 read `step_status[n]` for the status badge. Step 7 (Học phí) is
 * OVERRIDDEN to `displayStatus="info"` ("Tham khảo"); it never reads
 * `step_status[7]` (hard-coded "success"), shows no green/"Đầy đủ" badge, does NOT
 * contribute to ready/completed, and its CTA only navigates.
 *
 * The "Thao tác" cell is a real <button> → onNavigateToStep(n) (routes through the
 * unsaved-changes guard in AdmissionDetailClient). Detailed tables live in
 * InspectionDetails.
 */

"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
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

/** "Chi tiết" cell — a specific metric for steps 5/6, otherwise "—". */
function resolveDetail(step: number, profile: AdmissionProfileResponse): string {
  if (step === 5) {
    const total =
      typeof profile.total_score === "number" ? profile.total_score.toFixed(2) : "—"
    return `Tổng điểm: ${total}`
  }
  if (step === 6 && profile.document_stats) {
    const s = profile.document_stats
    return s.mandatory_count === 0
      ? "Không yêu cầu tài liệu"
      : `${s.submitted_count}/${s.mandatory_count} tài liệu`
  }
  return "—"
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
      <CardContent className="px-0 sm:px-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th scope="col" className="px-3 py-2 text-left font-medium">Bước</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">Nội dung</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">Trạng thái</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">Chi tiết</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((step) => {
                const status = resolveDisplayStatus(step.id, stepStatus)
                const meta = STATUS_META[status]
                const detail = resolveDetail(step.id, profile)
                const ctaLabel =
                  step.id === 7
                    ? "Xem Bước 7"
                    : status === "error" || status === "warning"
                      ? "Sửa"
                      : "Xem"

                return (
                  <tr key={step.id} className="border-b last:border-0">
                    <td className="whitespace-nowrap px-3 py-2.5 text-muted-foreground">
                      Bước {step.id}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-foreground">{step.label}</td>
                    <td className="px-3 py-2.5">
                      <Badge variant={meta.variant}>{meta.label}</Badge>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground break-words">{detail}</td>
                    <td className="px-3 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => onNavigateToStep(step.id)}
                        className="rounded-md px-2 py-1 text-sm font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {ctaLabel}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
