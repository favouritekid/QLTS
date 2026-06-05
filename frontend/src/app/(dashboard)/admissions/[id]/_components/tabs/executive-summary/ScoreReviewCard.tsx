/**
 * ScoreReviewCard — compact "Điểm xét tuyển" cockpit signal.
 *
 * BE-driven: total_score / average_score / admission_scores.gpa (single-NV) or
 * per-NV choices (uses_choice_engine). `admission_threshold_passed` is DISPLAY
 * ONLY (being below the sàn never blocks; "nộp" ≠ "trúng tuyển") so it renders as
 * a neutral reference in the secondary line, never an error tone.
 */

"use client"

import { SignalCell, type SignalTone } from "./SignalCell"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ScoreReviewCardProps {
  profile: AdmissionProfileResponse
}

export function ScoreReviewCard({ profile }: ScoreReviewCardProps) {
  const isMultiNv = profile.uses_choice_engine === true
  const choices = profile.choices ?? []
  const methodType = profile.applied_rules?.method_type
  const isGpaOnly = methodType === "gpa_only"

  const gpa = profile.admission_scores?.gpa
  const totalScore = profile.total_score
  const averageScore = profile.average_score
  const selectedGroup = profile.admission_scores?.selected_group

  let tone: SignalTone
  let primary: string
  let secondary: string

  if (isMultiNv) {
    const total = choices.length
    const completeCount = choices.filter((c) => c.data_complete).length
    const passedCount = choices.filter((c) => c.admission_threshold_passed === true).length
    tone = total > 0 && completeCount === total ? "success" : "warning"
    primary = total > 0 ? `${completeCount}/${total} NV đủ điểm` : "—"
    secondary =
      total === 0
        ? "Chưa có nguyện vọng"
        : passedCount > 0
          ? `${passedCount}/${total} NV đạt sàn`
          : "Chưa NV nào đạt sàn"
  } else if (isGpaOnly) {
    tone = gpa != null ? "success" : "warning"
    primary = gpa != null ? gpa.toFixed(2) : "—"
    secondary = gpa != null ? "Điểm TB (GPA) · thang 10" : "Chưa có điểm TB (GPA)"
  } else {
    tone = totalScore != null ? "success" : "warning"
    primary =
      totalScore != null
        ? `${totalScore.toFixed(2)}${selectedGroup ? ` (${selectedGroup})` : ""}`
        : "—"
    secondary =
      averageScore != null
        ? `Trung bình ${averageScore.toFixed(2)}`
        : totalScore != null
          ? "Tổng điểm xét tuyển"
          : "Chưa có điểm xét tuyển"
  }

  return (
    <SignalCell
      testId="score-review-card"
      title="Điểm xét tuyển"
      tone={tone}
      primary={primary}
      secondary={secondary}
    />
  )
}
