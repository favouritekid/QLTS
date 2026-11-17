"use client"

/**
 * GĐ1b §5.7 — chốt lô gián đoạn. Chốt KHÔNG ghi giấy nào, chỉ đánh dấu mục chưa chạy là "Chưa xử lý". Lý do: bắt buộc
 * khi Admin chốt lô của người khác — máy chủ quyết (thiếu ⇒ 422 ⇒ hộp báo "Cần nhập lý do"); giao diện không suy vai.
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
import { useFinalizeBatch } from "@/hooks/document-review/useBulkVerify"
import type { BulkEndpoint } from "@/lib/api/document-bulk"
import { describeFinalizeError } from "@/lib/document-review/messages"

interface Props {
  endpoint: BulkEndpoint
  batchId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function FinalizeBatchDialog({ endpoint, batchId, open, onOpenChange }: Props) {
  const reasonId = useId()
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const finalize = useFinalizeBatch(endpoint)

  const submit = () => {
    setError(null)
    finalize.mutate(
      { batchId, reason: reason.trim() || undefined },
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
          <Label htmlFor={reasonId}>Lý do chốt (bắt buộc nếu bạn chốt lô của người khác)</Label>
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
          <Button onClick={submit} disabled={finalize.isPending}>
            {finalize.isPending ? "Đang chốt…" : "Chốt lô"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
