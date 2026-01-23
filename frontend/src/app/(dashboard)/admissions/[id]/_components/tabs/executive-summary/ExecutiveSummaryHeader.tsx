/**
 * ExecutiveSummaryHeader Component
 *
 * Section 1: Thông tin định danh & Trạng thái
 * Displays: Name, ID, CCCD, Admission Method, Eligibility Badge, Progress Bar
 */

"use client"

import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { CheckCircle2, AlertCircle } from "lucide-react"
import { getAdmissionMethodLabel } from "@/lib/utils/admission-helpers"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ExecutiveSummaryHeaderProps {
  profile: AdmissionProfileResponse
}

export function ExecutiveSummaryHeader({ profile }: ExecutiveSummaryHeaderProps) {
  const isEligible = profile.eligibility_status === "eligible"
  const methodLabel = getAdmissionMethodLabel(profile.applied_rules)

  return (
    <Card className="border-2 border-primary/20 shadow-sm">
      <CardHeader>
        <div className="flex justify-between items-start gap-4">
          {/* Left: Thông tin cơ bản */}
          <div className="flex-1">
            <CardTitle className="text-2xl mb-3">
              {profile.full_name || "Chưa có tên"}
            </CardTitle>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm text-muted-foreground">
              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground">Mã hồ sơ:</span>
                <span className="font-mono font-semibold text-primary">
                  #{profile.id}
                </span>
              </div>

              <div className="flex items-center gap-2">
                <span className="font-medium text-foreground">CCCD:</span>
                <span className="font-mono">
                  {profile.citizen_id || <span className="text-red-500">Chưa nhập</span>}
                </span>
              </div>

              <div className="flex items-center gap-2 md:col-span-2">
                <span className="font-medium text-foreground">Nguyện vọng:</span>
                <span className="font-semibold text-foreground">{methodLabel}</span>
                {profile.admission_scores?.selected_group && (
                  <Badge variant="outline" className="ml-1">
                    Khối {profile.admission_scores.selected_group}
                  </Badge>
                )}
              </div>
            </div>
          </div>

          {/* Right: Status Badge */}
          <div className="flex-shrink-0">
            {isEligible ? (
              <Badge className="text-base px-5 py-2.5 bg-green-600 hover:bg-green-700">
                <CheckCircle2 className="mr-2 h-5 w-5" />
                Đủ Điều Kiện
              </Badge>
            ) : (
              <Badge
                variant="destructive"
                className="text-base px-5 py-2.5"
              >
                <AlertCircle className="mr-2 h-5 w-5" />
                Không Đủ Điều Kiện
              </Badge>
            )}
          </div>
        </div>

        {/* Progress Bar */}
        <div className="mt-6 pt-6 border-t">
          <div className="flex justify-between items-center text-sm mb-2">
            <span className="font-medium text-foreground">Hoàn thành hồ sơ</span>
            <span className="font-bold text-lg text-primary">
              {profile.completion_percent ?? 0}%
            </span>
          </div>
          <Progress
            value={profile.completion_percent ?? 0}
            className="h-3"
          />
          {profile.completion_percent && profile.completion_percent < 100 && (
            <p className="text-xs text-muted-foreground mt-2">
              Cần hoàn thành thêm {100 - profile.completion_percent}% để nộp hồ sơ
            </p>
          )}
        </div>
      </CardHeader>
    </Card>
  )
}
