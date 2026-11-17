"use client"

/**
 * GĐ1b — từ chối MỘT giấy (nút lẻ): lý do bắt buộc; `requires_ack` ⇒ hộp cam kết. Gửi `expected_row_version`.
 * Lý do KHÔNG lưu vào storage.
 */
import { useId, useState } from "react"

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
import { useRejectDocumentGd1b } from "@/hooks/document-review/useDocumentReview"
import type { Gd1bActionableDocument } from "@/lib/zod/document-review"

import { UnknownSubmitterAckFields } from "./UnknownSubmitterAckFields"
import { useDocumentActionFeedback } from "./useDocumentActionFeedback"

interface Props {
  profileId: number
  document: Gd1bActionableDocument
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RejectDocumentDialog({ profileId, document: doc, open, onOpenChange }: Props) {
  const baseId = useId()
  const [reason, setReason] = useState("")
  const [ack, setAck] = useState(false)
  const reject = useRejectDocumentGd1b(profileId)
  const feedback = useDocumentActionFeedback(() => onOpenChange(false))

  const trimmed = reason.trim()
  const canSubmit = trimmed.length > 0 && trimmed.length <= 500 && (!doc.requires_ack || ack) && !reject.isPending

  const submit = () => {
    if (!canSubmit) return
    feedback.clearError()
    reject.mutate(
      {
        docCode: doc.code,
        body: {
          reason: trimmed,
          expected_row_version: doc.row_version,
          unknown_submitter_ack: doc.requires_ack ? ack : false,
        },
      },
      {
        onSuccess: () => feedback.onSuccess("Đã từ chối giấy"),
        onError: feedback.onError,
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Từ chối giấy</DialogTitle>
          <DialogDescription>Giấy «{doc.label}» — lý do được ghi vào lịch sử giấy và báo cho cán bộ.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor={`${baseId}-ly-do`}>Lý do từ chối (bắt buộc)</Label>
          <Textarea
            id={`${baseId}-ly-do`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            autoComplete="off"
            rows={3}
            disabled={reject.isPending}
          />
        </div>
        {doc.requires_ack && (
          <UnknownSubmitterAckFields id={`${baseId}-ack`} checked={ack} onCheckedChange={setAck} disabled={reject.isPending} />
        )}
        {feedback.error && (
          <p role="alert" className="text-sm text-destructive">
            {feedback.error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={reject.isPending}>
            Huỷ
          </Button>
          <Button variant="destructive" onClick={submit} disabled={!canSubmit}>
            {reject.isPending ? "Đang từ chối…" : "Từ chối"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
