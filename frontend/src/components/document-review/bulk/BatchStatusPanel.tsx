"use client"

/**
 * GĐ1b §5.6 / §5.9 — TRA một lô theo mã (chỉ `GET`). Hỏi lại 3 s rồi 10 s khi đang bắt đầu / đang chạy / chưa rõ.
 * Nút "Chạy lô này" CHỈ theo cờ `can_execute`, "Chốt lô" CHỈ theo `can_finalize` (thin client). KHÔNG bao giờ tự gửi
 * lại `execute`: lệnh chỉ đi khi người dùng bấm, mỗi lần bấm đúng một lần gọi.
 */
import { useState } from "react"
import axios from "axios"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  useBatch,
  useExecuteBatch,
  useLastBatchId,
  type BulkEndpoint,
} from "@/hooks/document-review/useBulkVerify"
import {
  classifyExecuteError,
  confirmationSentence,
  describeBatchLookupError,
  POLLING_BATCH_STATUSES,
} from "@/lib/document-review/messages"

import { BatchResultView } from "./BatchResultView"
import { FinalizeBatchDialog } from "./FinalizeBatchDialog"

interface Props {
  endpoint: BulkEndpoint
  batchId: string
  /** câu báo kèm (vd "Chưa rõ kết quả — đang tra lô") */
  notice?: string | null
}

export function BatchStatusPanel({ endpoint, batchId, notice }: Props) {
  const batch = useBatch(endpoint, batchId)
  const execute = useExecuteBatch(endpoint)
  const last = useLastBatchId()
  const [confirmed, setConfirmed] = useState(false)
  const [runMessage, setRunMessage] = useState<string | null>(null)
  const [finalizeOpen, setFinalizeOpen] = useState(false)

  const view = batch.data
  const gone = axios.isAxiosError(batch.error) && batch.error.response?.status === 404

  const run = () => {
    if (!view || !confirmed || execute.isPending) return
    setRunMessage(null)
    execute.mutate(
      { batchId: view.batch_id, confirmationText: confirmationSentence(view.items.length) },
      {
        onError: (e) => {
          setRunMessage(classifyExecuteError(e).message)
          // tra lại bằng GET — không gửi lại execute
          void batch.refetch()
        },
      },
    )
  }

  return (
    <div className="space-y-3" data-testid="tra-lo">
      {notice && (
        <p role="status" className="text-sm font-medium">
          {notice}
        </p>
      )}
      {batch.isLoading && <p className="text-sm text-muted-foreground">Đang tra lô…</p>}
      {batch.isError && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-destructive">
            {describeBatchLookupError(batch.error)}
          </p>
          {gone && last.batchId === batchId && (
            <Button size="sm" variant="outline" onClick={last.forget}>
              Bỏ mã lô này khỏi phiên
            </Button>
          )}
        </div>
      )}

      {view && (
        <>
          <BatchResultView view={view} />
          {POLLING_BATCH_STATUSES.has(view.status) && (
            <p className="text-xs text-muted-foreground" data-testid="dang-hoi-lai">
              Đang cập nhật kết quả từ máy chủ…
            </p>
          )}

          {view.can_execute && (
            <div className="space-y-2 rounded-md border p-3" data-testid="chay-lo-nay">
              <div className="flex items-start gap-2">
                <Checkbox
                  id={`xac-nhan-${view.batch_id}`}
                  checked={confirmed}
                  onCheckedChange={(v) => setConfirmed(v === true)}
                  disabled={execute.isPending}
                />
                <Label htmlFor={`xac-nhan-${view.batch_id}`} className="font-normal leading-snug">
                  {confirmationSentence(view.items.length)}
                </Label>
              </div>
              <Button onClick={run} disabled={!confirmed || execute.isPending}>
                {execute.isPending ? "Đang chạy…" : "Chạy lô này"}
              </Button>
            </div>
          )}
          {runMessage && (
            <p role="alert" className="text-sm">
              {runMessage}
            </p>
          )}

          {view.can_finalize && (
            <Button variant="outline" onClick={() => setFinalizeOpen(true)}>
              Chốt lô
            </Button>
          )}
          {finalizeOpen && (
            <FinalizeBatchDialog
              endpoint={endpoint}
              batchId={view.batch_id}
              requiresReason={view.finalize_requires_reason}
              open
              onOpenChange={(v) => {
                if (!v) setFinalizeOpen(false)
              }}
            />
          )}
        </>
      )}
    </div>
  )
}
