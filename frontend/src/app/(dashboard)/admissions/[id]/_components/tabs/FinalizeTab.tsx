/**
 * FinalizeTab Component - Executive Summary
 *
 * Step 7: Final Review transformed into Executive Summary
 * Allows Manager/Admin to review entire profile in one screen
 */

"use client"

import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Send, Loader2, XCircle } from "lucide-react"
import { ExecutiveSummaryHeader } from "./executive-summary/ExecutiveSummaryHeader"
import { HealthCheckGrid } from "./executive-summary/HealthCheckGrid"
import { ReviewDetails } from "./executive-summary/ReviewDetails"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface FinalizeTabProps {
  profile: AdmissionProfileResponse
  isEligible: boolean
  onSubmit: () => void
  isSubmitting: boolean
  canApprove: boolean
}

export function FinalizeTab({
  profile,
  isEligible,
  onSubmit,
  isSubmitting,
  canApprove,
}: FinalizeTabProps) {
  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-8">
      {/* Section 1: Header - Thông tin định danh & Trạng thái */}
      <ExecutiveSummaryHeader profile={profile} />

      {/* Section 2: Health Check Grid - Lưới kiểm tra nhanh */}
      <HealthCheckGrid profile={profile} />

      {/* Section 3: Chi tiết xét duyệt (Expandable) */}
      <ReviewDetails profile={profile} />

      {/* Action Buttons - Only for Manager/Admin */}
      {canApprove && (
        <Card className="p-6 bg-gradient-to-br from-gray-50 to-white">
          <div className="flex flex-col sm:flex-row justify-center items-center gap-4">
            <Button
              size="lg"
              variant="outline"
              disabled={isSubmitting}
              className="w-full sm:w-auto min-w-[160px]"
            >
              <XCircle className="w-4 h-4 mr-2" />
              Từ chối hồ sơ
            </Button>

            <Button
              size="lg"
              disabled={!isEligible || isSubmitting}
              onClick={onSubmit}
              className="w-full sm:w-auto min-w-[200px]"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Đang xử lý...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4 mr-2" />
                  Phê duyệt hồ sơ
                </>
              )}
            </Button>
          </div>

          {!isEligible && (
            <p className="text-center text-sm text-muted-foreground mt-4">
              Hồ sơ chưa đủ điều kiện. Vui lòng kiểm tra các vấn đề cần sửa ở sidebar.
            </p>
          )}
        </Card>
      )}

      {/* For non-approvers (Officers, Students) - show submit button only */}
      {!canApprove && (
        <Card className="p-6 text-center">
          <Button
            size="lg"
            disabled={!isEligible || isSubmitting}
            onClick={onSubmit}
            className="min-w-[200px]"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Đang xử lý...
              </>
            ) : (
              <>
                <Send className="w-4 h-4 mr-2" />
                Nộp hồ sơ chính thức
              </>
            )}
          </Button>

          {!isEligible && (
            <p className="text-sm text-muted-foreground mt-4">
              Hồ sơ chưa đủ điều kiện. Vui lòng hoàn thành các bước trước.
            </p>
          )}
        </Card>
      )}
    </div>
  )
}
