/**
 * AdminCard Component
 *
 * Health Check Grid - Khối 3: Thủ Tục & Tài Chính
 * Displays: Document Summary + Step 5 (Documents) + Step 6 (Tuition)
 */

"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { FileText, CheckCircle2, Clock, AlertTriangle } from "lucide-react"
import { HealthCheckItem } from "./HealthCheckItem"
import {
  getVerifiedDocsCount,
  getMandatoryDocsCount,
  getMissingDocsCount,
} from "@/lib/utils/admission-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface AdminCardProps {
  profile: AdmissionProfileResponse
}

export function AdminCard({ profile }: AdminCardProps) {
  const step5Status = profile.step_status?.["5"] ?? "locked"
  const step6Status = profile.step_status?.["6"] ?? "locked"

  // Check if admin section is complete
  const isComplete = step5Status === "success" && step6Status === "success"
  const hasPending = step5Status === "warning" || step6Status === "warning"

  // Get error counts from grouped validation errors
  const documentsErrorCount = profile.grouped_validation_errors?.documents?.count ?? 0

  // Document counts
  // Fix: Show "Submitted" instead of "Verified" for main counter to avoid "0/12" panic
  const submittedCount = (profile.documents_checklist ?? []).filter(
    doc => doc.is_mandatory && ["uploaded", "verified", "paper_submitted"].includes(doc.status)
  ).length
  
  const verifiedCount = getVerifiedDocsCount(profile.documents_checklist ?? [])
  const mandatoryCount = getMandatoryDocsCount(profile.documents_checklist ?? [])
  const missingCount = getMissingDocsCount(profile.documents_checklist ?? [])

  // Status icon for the whole card
  const StatusIcon = isComplete
    ? CheckCircle2
    : hasPending
    ? Clock
    : AlertTriangle

  const statusColor = isComplete
    ? "text-green-600"
    : hasPending
    ? "text-amber-600"
    : "text-red-600"

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-muted-foreground" />
            <CardTitle className="text-lg">Thủ Tục & Tài Chính</CardTitle>
          </div>
          <StatusIcon className={`w-6 h-6 ${statusColor}`} />
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Documents Summary */}
        <div 
          className={`rounded-lg p-3.5 border ${ 
            verifiedCount === mandatoryCount && mandatoryCount > 0
              ? "bg-gradient-to-br from-green-50 to-green-100 border-green-200"
              : "bg-gradient-to-br from-amber-50 to-amber-100 border-amber-200"
          }`}
        >
          <div className="flex justify-between items-center text-sm mb-1">
            <span 
              className={`font-medium ${
                verifiedCount === mandatoryCount && mandatoryCount > 0
                  ? "text-green-900"
                  : "text-amber-900"
              }`}
            >
              Tài liệu đã nộp / Bắt buộc
            </span>
            <span 
              className={`font-bold text-lg ${
                verifiedCount === mandatoryCount && mandatoryCount > 0
                  ? "text-green-700"
                  : "text-amber-700"
              }`}
            >
              {submittedCount} / {mandatoryCount}
            </span>
          </div>

          {missingCount > 0 && (
            <div className="text-xs text-red-600 font-medium">
              Còn thiếu: {missingCount} tài liệu
            </div>
          )}

          {missingCount === 0 && verifiedCount < mandatoryCount && (
            <div className="text-xs text-amber-700 font-medium">
              Đã nộp đủ, chờ xác nhận ({verifiedCount}/{mandatoryCount} đã duyệt)
            </div>
          )}

          {verifiedCount === mandatoryCount && mandatoryCount > 0 && (
            <div className="text-xs text-green-700 font-medium flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              Đã xác nhận đầy đủ
            </div>
          )}
        </div>

        {/* Step 5: Documents */}
        <HealthCheckItem
          label="Tài liệu pháp lý"
          status={step5Status}
          errorCount={documentsErrorCount}
        />

        {/* Step 6: Tuition */}
        <HealthCheckItem
          label="Học phí"
          status={step6Status}
        />
      </CardContent>
    </Card>
  )
}
