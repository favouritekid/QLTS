"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useCancelReviewSession } from "@/lib/hooks/use-review-sessions"
import {
  CANCEL_CONFIRM_TEXT,
  CANCEL_DONE,
  CANCEL_REASON_HINT,
  CANCEL_REASON_INVALID,
  CANCEL_STALE,
  describeReviewSessionError,
} from "@/lib/review-sessions/messages"
import { CANCEL_REASON_MAX_LENGTH, codePointLength } from "@/lib/zod/review-sessions"

import { ReviewErrorAlert } from "./ReviewErrorAlert"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  sessionId: number
  /** `version` của E3 MỚI NHẤT đang xem — gửi kèm (phiên bản lạc quan, HĐ4 §1.5) */
  version: number
  seqNo: number
  academicYear: number
  /** E3 đang tải lại ⇒ khoá nút (thao tác kế phải dùng `version` mới) */
  busy: boolean
}

/**
 * Câu lỗi của E5 (thiết kế §3.8): 409 STALE ⇒ câu riêng (giữ lý do, E3 đã được tải lại); 422 ⇒ câu lý do; còn lại theo bảng
 * chung §5 (mất kết nối ⇒ "chưa rõ đã ghi"; đóng băng; 500 `REVIEW_ISOLATION_UNSUPPORTED` ⇒ câu máy chủ). Rẽ nhánh theo MÃ.
 */
function cancelErrorText(error: unknown): string {
  const v = describeReviewSessionError(error, "write")
  if (v.errorCode === "REVIEW_SESSION_STALE") return CANCEL_STALE
  if (v.kind === "invalid") return CANCEL_REASON_INVALID
  return v.message
}

/**
 * M7 — huỷ lần xét (E5). Chỉ mở được khi máy chủ trả `cancel` trong `available_actions` (màn cha quyết). Lý do bắt buộc: đếm sau
 * khi cắt khoảng trắng, 1–1000 KÝ TỰ (kiểm DẠNG để khoá nút; máy chủ là chốt). Làm mới E2 / E3 / E7 / E8 do hook lo, khi thao tác
 * kết thúc bất kể kết quả.
 *  - 409 `REVIEW_SESSION_STALE` ⇒ GIỮ lý do đã gõ, hộp vẫn mở; bấm lại sẽ gửi `version` mới.
 *  - 409 `REVIEW_SESSION_NOT_DRAFT` ⇒ đóng hộp, báo câu máy chủ (lần xét có thể đã huỷ ở nơi khác).
 *  - Mất kết nối ⇒ "chưa rõ đã ghi"; E3 tải lại cho biết — đã huỷ thì máy chủ thôi trả `cancel` và hộp tự đóng.
 */
export function CancelReviewSessionDialog({ open, onOpenChange, sessionId, version, seqNo, academicYear, busy }: Props) {
  const cancel = useCancelReviewSession(sessionId)
  const [reason, setReason] = useState("")
  const length = codePointLength(reason.trim())
  const reasonOk = length >= 1 && length <= CANCEL_REASON_MAX_LENGTH
  const canSubmit = reasonOk && !cancel.isPending && !busy

  const close = () => {
    cancel.reset()
    onOpenChange(false)
  }

  const submit = () => {
    cancel.mutate(
      { version, reason: reason.trim() },
      {
        onSuccess: () => {
          setReason("")
          close()
          toast.success(CANCEL_DONE)
        },
        onError: (error) => {
          const v = describeReviewSessionError(error, "write")
          if (v.errorCode === "REVIEW_SESSION_NOT_DRAFT") {
            close()
            toast.error(v.message)
          }
        },
      },
    )
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(o) => {
        if (cancel.isPending) return
        if (o) onOpenChange(true)
        else close()
      }}
    >
      <AlertDialogContent data-testid="hop-huy-lan-xet">
        <AlertDialogHeader>
          <AlertDialogTitle>
            Huỷ lần xét số {seqNo} năm {academicYear}?
          </AlertDialogTitle>
          <AlertDialogDescription>{CANCEL_CONFIRM_TEXT}</AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-1">
          <Label htmlFor="huy-ly-do">Lý do (bắt buộc)</Label>
          <Textarea
            id="huy-ly-do"
            data-testid="huy-ly-do"
            value={reason}
            disabled={cancel.isPending}
            onChange={(e) => setReason(e.target.value)}
          />
          <p className="text-xs text-muted-foreground" data-testid="huy-ly-do-dem">
            {CANCEL_REASON_HINT} ({length}/{CANCEL_REASON_MAX_LENGTH})
          </p>
        </div>

        {cancel.error ? <ReviewErrorAlert testId="huy-loi" message={cancelErrorText(cancel.error)} /> : null}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={cancel.isPending}>Đóng</AlertDialogCancel>
          <Button variant="destructive" disabled={!canSubmit} onClick={submit} data-testid="huy-xac-nhan">
            {cancel.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Huỷ lần xét
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
