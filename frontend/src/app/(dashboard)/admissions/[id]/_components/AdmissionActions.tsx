"use client"

/**
 * Phase 7: Permission-Based Rendering (ADR-FE-002)
 * 
 * Button visibility is now controlled by backend permissions via can() pattern.
 * - ❌ FORBIDDEN: {isDraft && <Button />}
 * - ✅ REQUIRED: {can('submit') && <Button />}
 */

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, Save, Send, GraduationCap, ClipboardCheck, Lock, CheckCircle, XCircle, Trash, ArrowRight, ArrowLeft } from "lucide-react"
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
import { cn } from "@/lib/utils"
import { usePermissions } from "@/hooks/usePermissions"
import { getStatusConfig } from "@/lib/status-config"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"
import { SendConfirmationButton } from "./SendConfirmationButton"

interface AdmissionActionsProps {
  profile: AdmissionProfileResponse
  currentStep: number
  onStepChange: (step: number) => void
  isSaving: boolean
  isSubmitting: boolean
  isEnrolling: boolean
  onSave: () => void
  onSubmit: () => void
  onEnroll: () => void
  onCheckCondition?: () => void
  // Resubmit action (officer - rejected profiles)
  onResubmit?: () => void
  isResubmitting?: boolean
  // Optional: For Manager actions
  onApprove?: () => void
  onReject?: () => void
  isApproving?: boolean
  isRejecting?: boolean
  // Claim/unclaim actions
  onClaim?: () => void
  onUnclaim?: () => void
  isClaiming?: boolean
  isUnclaiming?: boolean
  // Delete action
  onDelete?: () => void
  isDeleting?: boolean
}

