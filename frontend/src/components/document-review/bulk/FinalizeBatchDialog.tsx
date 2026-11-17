"use client"

/**
 * GĐ1b §5.7 — chốt lô gián đoạn. Chốt KHÔNG ghi giấy nào, chỉ đánh dấu mục chưa chạy là "Chưa xử lý".
 * Lý do BẮT BUỘC khi máy chủ báo `finalize_requires_reason` (bản 5 B4: Admin chốt lô của người khác) — giao diện không
 * suy theo vai; máy chủ vẫn là chốt (thiếu ⇒ 422 ⇒ "Cần nhập lý do chốt lô"). Lý do KHÔNG lưu vào storage.
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
import { useFinalizeBatch, type BulkEndpoint } from "@/hooks/document-review/useBulkVerify"
import { describeFinalizeError } from "@/lib/document-review/messages"

interface Props {
  endpoint: BulkEndpoint
  batchId: string
  /** cờ máy chủ `BatchView.finalize_requires_reason` */
  requiresReason: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function FinalizeBatchDialog({ endpoint, batchId, requiresReason, open, onOpenChange }: Props) {
  const reasonId = useId()
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const finalize = useFinalizeBatch(endpoint)
  const trimmed = reason.trim()
  const canSubmit = !finalize.isPending && (!requiresReason || (trimmed.length > 0 && trimmed.length <= 500))

  const submit = () => {
    if (!canSubmit) return
    setError(null)
    finalize.mutate(
      { batchId, reason: trimmed || undefined },
      {
        onSuccess: () => onOpenChange(false),
        onError: (e) => setError(describeFinalizeError(e)),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Chốt lô bị gián đoạn</DialogTitle>
          <DialogDescription>
            Chốt không ghi thêm giấy nào: các giấy chưa chạy được đánh dấu &quot;Chưa xử lý&quot;. Giấy đã ghi giữ nguyên.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor={reasonId}>
            {requiresReason ? "Lý do chốt lô của người khác (bắt buộc)" : "Lý do chốt (không bắt buộc)"}
          </Label>
          <Textarea
            id={reasonId}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={500}
            autoComplete="off"
            rows={3}
            disabled={finalize.isPending}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={finalize.isPending}>
            Huỷ
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {finalize.isPending ? "Đang chốt…" : "Chốt lô"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
