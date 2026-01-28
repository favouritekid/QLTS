/**
 * LegalDocsCard Component
 *
 * Health Check Grid - Khối 1: Hồ Sơ Pháp Lý
 * Displays: Step 1 (Personal Info) + Step 2 (Family)
 */

"use client"

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { User, CheckCircle2, AlertTriangle, AlertCircle } from "lucide-react"
import { HealthCheckItem } from "./HealthCheckItem"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface LegalDocsCardProps {
  profile: AdmissionProfileResponse
}

export function LegalDocsCard({ profile }: LegalDocsCardProps) {
  const step1Status = profile.step_status?.["1"] ?? "locked"
  const step2Status = profile.step_status?.["2"] ?? "locked"

  // Check if legal docs section is complete
  const isComplete = step1Status === "success" && step2Status === "success"
  const hasWarning = step1Status === "warning" || step2Status === "warning"

  // Get error counts from grouped validation errors
  const personalErrorCount = profile.grouped_validation_errors?.personal_info?.count ?? 0

  // Status icon for the whole card
  const StatusIcon = isComplete
    ? CheckCircle2
    : hasWarning
    ? AlertTriangle
    : AlertCircle

  const statusColor = isComplete
    ? "text-success-600"
    : hasWarning
    ? "text-warning-600"
    : "text-error-600"

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <User className="w-5 h-5 text-muted-foreground" />
            <CardTitle className="text-lg">Hồ Sơ Pháp Lý</CardTitle>
          </div>
          <StatusIcon className={`w-6 h-6 ${statusColor}`} />
        </div>
      </CardHeader>

      <CardContent className="space-y-2">
        {/* Step 1: Personal Info */}
        <HealthCheckItem
          label="Thông tin cá nhân"
          status={step1Status}
          errorCount={personalErrorCount}
        />

        {/* Step 2: Family */}
        <HealthCheckItem
          label="Gia đình / Giám hộ"
          status={step2Status}
        />

        {/* Warning Alert for optional fields */}
        {step1Status === "warning" && (
          <Alert variant="default" className="bg-warning-50 border-warning-200 mt-3">
            <AlertCircle className="h-4 w-4 text-warning-600" />
            <AlertDescription className="text-sm text-warning-800">
              Một số trường không bắt buộc chưa điền (Email, Nơi sinh, ...)
            </AlertDescription>
          </Alert>
        )}

        {step2Status === "warning" && (
          <Alert variant="default" className="bg-warning-50 border-warning-200 mt-3">
            <AlertCircle className="h-4 w-4 text-warning-600" />
            <AlertDescription className="text-sm text-warning-800">
              Chưa có thông tin gia đình hoặc người giám hộ
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  )
}
