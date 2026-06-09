"use client"

import { useState } from "react"
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
import { useReopenLead, useCreateReopenRequest } from "@/hooks/useLeads"
import type { LeadDetail } from "@/types/lead.types"

interface ReopenLeadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  lead: LeadDetail
  /** "reopen": manager/admin mở trực tiếp; "request": officer XIN (chờ duyệt). */
  mode?: "reopen" | "request"
}

// Mirror backend LeadReopenRequest.reason (min_length=5, max_length=500).
const REASON_MIN = 5
const REASON_MAX = 500

const COPY = {
  reopen: {
    title: "Mở lại tư vấn",
    desc: "Mở lại sẽ đưa lead về luồng tư vấn để tiếp tục chăm sóc.",
    label: "Lý do mở lại",
    submit: "Mở lại tư vấn",
  },
  request: {
    title: "Xin mở lại tư vấn",
    desc: "Yêu cầu sẽ được gửi tới quản lý duyệt trước khi lead được mở lại.",
    label: "Lý do xin mở lại",
    submit: "Gửi yêu cầu",
  },
} as const

/**
 * Dialog mở lại / xin mở lại lead đã ngừng tư vấn (sts20). Visibility quyết định ở
 * nơi gọi qua cờ ``permissions.can_reopen`` (manager/admin) hoặc
 * ``permissions.can_request_reopen`` (officer) — Thin Client. Dialog chỉ thu lý do.
 */
export function ReopenLeadDialog({
  open,
  onOpenChange,
  lead,
  mode = "reopen",
}: ReopenLeadDialogProps) {
  const [reason, setReason] = useState("")
  const reopenMutation = useReopenLead()
  const requestMutation = useCreateReopenRequest()
  const mutation = mode === "request" ? requestMutation : reopenMutation
  const copy = COPY[mode]

  // reason được xóa khi đóng dialog (onOpenChange !next → reset). Nút "Mở lại" chỉ mở
  // dialog từ trạng thái đã đóng nên mỗi lần mở reason luôn rỗng — không cần effect
  // reset-on-open (vi phạm rule setState-trong-effect).
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
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>
            Lead <strong>{lead.full_name}</strong> đang ở trạng thái đã ngừng tư
            vấn. {copy.desc} Lý do được lưu lại để đối soát.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 py-2">
          <Label htmlFor="reopen-reason">
            {copy.label}{" "}
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
            {copy.submit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
