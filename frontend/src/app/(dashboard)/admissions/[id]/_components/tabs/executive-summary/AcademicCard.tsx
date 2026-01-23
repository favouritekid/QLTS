/**
 * AcademicCard Component
 *
 * Health Check Grid - Khối 2: Năng Lực Học Tập
 * Displays: GPA/Total Score (large) + Step 3 (Academic History) + Step 4 (Scores)
 */

"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { GraduationCap, CheckCircle2, XCircle, AlertTriangle } from "lucide-react"
import { HealthCheckItem } from "./HealthCheckItem"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface AcademicCardProps {
  profile: AdmissionProfileResponse
}

export function AcademicCard({ profile }: AcademicCardProps) {
  const step3Status = profile.step_status?.["3"] ?? "locked"
  const step4Status = profile.step_status?.["4"] ?? "locked"

  // Check if academic section is complete
  const isComplete = step3Status === "success" && step4Status === "success"
  const hasError = step3Status === "error" || step4Status === "error"

  // Get error counts from grouped validation errors
  const scoresErrorCount = profile.grouped_validation_errors?.scores?.count ?? 0

  // Status icon for the whole card
  const StatusIcon = isComplete
    ? CheckCircle2
    : hasError
    ? XCircle
    : AlertTriangle

  const statusColor = isComplete
    ? "text-green-600"
    : hasError
    ? "text-red-600"
    : "text-amber-600"

  // Determine which score to display
  const methodType = profile.applied_rules?.method_type
  const isGpaOnly = methodType === "gpa_only"

  const gpa = profile.admission_scores?.gpa
  const totalScore = profile.admission_scores?.total_score
  const averageScore = profile.admission_scores?.average_score
  const selectedGroup = profile.admission_scores?.selected_group

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <GraduationCap className="w-5 h-5 text-muted-foreground" />
            <CardTitle className="text-lg">Năng Lực Học Tập</CardTitle>
          </div>
          <StatusIcon className={`w-6 h-6 ${statusColor}`} />
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Score Display - Large */}
        <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 border border-blue-200">
          {isGpaOnly ? (
            // GPA-only method
            <div className="text-center">
              <div className="text-xs font-medium text-blue-600 mb-1">
                Điểm Trung Bình (GPA)
              </div>
              <div className="text-4xl font-bold text-blue-700">
                {gpa !== null && gpa !== undefined ? gpa.toFixed(2) : "N/A"}
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Thang điểm 10
              </div>
            </div>
          ) : (
            // Subject-based method
            <div className="text-center">
              <div className="text-xs font-medium text-blue-600 mb-1">
                Tổng Điểm Xét Tuyển
                {selectedGroup && (
                  <span className="ml-1 font-semibold">
                    (Khối {selectedGroup})
                  </span>
                )}
              </div>
              <div className="text-4xl font-bold text-blue-700">
                {totalScore !== null && totalScore !== undefined
                  ? totalScore.toFixed(2)
                  : "N/A"}
              </div>
              {averageScore !== null && averageScore !== undefined && (
                <div className="text-xs text-muted-foreground mt-1">
                  Trung bình: {averageScore.toFixed(2)}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Step 3: Academic History */}
        <HealthCheckItem
          label="Lịch sử học tập"
          status={step3Status}
        />

        {/* Step 4: Scores */}
        <HealthCheckItem
          label="Điểm xét tuyển"
          status={step4Status}
          errorCount={scoresErrorCount}
        />
      </CardContent>
    </Card>
  )
}
