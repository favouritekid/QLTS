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
  // Optional: For Manager actions
  onApprove?: () => void
  onReject?: () => void
  isApproving?: boolean
  isRejecting?: boolean
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
  onApprove,
  onReject,
  isApproving = false,
  isRejecting = false,
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
                <Button variant="ghost" size="sm" disabled={isDeleting}>
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

          {/* Step 1-6: Step Navigation Actions */}
          {currentStep < 7 && can('save') && (
            <>
              {/* Back Button - only show if not on step 1 */}
              {currentStep > 1 && (
                <Button variant="outline" onClick={() => onStepChange(currentStep - 1)}>
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Quay lại
                </Button>
              )}

              {/* Save Changes */}
              <Button variant="outline" onClick={onSave} disabled={isSaving}>
                {isSaving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
                Lưu thay đổi
              </Button>

              {/* Next Step Button */}
              <Button onClick={() => onStepChange(currentStep + 1)}>
                Tiếp tục
                <ArrowRight className="w-4 h-4 ml-2" />
              </Button>
            </>
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

          {/* Manager Actions - Only when status = submitted */}
          {profile.status === 'submitted' && (
            <>
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
            </>
          )}

          {/* Enroll - can('enroll') when status = approved */}
          {can('enroll') && (
            <Button onClick={onEnroll} disabled={isEnrolling} className="bg-info-600 hover:bg-info-700">
              {isEnrolling ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <GraduationCap className="w-4 h-4 mr-2" />}
              Xác nhận nhập học
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
