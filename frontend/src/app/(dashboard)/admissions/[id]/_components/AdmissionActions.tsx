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
import { Loader2, Save, Send, GraduationCap, ClipboardCheck, Lock, CheckCircle, XCircle, Trash } from "lucide-react"
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
  isSaving: boolean
  isSubmitting: boolean
  isEnrolling: boolean
  onSave: () => void
  onSubmit: () => void
  onEnroll: () => void
  onCheckCondition?: () => void
  // Optional: For Manager actions
  onApprove?: () => void
  isApproving?: boolean
  isRejecting?: boolean
  // Delete action
  onDelete?: () => void
  isDeleting?: boolean
}

export function AdmissionActions({
  profile,
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
    <div className="fixed bottom-0 left-0 lg:left-64 right-0 border-t bg-background p-4 z-40 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.1)]">
      <div className="container max-w-7xl mx-auto flex items-center justify-between">
        {/* Status Badge */}
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-muted-foreground hidden sm:inline-block">
            Trạng thái: 
          </span>
          <StatusBadge status={profile.status} config={statusConfig} />
        </div>

        {/* Action Buttons - Permission Controlled */}
        <div className="flex items-center gap-3">
           {/* DELETE - can('delete') - Critical Action */}
           {can('delete') && onDelete && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" disabled={isDeleting}>
                  {isDeleting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Trash className="w-4 h-4 mr-2" />}
                  Xóa
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

          {/* Save Draft - can('save') */}
          {can('save') && (
            <Button variant="outline" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
              Lưu nháp
            </Button>
          )}
          
          {/* Check Condition - can('submit') */}
          {can('submit') && (
            <Button variant="secondary" onClick={onCheckCondition}>
              <ClipboardCheck className="w-4 h-4 mr-2" />
              Kiểm tra điều kiện
            </Button>
          )}

          {/* Submit - can('submit') && isEligible */}
          {can('submit') && (
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
          )}

          {/* Approve - can('approve') - Manager only */}
          {can('approve') && onApprove && (
            <Button 
              onClick={onApprove} 
              disabled={isApproving}
              className="bg-green-600 hover:bg-green-700"
            >
              {isApproving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <CheckCircle className="w-4 h-4 mr-2" />}
              Phê duyệt
            </Button>
          )}

          {/* Reject - can('reject') - Manager only */}
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

          {/* Enroll - can('enroll') */}
          {can('enroll') && (
            <Button onClick={onEnroll} disabled={isEnrolling} className="bg-blue-600 hover:bg-blue-700">
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
  status: string
  config: ReturnType<typeof getStatusConfig>
}

function StatusBadge({ status, config }: StatusBadgeProps) {
  return <Badge className={config.badgeColor}>{config.label}</Badge>
}
