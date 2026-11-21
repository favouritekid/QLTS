"use client"

/**
 * GĐ2-F1 — duyệt minh chứng ưu tiên khi máy chủ báo `requires_ack` (không rõ người tải tệp / người nhận bản giấy — quyết
 * định owner 19-11 câu 1, giống nút lẻ giấy tờ GĐ1b N1b A′): bắt buộc tích cam kết VÀ ghi lý do. Dùng lại hộp cam kết của
 * giấy tờ GĐ1b (`UnknownSubmitterAckFields`). Máy chủ kiểm lại (409 `UNKNOWN_SUBMITTER` / `OWN_SUBMISSION`); giao diện chỉ
 * khoá nút gửi. Lý do KHÔNG lưu vào storage.
 */
import { useId, useState } from "react"
import { toast } from "sonner"

import { UnknownSubmitterAckFields } from "@/components/document-review/UnknownSubmitterAckFields"
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
import { useVerifyObjectEvidence } from "@/lib/hooks/use-priority-evidence"
import { describePriorityEvidenceError } from "@/lib/priority-evidence/messages"

const MAX_REASON = 500

interface Props {
  profileId: number
  profileVersion: number
  subCode: string
  /** `document_id` máy chủ trả trong `priority_evidence_documents` (null = chưa có dòng giấy nào). */
  documentId: number | null
  /** Máy chủ báo dòng này CHƯA có dòng giấy (`status = missing`) — chỉ để hiện câu gợi ý. */
  noEvidenceRow: boolean
  onClose: () => void
}

export function UtEvidenceVerifyAckDialog({
  profileId,
  profileVersion,
  subCode,
  documentId,
  noEvidenceRow,
  onClose,
}: Props) {
  const baseId = useId()
  // Phiên bản hồ sơ chốt lúc mở hộp (hồ sơ được làm mới sau lỗi không âm thầm đổi bản đang duyệt).
  const [version] = useState(profileVersion)
  const [ack, setAck] = useState(false)
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const verify = useVerifyObjectEvidence(profileId, subCode)

  const trimmed = reason.trim()
  const canSubmit = ack && trimmed.length > 0 && trimmed.length <= MAX_REASON && !verify.isPending

  const submit = () => {
    if (!canSubmit) return
    setError(null)
    verify.mutate(
      { version, document_id: documentId, unknown_submitter_ack: ack, reason: trimmed },
      {
        onSuccess: () => {
          toast.success(`Đã duyệt UT${subCode} (có cam kết)`)
          onClose()
        },
        onError: (e) => setError(describePriorityEvidenceError(e, "verify")),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent data-testid={`ut-verify-ack-dialog-${subCode}`}>
        <DialogHeader>
          <DialogTitle>Duyệt minh chứng UT{subCode}</DialogTitle>
          <DialogDescription>
            Không rõ ai đã tải tệp / nhận bản giấy của minh chứng này. Chỉ duyệt khi bạn đã tự đối chiếu giấy thật; lý do
            được lưu vào nhật ký ưu tiên.
          </DialogDescription>
        </DialogHeader>
        {noEvidenceRow && (
          <p className="text-xs text-muted-foreground" data-testid={`ut-verify-ack-goi-y-${subCode}`}>
            Minh chứng này chưa được ghi nhận bản giấy. Nếu bản giấy vừa được nộp, nên để người nhận bấm «Đã nhận bản giấy»
            ở tab Giấy tờ, rồi người khác duyệt.
          </p>
        )}
        <UnknownSubmitterAckFields
          id={`${baseId}-ack`}
          checked={ack}
          onCheckedChange={setAck}
          disabled={verify.isPending}
        />
        <div className="space-y-2">
          <Label htmlFor={`${baseId}-ly-do`}>Lý do (bắt buộc khi cam kết)</Label>
          <Textarea
            id={`${baseId}-ly-do`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={MAX_REASON}
            autoComplete="off"
            rows={3}
            disabled={verify.isPending}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={verify.isPending}>
            Huỷ
          </Button>
          <Button onClick={submit} disabled={!canSubmit} data-testid={`ut-verify-ack-submit-${subCode}`}>
            {verify.isPending ? "Đang duyệt…" : "Duyệt"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
