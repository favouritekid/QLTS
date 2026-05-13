"use client"

/**
 * Phase 3 PR-3D-B FE Wave B Bundle 3 — local resolve dialog for backfill queue.
 *
 * Slim dialog (single textarea + min length validate) — separate from Bundle 2
 * AuditReasonDialog because backfill queue is a different domain (data cleanup
 * vs state-machine transition). Reuses the same min/max length contract
 * (5/2000) as BE `BackfillExceptionResolveRequest` schema.
 *
 * Modes:
 *   - Single target → `target` prop set, dialog shows "Đóng ngoại lệ #{id}"
 *   - Bulk → `bulkCount` prop set, dialog shows "Đóng N ngoại lệ"
 */
import { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import type {
  AdmissionBackfillException,
  BackfillBulkResolveResponse,
} from "@/lib/zod/admission-backfill"

const MIN_LENGTH = 5
const MAX_LENGTH = 2000

export interface BackfillResolveDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Single-row mode: the row being resolved. Mutually exclusive with bulkCount. */
  target?: AdmissionBackfillException | null
  /** Bulk mode: number of rows selected. */
  bulkCount?: number
  onSubmit: (reason: string) => void
  isSubmitting: boolean
  /** Bulk mode: counters from last successful run for inline summary. */
  bulkResult?: BackfillBulkResolveResponse | null
  errorMessage?: string | null
}

export function BackfillResolveDialog({
  open,
  onOpenChange,
  target,
  bulkCount,
  onSubmit,
  isSubmitting,
  bulkResult,
  errorMessage,
}: BackfillResolveDialogProps) {
  const isBulk = bulkCount !== undefined && bulkCount > 0 && !target
  const [reason, setReason] = useState("")
  // Reset reason whenever dialog opens. React docs-blessed
  // "reset state on prop change" pattern — setState during render avoids
  // useEffect cascade + react-hooks/set-state-in-effect lint error.
  const [lastOpen, setLastOpen] = useState(open)
  if (lastOpen !== open) {
    setLastOpen(open)
    if (open) setReason("")
  }

  const trimmed = reason.trim()
  const tooShort = trimmed.length < MIN_LENGTH
  const tooLong = trimmed.length > MAX_LENGTH
  const invalid = tooShort || tooLong

  const title = isBulk
    ? `Đóng ${bulkCount} ngoại lệ`
    : target
    ? `Đóng ngoại lệ #${target.id}`
    : "Đóng ngoại lệ"

  const description = isBulk
    ? `Hành động sẽ đóng đồng loạt ${bulkCount} dòng đang chọn. Dòng đã đóng từ trước sẽ bị bỏ qua (xem counters sau khi gửi).`
    : target
    ? `Loại: ${target.exception_type} — Hồ sơ #${target.profile_id}.`
    : ""

  const handleConfirm = () => {
    if (invalid) return
    onSubmit(trimmed)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="backfill-resolve-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="backfill-resolve-notes">
            Ghi chú xử lý <span className="text-destructive">*</span>
          </Label>
          <Textarea
            id="backfill-resolve-notes"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={`Nhập tối thiểu ${MIN_LENGTH} ký tự để ghi audit log…`}
            rows={4}
            disabled={isSubmitting}
            aria-invalid={invalid && trimmed.length > 0}
            data-testid="backfill-resolve-textarea"
          />
          <div className="flex items-center justify-between text-xs">
            <span
              className="text-muted-foreground"
              data-testid="backfill-resolve-counter"
            >
              {trimmed.length}/{MAX_LENGTH}
            </span>
            {tooShort && trimmed.length > 0 && (
              <span
                role="alert"
                className="text-destructive"
                data-testid="backfill-resolve-error"
              >
                Cần tối thiểu {MIN_LENGTH} ký tự.
              </span>
            )}
            {tooLong && (
              <span role="alert" className="text-destructive">
                Vượt giới hạn {MAX_LENGTH} ký tự.
              </span>
            )}
          </div>
          {errorMessage && (
            <p
              role="alert"
              className="text-sm text-destructive"
              data-testid="backfill-resolve-server-error"
            >
              {errorMessage}
            </p>
          )}
          {isBulk && bulkResult && (
            <div
              className="rounded-md border bg-muted/30 p-2 text-xs"
              data-testid="bulk-result-summary"
            >
              <p>
                Yêu cầu: <strong>{bulkResult.requested}</strong> • Đã đóng:{" "}
                <strong className="text-success-700">
                  {bulkResult.resolved}
                </strong>{" "}
                • Đã đóng trước đó:{" "}
                <strong>{bulkResult.skipped_already_resolved}</strong> • Không
                tồn tại: <strong>{bulkResult.missing}</strong>
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
          >
            Huỷ
          </Button>
          <Button
            type="button"
            onClick={handleConfirm}
            disabled={invalid || isSubmitting}
            data-testid="backfill-resolve-confirm"
          >
            {isSubmitting ? "Đang xử lý…" : "Xác nhận đóng"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
