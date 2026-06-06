/**
 * PerNvScoreSummary Component
 *
 * P0 hotfix multi-NV (2026-06-04) — per-nguyện-vọng score summary (DISPLAY).
 *
 * Multi-NV profiles keep scores per choice (ProfileChoiceScore); the
 * profile-level `total_score` is null. The backend computes each NV's
 * `computed_total_score` + `data_complete` + `admission_threshold_passed`
 * and the FE renders them verbatim (thin client — NO scoring math here).
 *
 * `admission_threshold_passed` is DISPLAY ONLY: being below the sàn does
 * NOT block submit ("nộp" ≠ "trúng tuyển"), so it renders as a neutral
 * reference badge, never a blocking error.
 *
 * Shared by ScoreReviewCard / ScoreSnapshot / AcademicCard so the
 * profile-level "Tổng Điểm Xét Tuyển" never shows a misleading 0.00 for a
 * multi-NV profile.
 */
"use client"

import { Badge } from "@/components/ui/badge"
import type { AdmissionProfileChoiceResponse } from "@/lib/zod/admission-choices"

interface PerNvScoreSummaryProps {
  choices: AdmissionProfileChoiceResponse[]
  /** Tighter score font for the cockpit cards. */
  compact?: boolean
}

export function PerNvScoreSummary({
  choices,
  compact = false,
}: PerNvScoreSummaryProps) {
  const ordered = [...choices].sort(
    (a, b) => a.display_order - b.display_order,
  )

  if (ordered.length === 0) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-testid="per-nv-score-empty"
      >
        Chưa có nguyện vọng
      </p>
    )
  }

  return (
    <ul className="space-y-2" data-testid="per-nv-score-summary">
      {ordered.map((choice) => {
        // computed_total_score is a Pydantic Decimal → arrives as a STRING
        // ("7.50") over JSON (the Zod type infers `number` but the profile
        // payload reaching these cards is not runtime-parsed). Coerce
        // defensively so .toFixed never throws on a string.
        const rawScore = choice.computed_total_score
        const scoreNum =
          rawScore === null || rawScore === undefined ? null : Number(rawScore)
        const scoreLabel =
          scoreNum !== null && !Number.isNaN(scoreNum)
            ? scoreNum.toFixed(2)
            : "—"
        // Program name only — drop the `|| display_path_name` machine-composite
        // fallback (… - 2026 - 201 - DOT_2) so it never leaks codes here.
        const title = (choice.display_program_name ?? "").trim() || "—"

        return (
          <li
            key={choice.id}
            className="flex items-start justify-between gap-3 rounded-md border p-2"
            data-testid={`per-nv-row-${choice.id}`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="shrink-0 text-xs font-semibold text-muted-foreground">
                  NV{choice.display_order}
                </span>
                <span className="truncate text-sm font-medium" title={title}>
                  {title}
                </span>
              </div>
              {choice.display_subject_group_name && (
                <span className="text-xs text-muted-foreground">
                  {choice.display_subject_group_name}
                </span>
              )}
            </div>

            <div className="flex shrink-0 flex-col items-end gap-1">
              <span
                className={`font-bold tabular-nums text-info-700 ${
                  compact ? "text-lg" : "text-xl"
                }`}
                data-testid={`per-nv-score-${choice.id}`}
              >
                {scoreLabel}
              </span>
              <div className="flex items-center gap-1">
                {choice.data_complete ? (
                  <Badge variant="success" className="text-[10px]">
                    Đủ điểm
                  </Badge>
                ) : (
                  <Badge variant="warning" className="text-[10px]">
                    Thiếu điểm
                  </Badge>
                )}
                {/* DISPLAY ONLY — does not gate submit. */}
                {choice.admission_threshold_passed === true && (
                  <Badge variant="info" className="text-[10px]">
                    Đạt sàn
                  </Badge>
                )}
                {choice.admission_threshold_passed === false && (
                  <Badge variant="outline" className="text-[10px]">
                    Dưới sàn
                  </Badge>
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
