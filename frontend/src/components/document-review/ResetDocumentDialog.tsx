"use client"

/**
 * GĐ1b §7 — hộp Đặt lại giấy: lý do BẮT BUỘC; giấy đã duyệt (cờ máy chủ `reset_keeps_evidence`) ghi "Tệp scan được giữ
 * lại" và KHÔNG có câu "file sẽ bị xóa"; giấy ngoài cấu hình (X1) có tiêu đề riêng; `requires_ack` ⇒ hộp cam kết.
 * Gửi `expected_row_version` = `row_version` của giấy đang xem. Lý do KHÔNG lưu vào "lý do gần đây" / storage.
 */
import { useId, useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
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
import { useResetDocumentGd1b } from "@/hooks/document-review/useDocumentReview"
import { documentStatusLabel } from "@/lib/document-review/messages"
import type { Gd1bActionableDocument } from "@/lib/zod/document-review"

import { UnknownSubmitterAckFields } from "./UnknownSubmitterAckFields"
import { useDocumentActionFeedback } from "./useDocumentActionFeedback"

export const RESET_KEEPS_EVIDENCE_TEXT = "Tệp scan được giữ lại làm bằng chứng của lần duyệt trước."
export const RESET_DETACHES_FILE_TEXT = "Tệp đã tải lên sẽ được gỡ khỏi giấy này."

interface Props {
  profileId: number
  document: Gd1bActionableDocument
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ResetDocumentDialog({ profileId, document: doc, open, onOpenChange }: Props) {
  const reasonId = useId()
  const ackId = useId()
  const [reason, setReason] = useState("")
  const [ack, setAck] = useState(false)
  const reset = useResetDocumentGd1b(profileId)
  const feedback = useDocumentActionFeedback(() => onOpenChange(false))

  const trimmed = reason.trim()
  const canSubmit = trimmed.length > 0 && trimmed.length <= 500 && (!doc.requires_ack || ack) && !reset.isPending

  const submit = () => {
    if (!canSubmit) return
    feedback.clearError()
    reset.mutate(
      {
        docCode: doc.code,
        body: {
          reason: trimmed,
          expected_row_version: doc.row_version,
          unknown_submitter_ack: doc.requires_ack ? ack : false,
        },
      },
      {
        onSuccess: () => feedback.onSuccess("Đã đặt lại giấy"),
        onError: feedback.onError,
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{doc.is_extra ? "Đặt lại giấy ngoài cấu hình" : "Đặt lại giấy"}</DialogTitle>
          <DialogDescription>
            Giấy «{doc.label}» ({documentStatusLabel(doc.status)}) sẽ về trạng thái Chưa nộp. Thao tác được ghi vào lịch sử
            giấy cùng lý do.
          </DialogDescription>
        </DialogHeader>

        {doc.reset_keeps_evidence ? (
          <Alert data-testid="dat-lai-giu-tep">
            <AlertDescription>{RESET_KEEPS_EVIDENCE_TEXT}</AlertDescription>
          </Alert>
        ) : doc.document_id != null ? (
          <p className="text-sm text-muted-foreground" data-testid="dat-lai-go-tep">
            {RESET_DETACHES_FILE_TEXT}
          </p>
        ) : null}

        <div className="space-y-2">
          <Label htmlFor={reasonId}>Lý do đặt lại (bắt buộc)</Label>
          <Textarea
            id={reasonId}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            autoComplete="off"
            rows={3}
            disabled={reset.isPending}
          />
        </div>

        {doc.requires_ack && (
          <UnknownSubmitterAckFields id={ackId} checked={ack} onCheckedChange={setAck} disabled={reset.isPending} />
        )}

        {feedback.error && (
          <p role="alert" className="text-sm text-destructive">
            {feedback.error}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={reset.isPending}>
            Huỷ
          </Button>
          <Button variant="destructive" onClick={submit} disabled={!canSubmit}>
            {reset.isPending ? "Đang đặt lại…" : "Đặt lại"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
