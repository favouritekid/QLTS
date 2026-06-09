"use client"

import { useEffect, useState } from "react"
import { Loader2, RotateCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useReopenLead } from "@/hooks/useLeads"
import type { LeadDetail } from "@/types/lead.types"

interface ReopenLeadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  lead: LeadDetail
}

// Mirror backend LeadReopenRequest.reason (min_length=5, max_length=500).
const REASON_MIN = 5
const REASON_MAX = 500

/**
 * Manager/admin entry to ``POST /leads/{id}/reopen`` — đưa một lead đã ngừng tư
 * vấn (sts20) trở lại luồng tư vấn (sts04).
 *
 * Visibility được quyết định ở nơi gọi qua cờ ``lead.permissions.can_reopen``
 * từ API (Thin Client — FE không tự suy quyền). Dialog chỉ thu lý do bắt buộc
 * và gọi mutation; mọi guard nghiệp vụ nằm ở backend.
 */
export function ReopenLeadDialog({
  open,
  onOpenChange,
  lead,
}: ReopenLeadDialogProps) {
  const [reason, setReason] = useState("")
  const mutation = useReopenLead()

  // Dialog luôn được mount (không key theo open) → xóa lý do cũ mỗi lần mở để không
  // hiện lại text của lần submit lỗi trước nếu mở lại mà không qua bước đóng.
  useEffect(() => {
    if (open) setReason("")
  }, [open])

  const reasonTrimmed = reason.trim()
  const reasonValid =
    reasonTrimmed.length >= REASON_MIN && reasonTrimmed.length <= REASON_MAX

  function reset() {
    setReason("")
  }

  function handleSubmit() {
    if (!reasonValid) return
    mutation.mutate(
      { leadId: lead.id, reason: reasonTrimmed },
      {
        onSuccess: () => {
          reset()
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (mutation.isPending) return
        onOpenChange(next)
        if (!next) reset()
      }}
    >
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Mở lại tư vấn</DialogTitle>
          <DialogDescription>
            Lead <strong>{lead.full_name}</strong> đang ở trạng thái đã ngừng tư
            vấn. Mở lại sẽ đưa lead về luồng tư vấn để tiếp tục chăm sóc. Lý do
            được lưu lại để đối soát.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 py-2">
          <Label htmlFor="reopen-reason">
            Lý do mở lại{" "}
            <span className="text-muted-foreground text-xs">
              (bắt buộc, ≥ {REASON_MIN} ký tự)
            </span>
          </Label>
          <Textarea
            id="reopen-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={mutation.isPending}
            rows={3}
            placeholder="Ví dụ: khách gọi lại ngày 09/06 muốn tiếp tục tư vấn ngành CĐ Điều dưỡng"
            autoFocus
          />
          {reason && !reasonValid && (
            <p className="text-xs text-destructive">
              {reasonTrimmed.length < REASON_MIN
                ? `Tối thiểu ${REASON_MIN} ký tự`
                : `Tối đa ${REASON_MAX} ký tự`}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              if (mutation.isPending) return
              onOpenChange(false)
              reset()
            }}
            disabled={mutation.isPending}
          >
            Hủy
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!reasonValid || mutation.isPending}
            className="bg-amber-600 hover:bg-amber-700"
          >
            {mutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RotateCcw className="mr-2 h-4 w-4" />
            )}
            Mở lại tư vấn
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
