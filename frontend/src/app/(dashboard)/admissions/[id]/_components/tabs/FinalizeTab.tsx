/**
 * FinalizeTab — Decision Surface (Commit 2)
 *
 * Step 8 = decision surface duy nhất. Approve/Reject/Submit/Resubmit
 * render ở đây theo BE permission flags (canApprove/canReject/canSubmit/
 * canResubmit), KHÔNG đoán theo profile.status. Sticky bar
 * (AdmissionActions) chỉ còn navigation + non-decision workflow actions.
 *
 * bypass_warning guard cho approve được bảo toàn qua ApprovalDecisionButton.
 */

"use client"

import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Send, Loader2, XCircle, GraduationCap, ClipboardCheck } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { ExecutiveSummaryHeader } from "./executive-summary/ExecutiveSummaryHeader"
import { HealthCheckGrid } from "./executive-summary/HealthCheckGrid"
import { ReviewDetails } from "./executive-summary/ReviewDetails"
import { ApprovalDecisionButton } from "../ApprovalDecisionButton"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface FinalizeTabProps {
  profile: AdmissionProfileResponse
  isEligible: boolean

  // Submit (officer/applicant — state draft)
  onSubmit: () => void
  isSubmitting: boolean
  canSubmit: boolean

  // Resubmit (officer — state rejected/revision_requested)
  onResubmit?: () => void
  isResubmitting?: boolean
  canResubmit: boolean

  // Approve (manager/admin — state submitted/resubmitted/reviewing)
  onApprove?: () => void
  isApproving?: boolean
  canApprove: boolean

  // Reject (manager/admin — state submitted/resubmitted/reviewing)
  onReject?: () => void
  isRejecting?: boolean
  canReject: boolean

  // Commit 7 — workflow actions di chuyển từ sticky bar vào decision panel.
  // Request revision (manager — yêu cầu officer sửa)
  onRequestRevision?: () => void
  isRequestingRevision?: boolean
  canRequestRevision: boolean

  // Publish result (manager/admin multi-NV — engine cascade)
  onPublishResult?: () => void
  isPublishingResult?: boolean
  canPublishResult: boolean

  // Enroll (manager — state confirmed/overridden post-approval)
  onEnroll?: () => void
  isEnrolling?: boolean
  canEnroll: boolean

  // Commit 4 fix-up — pass-through cho ReviewDetails → UtEvidenceCards
  // "Mở tab Giấy tờ để upload" CTA khi thiếu minh chứng UT.
  onNavigateToDocuments: () => void
}

