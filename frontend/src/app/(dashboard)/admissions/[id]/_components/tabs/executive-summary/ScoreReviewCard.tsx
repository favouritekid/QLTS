"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Calculator, CheckCircle2, AlertTriangle } from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { PerNvScoreSummary } from "./PerNvScoreSummary"

interface ScoreReviewCardProps {
  profile: AdmissionProfileResponse
}

/**
 * Cockpit card cho § điểm xét tuyển. BE-driven: đọc total_score /
 * average_score / admission_scores root-level fields.
 *
 * P0 hotfix multi-NV: khi uses_choice_engine, total_score profile-level là
 * null → render điểm per-NV (PerNvScoreSummary) thay vì "—"/0.00.
 */
export function ScoreReviewCard({ profile }: ScoreReviewCardProps) {
  const isMultiNv = profile.uses_choice_engine === true
  const choices = profile.choices ?? []

  const methodType = profile.applied_rules?.method_type
  const isGpaOnly = methodType === "gpa_only"

  const gpa = profile.admission_scores?.gpa
  const totalScore = profile.total_score
  const averageScore = profile.average_score
  const selectedGroup = profile.admission_scores?.selected_group

  const hasScore = isMultiNv
    ? choices.length > 0 && choices.every((c) => c.data_complete)
    : isGpaOnly
    ? gpa !== null && gpa !== undefined
    : totalScore !== null && totalScore !== undefined

  const StatusIcon = hasScore ? CheckCircle2 : AlertTriangle
  const statusColor = hasScore ? "text-success-600" : "text-warning-600"

  return (
    <Card data-testid="score-review-card">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calculator className="w-5 h-5 text-muted-foreground" />
            <CardTitle className="text-lg">Điểm xét tuyển</CardTitle>
          </div>
          <StatusIcon className={`w-6 h-6 ${statusColor}`} />
        </div>
      </CardHeader>

      <CardContent className="space-y-2 text-sm">
        {isMultiNv ? (
          <PerNvScoreSummary choices={choices} compact />
        ) : isGpaOnly ? (
          <div className="flex justify-between items-baseline">
            <span className="text-muted-foreground">GPA:</span>
            <span className="font-bold text-2xl tabular-nums">
              {gpa !== null && gpa !== undefined ? gpa.toFixed(2) : "—"}
            </span>
          </div>
        ) : (
          <>
            <div className="flex justify-between items-baseline">
              <span className="text-muted-foreground">Tổng điểm{selectedGroup ? ` (${selectedGroup})` : ""}:</span>
              <span className="font-bold text-2xl tabular-nums">
                {totalScore !== null && totalScore !== undefined ? totalScore.toFixed(2) : "—"}
              </span>
            </div>
            {averageScore !== null && averageScore !== undefined && (
              <div className="flex justify-between items-baseline text-xs text-muted-foreground">
                <span>Trung bình:</span>
                <span className="tabular-nums">{averageScore.toFixed(2)}</span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
