"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { FileText, CheckCircle2, Clock, AlertTriangle } from "lucide-react"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface DocumentReviewCardProps {
  profile: AdmissionProfileResponse
}

/**
 * Cockpit card cho § tài liệu. BE-driven: document_stats + UT priority
 * evidence từ priority_evidence_documents + missing codes.
 */
export function DocumentReviewCard({ profile }: DocumentReviewCardProps) {
  const stats = profile.document_stats ?? null
  const verifiedCount = stats?.verified_count ?? 0
  const submittedCount = stats?.submitted_count ?? 0
  const mandatoryCount = stats?.mandatory_count ?? 0
  const missingCount = stats?.missing_count ?? 0

  const utEvidence = profile.priority_evidence_documents ?? []
  const utVerifiedCount = utEvidence.filter((d) => d.status === "verified").length
  const missingUtCount = profile.missing_priority_evidence_codes?.length ?? 0

  // Path không bắt buộc tài liệu + không thiếu UT → coi như đủ điều kiện
  // ("không có gì để duyệt"). Tránh false-error icon đỏ.
  const noMandatoryRequired = mandatoryCount === 0
  const isComplete =
    (noMandatoryRequired || verifiedCount === mandatoryCount) &&
    missingUtCount === 0
  const hasPending = submittedCount < mandatoryCount || missingUtCount > 0
  const StatusIcon = isComplete ? CheckCircle2 : hasPending ? Clock : AlertTriangle
  const statusColor = isComplete
    ? "text-success-600"
    : hasPending
      ? "text-warning-600"
      : "text-error-600"

  return (
    <Card data-testid="document-review-card">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-muted-foreground" />
            <CardTitle className="text-lg">Tài liệu</CardTitle>
          </div>
          <StatusIcon className={`w-6 h-6 ${statusColor}`} />
        </div>
      </CardHeader>

      <CardContent className="space-y-2 text-sm">
        <div className="flex justify-between items-baseline">
          <span className="text-muted-foreground">Bắt buộc đã duyệt:</span>
          <span className="font-semibold tabular-nums">
            {verifiedCount}/{mandatoryCount}
          </span>
        </div>
        <div className="flex justify-between items-baseline text-xs text-muted-foreground">
          <span>Đã nộp:</span>
          <span className="tabular-nums">{submittedCount}</span>
        </div>
        {utEvidence.length > 0 && (
          <div className="flex justify-between items-baseline">
            <span className="text-muted-foreground">Minh chứng UT đã duyệt:</span>
            <span className="font-semibold tabular-nums">
              {utVerifiedCount}/{utEvidence.length}
            </span>
          </div>
        )}
        {missingCount > 0 && (
          <Badge variant="outline" className="bg-error-50 border-error-200 text-error-700 text-xs">
            Thiếu {missingCount} tài liệu bắt buộc
          </Badge>
        )}
        {missingUtCount > 0 && (
          <Badge variant="outline" className="bg-warning-50 border-warning-200 text-warning-700 text-xs">
            Thiếu {missingUtCount} minh chứng UT
          </Badge>
        )}
      </CardContent>
    </Card>
  )
}
