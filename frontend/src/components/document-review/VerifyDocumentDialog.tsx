"use client"

/**
 * GĐ1b §4.6 / §7 — duyệt MỘT giấy (nút lẻ): hình thức mặc định = hình thức lúc nhận; KHÔNG có dự phòng "photo" —
 * thiếu hình thức lúc nhận ⇒ người duyệt phải tự chọn. `requires_ack` ⇒ hộp cam kết + lý do bắt buộc.
 * Gửi `expected_row_version`. Lý do KHÔNG lưu vào storage.
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Textarea } from "@/components/ui/textarea"
import { useVerifyDocumentGd1b } from "@/hooks/document-review/useDocumentReview"
import { formatLabel } from "@/lib/document-review/messages"
import { VERIFIED_FORMATS, verifiedFormatSchema, type Gd1bDocument, type VerifiedFormat } from "@/lib/zod/document-review"

import { UnknownSubmitterAckFields } from "./UnknownSubmitterAckFields"
import { useDocumentActionFeedback } from "./useDocumentActionFeedback"

interface Props {
  profileId: number
  document: Gd1bDocument
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Hình thức lúc nhận nếu là mã hợp lệ — KHÔNG đoán khi trống / lạ. */
function declaredFormat(doc: Gd1bDocument): VerifiedFormat | null {
  const r = verifiedFormatSchema.safeParse(doc.actual_submission_format)
  return r.success ? r.data : null
}

export function VerifyDocumentDialog({ profileId, document: doc, open, onOpenChange }: Props) {
  const baseId = useId()
  const [format, setFormat] = useState<VerifiedFormat | null>(() => declaredFormat(doc))
  const [reason, setReason] = useState("")
  const [ack, setAck] = useState(false)
  const verify = useVerifyDocumentGd1b(profileId)
  const feedback = useDocumentActionFeedback(() => onOpenChange(false))

  const trimmed = reason.trim()
  const ackOk = !doc.requires_ack || (ack && trimmed.length > 0 && trimmed.length <= 500)
  const canSubmit = format !== null && ackOk && !verify.isPending

  const submit = () => {
    if (!canSubmit || format === null) return
    feedback.clearError()
    verify.mutate(
      {
        docCode: doc.code,
        body: {
          format,
          expected_row_version: doc.row_version,
          unknown_submitter_ack: doc.requires_ack ? ack : false,
          ...(doc.requires_ack ? { reason: trimmed } : {}),
        },
      },
      {
        onSuccess: () => feedback.onSuccess("Đã duyệt giấy"),
        onError: feedback.onError,
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Duyệt giấy</DialogTitle>
          <DialogDescription>
            Giấy «{doc.label}» — hình thức lúc nhận: {formatLabel(doc.actual_submission_format)}.
          </DialogDescription>
        </DialogHeader>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Hình thức đã đối chiếu</legend>
          <RadioGroup
            value={format ?? ""}
            onValueChange={(v) => {
              const r = verifiedFormatSchema.safeParse(v)
              setFormat(r.success ? r.data : null)
            }}
            disabled={verify.isPending}
          >
            {VERIFIED_FORMATS.map((f) => (
              <div key={f} className="flex items-center gap-2">
                <RadioGroupItem id={`${baseId}-${f}`} value={f} />
                <Label htmlFor={`${baseId}-${f}`} className="font-normal">
                  {formatLabel(f)}
                </Label>
              </div>
            ))}
          </RadioGroup>
          {format === null && (
            <p className="text-xs text-muted-foreground" data-testid="chua-chon-hinh-thuc">
              Chưa ghi hình thức lúc nhận — hãy chọn hình thức đã đối chiếu.
            </p>
          )}
        </fieldset>

        {doc.requires_ack && (
          <>
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
                maxLength={500}
                autoComplete="off"
                rows={3}
                disabled={verify.isPending}
              />
            </div>
          </>
        )}

        {feedback.error && (
          <p role="alert" className="text-sm text-destructive">
            {feedback.error}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={verify.isPending}>
            Huỷ
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {verify.isPending ? "Đang duyệt…" : "Duyệt"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