export function AdmissionActions({
  profile,
  currentStep,
  onStepChange,
  isSaving,
  isSubmitting,
  isEnrolling,
  onSave,
  onSubmit,
  onEnroll,
  onCheckCondition,
  onResubmit,
  isResubmitting = false,
  onApprove,
  onReject,
  isApproving = false,
  isRejecting = false,
  onClaim,
  onUnclaim,
  isClaiming = false,
  isUnclaiming = false,
  onDelete,
  isDeleting = false,
}: AdmissionActionsProps) {
  // =========================================================================
  // Phase 7: Permission-Based Button Visibility
  // =========================================================================
  const { can } = usePermissions(profile)
  const statusConfig = getStatusConfig(profile.status)
  
  // Check eligibility from backend (not local calculation)
  const isEligible = profile.eligibility_status === 'eligible'
  
  return (
    <div className="fixed bottom-0 left-0 right-0 border-t bg-background z-40 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.1)]">
      <div className="container max-w-7xl mx-auto h-16 px-6 flex items-center justify-between">
        {/* Status Badge */}
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-muted-foreground hidden sm:inline-block">
            Trạng thái:
          </span>
          <StatusBadge config={statusConfig} />
        </div>

        {/* Action Buttons - Phase 2: Context-Based */}
        <div className="flex items-center gap-3">
          {/* DELETE - Always available if can('delete') */}
          {can('delete') && onDelete && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="sm" disabled={isDeleting} aria-label="Xóa hồ sơ">
                  {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash className="w-4 h-4" />}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Bạn có chắc chắn muốn xóa hồ sơ này?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Hành động này không thể hoàn tác. Hồ sơ tuyển sinh sẽ bị xóa vĩnh viễn khỏi hệ thống.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                  <AlertDialogAction onClick={onDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    Xóa hồ sơ
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {/* Back Button - always available for steps 2-6, independent of save permission */}
          {currentStep > 1 && currentStep < 7 && (
            <Button variant="outline" onClick={() => onStepChange(currentStep - 1)}>
              <ArrowLeft className="w-4 h-4 mr-2" />
              Quay lại
            </Button>
          )}

          {/* Save Changes - only when profile is editable */}
          {currentStep < 7 && can('save') && (
            <Button variant="outline" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Lưu thay đổi
            </Button>
          )}

          {/* Next Step Button - always available for steps 1-6, independent of save permission */}
          {currentStep < 7 && (
            <Button onClick={() => onStepChange(currentStep + 1)}>
              Tiếp tục
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          )}

          {/* Step 7 Only: Submit Actions */}
          {currentStep === 7 && can('submit') && (
            <>
              {/* Check Condition */}
              <Button variant="outline" onClick={onCheckCondition}>
                <ClipboardCheck className="w-4 h-4 mr-2" />
                Kiểm tra toàn bộ
              </Button>

              {/* Submit */}
              <Button
                onClick={onSubmit}
                disabled={isSubmitting || !isEligible}
                className={cn(!isEligible && "opacity-80")}
              >
                {isSubmitting ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : !isEligible ? (
                  <Lock className="w-4 h-4 mr-2" />
                ) : (
                  <Send className="w-4 h-4 mr-2" />
                )}
                Nộp hồ sơ
              </Button>
            </>
          )}

          {/* Resubmit - Officer action for rejected profiles */}
          {can('resubmit') && onResubmit && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button disabled={isResubmitting}>
                  {isResubmitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Send className="w-4 h-4 mr-2" />}
                  Nộp lại hồ sơ
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Nộp lại hồ sơ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Hồ sơ đã bị từ chối trước đó. Sau khi nộp lại, hồ sơ sẽ được chuyển sang trạng thái chờ duyệt.
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

          {/* Manager Actions - Permission-based (ADR-FE-002) */}
          {can('approve') && onApprove && (
            <Button
              onClick={onApprove}
              disabled={isApproving}
              className="bg-success-600 hover:bg-success-700"
            >
              {isApproving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <CheckCircle className="w-4 h-4 mr-2" />}
              Phê duyệt
            </Button>
          )}

          {can('reject') && onReject && (
            <Button
              onClick={onReject}
              disabled={isRejecting}
              variant="destructive"
            >
              {isRejecting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <XCircle className="w-4 h-4 mr-2" />}
              Từ chối
            </Button>
          )}

          {/* Claim/Unclaim Actions */}
          {can('claim') && onClaim && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" disabled={isClaiming}>
                  {isClaiming ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <ClipboardCheck className="w-4 h-4 mr-2" />}
                  Nhận duyệt
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Nhận duyệt hồ sơ?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Bạn sẽ được gán là người duyệt hồ sơ này. Bạn có thể bỏ nhận bất cứ lúc nào.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                  <AlertDialogAction onClick={onClaim}>
                    Nhận duyệt
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {can('unclaim') && onUnclaim && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" disabled={isUnclaiming}>
                  {isUnclaiming ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <XCircle className="w-4 h-4 mr-2" />}
                  Bỏ nhận
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Bỏ nhận duyệt?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Bạn sẽ không còn là người duyệt hồ sơ này. Manager khác có thể nhận duyệt.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Hủy</AlertDialogCancel>
                  <AlertDialogAction onClick={onUnclaim}>
                    Bỏ nhận
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {/* Send magic-link — visible on approved. Lets officers regenerate/
              resend the confirm link and grab a copy-able URL for Zalo/SMS
              when the applicant has no email on file. See
              project_send_confirmation_ops_gaps. */}
          {profile.status === "approved" && can('enroll') && (
            <SendConfirmationButton profileId={profile.id} />
          )}

          {/* Enroll - can('enroll') when status ∈ {approved, confirmed, overridden}.
              Label is "Ghi danh" (not "Xác nhận nhập học") so officers don't
              confuse it with the applicant-facing "xác nhận" magic-link step. */}
          {can('enroll') && (
            <Button onClick={onEnroll} disabled={isEnrolling} className="bg-info-600 hover:bg-info-700">
              {isEnrolling ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <GraduationCap className="w-4 h-4 mr-2" />}
              Ghi danh
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * StatusBadge - Uses status-config for consistent styling
 */
interface StatusBadgeProps {
  config: ReturnType<typeof getStatusConfig>
}

function StatusBadge({ config }: StatusBadgeProps) {
  return <Badge className={config.badgeColor}>{config.label}</Badge>
}