export function FinalizeTab({
  profile,
  isEligible,
  onSubmit,
  isSubmitting,
  canSubmit,
  onResubmit,
  isResubmitting = false,
  canResubmit,
  onApprove,
  isApproving = false,
  canApprove,
  onReject,
  isRejecting = false,
  canReject,
  onRequestRevision,
  isRequestingRevision = false,
  canRequestRevision,
  onPublishResult,
  isPublishingResult = false,
  canPublishResult,
  onEnroll,
  isEnrolling = false,
  canEnroll,
  onNavigateToDocuments,
}: FinalizeTabProps) {
  const hasDecisionAction =
    canSubmit ||
    canResubmit ||
    canApprove ||
    canReject ||
    canRequestRevision ||
    canPublishResult ||
    canEnroll

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-8">
      <ExecutiveSummaryHeader profile={profile} />
      <HealthCheckGrid profile={profile} />
      <ReviewDetails profile={profile} onNavigateToDocuments={onNavigateToDocuments} />

      {hasDecisionAction && (
        <Card className="p-6 bg-gradient-to-br from-gray-50 to-white lg:sticky lg:bottom-4 lg:z-30 lg:shadow-lg">
          <div className="flex flex-col sm:flex-row justify-center items-center gap-4 flex-wrap">
            {canRequestRevision && onRequestRevision && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    size="lg"
                    variant="outline"
                    disabled={isRequestingRevision || isApproving || isRejecting}
                    className="w-full sm:w-auto min-w-[160px]"
                  >
                    {isRequestingRevision ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                    ) : (
                      <ClipboardCheck className="w-4 h-4 mr-2" aria-hidden="true" />
                    )}
                    Yêu cầu sửa
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Yêu cầu sửa hồ sơ?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Hồ sơ sẽ chuyển sang trạng thái <strong>Cần sửa</strong>. Officer
                      phụ trách sẽ nhận thông báo và có thể chỉnh sửa rồi nộp lại.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Hủy</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={(e) => {
                        e.preventDefault()
                        onRequestRevision?.()
                      }}
                    >
                      Yêu cầu sửa
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}

            {canReject && onReject && (
              <Button
                size="lg"
                variant="outline"
                disabled={isRejecting || isApproving}
                onClick={onReject}
                className="w-full sm:w-auto min-w-[160px]"
              >
                {isRejecting ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                    Đang xử lý…
                  </>
                ) : (
                  <>
                    <XCircle className="w-4 h-4 mr-2" aria-hidden="true" />
                    Từ chối hồ sơ
                  </>
                )}
              </Button>
            )}

            {canApprove && onApprove && (
              <ApprovalDecisionButton
                profile={profile}
                onApprove={onApprove}
                isApproving={isApproving}
                disabled={(!isEligible && !profile.bypass_warning) || isRejecting}
                size="lg"
                // Layout-only — màu success/warning do component tự compose
                // theo profile.bypass_warning (KHÔNG override để tránh mất
                // risk signal warning khi bypass_warning=true).
                className="w-full sm:w-auto min-w-[200px]"
              />
            )}

            {canPublishResult && onPublishResult && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    size="lg"
                    disabled={isPublishingResult}
                    className="w-full sm:w-auto min-w-[200px] bg-success-600 hover:bg-success-700"
                  >
                    {isPublishingResult ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                    ) : (
                      <GraduationCap className="w-4 h-4 mr-2" aria-hidden="true" />
                    )}
                    Công bố kết quả
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Công bố kết quả xét tuyển?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Hệ thống sẽ chạy <strong>engine xét tuần tự các nguyện vọng</strong>
                      {" "}theo thứ tự ưu tiên. Mỗi NV sẽ có quyết định riêng:
                      {" "}<strong>Đậu</strong> / <strong>Trượt</strong> / <strong>Bị bỏ qua</strong>
                      {" "}/ <strong>Dự bị</strong>. Hành động không thể hoàn tác (chỉ admin có thể rollback về Nháp).
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Hủy</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={(e) => {
                        e.preventDefault()
                        onPublishResult?.()
                      }}
                      className="bg-success-600 hover:bg-success-700"
                    >
                      Công bố kết quả
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}

            {canEnroll && onEnroll && (
              <Button
                size="lg"
                onClick={onEnroll}
                disabled={isEnrolling}
                className="w-full sm:w-auto min-w-[200px] bg-info-600 hover:bg-info-700"
              >
                {isEnrolling ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                ) : (
                  <GraduationCap className="w-4 h-4 mr-2" aria-hidden="true" />
                )}
                Ghi danh
              </Button>
            )}

            {canSubmit && (
              <Button
                size="lg"
                disabled={!isEligible || isSubmitting}
                onClick={onSubmit}
                className="w-full sm:w-auto min-w-[200px]"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                    Đang xử lý…
                  </>
                ) : (
                  <>
                    <Send className="w-4 h-4 mr-2" aria-hidden="true" />
                    Nộp hồ sơ chính thức
                  </>
                )}
              </Button>
            )}

            {canResubmit && onResubmit && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="lg" disabled={isResubmitting} className="w-full sm:w-auto min-w-[200px]">
                    {isResubmitting ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                    ) : (
                      <Send className="w-4 h-4 mr-2" aria-hidden="true" />
                    )}
                    Nộp lại hồ sơ
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Nộp lại hồ sơ?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Hồ sơ đã bị từ chối trước đó. Sau khi nộp lại, hồ sơ sẽ
                      được chuyển sang trạng thái chờ duyệt.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Hủy</AlertDialogCancel>
                    <AlertDialogAction onClick={onResubmit}>
                      Nộp lại
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>

          {(canSubmit || canApprove) && !isEligible && !profile.bypass_warning && (
            <p className="text-center text-sm text-muted-foreground mt-4">
              Hồ sơ chưa đủ điều kiện. Vui lòng xem danh sách &ldquo;Vấn đề cần
              sửa&rdquo; ở panel bên cạnh (desktop) hoặc nút &ldquo;N vấn
              đề&rdquo; (mobile).
            </p>
          )}
        </Card>
      )}
    </div>
  )
}
