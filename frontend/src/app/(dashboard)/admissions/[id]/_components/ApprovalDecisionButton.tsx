"use client"

import { Button } from "@/components/ui/button"
import { CheckCircle, Loader2 } from "lucide-react"
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
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface ApprovalDecisionButtonProps {
  profile: AdmissionProfileResponse
  onApprove: () => void
  isApproving: boolean
  disabled?: boolean
  size?: "default" | "sm" | "lg"
  /**
   * Layout-only className (width/size/min-width).
   * Màu nền (success vs warning) do component tự compose theo
   * `profile.bypass_warning` — caller KHÔNG override để tránh mất risk
   * signal khi bypass_warning=true.
   */
  className?: string
}

/**
 * Approve button với bypass_warning guard.
 *
 * Khi `profile.bypass_warning === true` (BE flag = đợt cho phép nộp hồ
 * sơ chưa đầy đủ + status reviewable + eligibility_status=ineligible),
 * Approve được wrap trong AlertDialog liệt kê `validation_errors` để
 * manager/admin nhận biết hồ sơ thiếu trường (e.g. tên ứng viên, CCCD)
 * trước khi quyết định "Vẫn phê duyệt". Không có guard → silent approve
 * → student row tạo với dữ liệu NULL.
 *
 * Khi `bypass_warning === false`, render plain Button.
 */
export function ApprovalDecisionButton({
  profile,
  onApprove,
  isApproving,
  disabled = false,
  size = "default",
  className,
}: ApprovalDecisionButtonProps) {
  if (profile.bypass_warning) {
    return (
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            size={size}
            disabled={isApproving || disabled}
            className={cn(className, "bg-warning-600 hover:bg-warning-700")}
          >
            {isApproving ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <CheckCircle className="w-4 h-4 mr-2" />
            )}
            Phê duyệt (vượt điều kiện)
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>⚠️ Hồ sơ chưa đủ điều kiện</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                <p>
                  Đợt tuyển sinh này cho phép nộp hồ sơ chưa đầy đủ
                  (<code>allow_unverified_submission=true</code>), nhưng hồ sơ
                  hiện có{" "}
                  <strong>{profile.validation_errors?.length ?? 0} lỗi</strong>
                  {" "}chưa khắc phục:
                </p>
                {profile.validation_errors && profile.validation_errors.length > 0 && (
                  <ul className="list-disc pl-5 text-sm max-h-40 overflow-y-auto">
                    {profile.validation_errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                )}
                <p className="text-warning-800 font-medium">
                  Phê duyệt sẽ tạo hồ sơ vào hệ thống với dữ liệu thiếu
                  (ví dụ: tên ứng viên, ngày sinh, CCCD…). Bạn có chắc?
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Để tôi xem lại</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => { e.preventDefault(); onApprove(); }}
              className="bg-warning-600 hover:bg-warning-700"
            >
              Vẫn phê duyệt
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  return (
    <Button
      size={size}
      onClick={onApprove}
      disabled={isApproving || disabled}
      className={cn(className, "bg-success-600 hover:bg-success-700")}
    >
      {isApproving ? (
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
      ) : (
        <CheckCircle className="w-4 h-4 mr-2" />
      )}
      Phê duyệt
    </Button>
  )
}
