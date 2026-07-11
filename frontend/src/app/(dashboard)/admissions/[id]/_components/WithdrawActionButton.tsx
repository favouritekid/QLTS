// src/app/(dashboard)/admissions/[id]/_components/WithdrawActionButton.tsx
"use client"

import { useState } from "react"
import { Loader2, LogOut, RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  useWithdrawAdmission,
  useCancelWithdrawal,
} from "@/hooks/admissions/useAdmissions"

/**
 * PR-B — direct withdraw / cancel-withdrawal actions.
 *
 * Owner-chosen flow: the candidate comes to the school and the officer withdraws
 * the profile ON THE SPOT (no magic-link). ``mode="withdraw"`` opens a reason
 * dialog → POST /withdraw (officer/manager/admin, gated by ``send_withdraw_link``
 * upstream). ``mode="cancel"`` reverts a ``withdrawal_pending`` profile back to
 * draft → POST /cancel-withdrawal (admin only, gated by ``cancel_withdrawal``).
 *
 * Thin-client: the parent gates visibility via BE permission flags before
 * mounting this — the component itself does not check roles.
 */
interface Props {
  profileId: number
  version: number
  mode: "withdraw" | "cancel"
}

const MIN_REASON = 5

export function WithdrawActionButton({ profileId, version, mode }: Props) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState("")

  const withdraw = useWithdrawAdmission(profileId)
  const cancel = useCancelWithdrawal(profileId)

  const isWithdraw = mode === "withdraw"
  const isPending = isWithdraw ? withdraw.isPending : cancel.isPending
  const tooShort = reason.trim().length < MIN_REASON

  const reset = () => {
    setOpen(false)
    setReason("")
  }

  const handleSubmit = () => {
    if (tooShort) return
    const trimmed = reason.trim()
    if (isWithdraw) {
      withdraw.mutate(
        { reason: trimmed, version },
        { onSuccess: reset },
      )
    } else {
      cancel.mutate({ reason: trimmed }, { onSuccess: reset })
    }
  }

  return (
    <>
      <Button
        variant={isWithdraw ? "outline" : "secondary"}
        onClick={() => setOpen(true)}
        className="gap-2"
      >
        {isWithdraw ? (
          <LogOut className="h-4 w-4" />
        ) : (
          <RotateCcw className="h-4 w-4" />
        )}
        {isWithdraw ? "Rút hồ sơ" : "Hủy quy trình rút"}
      </Button>

      <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : reset())}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {isWithdraw ? "Rút hồ sơ tuyển sinh" : "Hủy quy trình rút"}
            </DialogTitle>
            <DialogDescription>
              {isWithdraw
                ? "Xác nhận rút hồ sơ tại chỗ (thí sinh đến trường)."
                : "Đưa hồ sơ đang chờ hoàn trở về nháp — dùng khi hoàn tiền bị từ chối, để hồ sơ không kẹt."}
            </DialogDescription>
          </DialogHeader>

          {isWithdraw ? (
            <Alert>
              <AlertDescription>
                Nếu hồ sơ đã đóng học phí, hệ thống sẽ tự tạo yêu cầu hoàn tiền;
                hồ sơ chỉ rút xong khi hoàn tất hoàn tiền.
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="withdraw-reason">Lý do</Label>
            <Textarea
              id="withdraw-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Nhập lý do (tối thiểu 5 ký tự)"
              rows={3}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="secondary" onClick={reset}>
              Đóng
            </Button>
            <Button
              type="button"
              variant={isWithdraw ? "destructive" : "default"}
              onClick={handleSubmit}
              disabled={isPending || tooShort}
            >
              {isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              {isWithdraw ? "Xác nhận rút" : "Xác nhận hủy rút"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
