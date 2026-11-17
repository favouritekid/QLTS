"use client"

/**
 * GĐ1b §5.2 → §5.9 — luồng MỘT lô: Xem trước (tạo lô ở máy chủ, lưu `batch_id` vào sessionStorage) → ô xác nhận →
 * Duyệt (`execute`, ĐÚNG MỘT LẦN mỗi lần bấm) → kết quả tường minh. Mất phản hồi / 5xx / 504 / 409 `BATCH_RUNNING` /
 * `BATCH_EXISTS` ⇒ TRA lô bằng `GET`, KHÔNG gửi lại `execute`. `PREVIEW_EXPIRED` / 404 ⇒ xem trước lại.
 *
 * Dùng cho: nút "Duyệt giấy theo bộ lọc hiện tại" (danh sách hồ sơ), "Xác nhận kiểm tra" một hồ sơ (`profile_ids =
 * [id]` — thay `Promise.all` cũ), lô duyệt chéo. ⚠️ Nối vào `/admissions*` CHỜ biên bản đo nền V4.
 */
import { useId, useState } from "react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  useExecuteBatch,
  usePreviewBulkVerify,
  type BulkEndpoint,
  type BulkSelection,
} from "@/hooks/document-review/useBulkVerify"
import {
  classifyExecuteError,
  confirmationSentence,
  describePreviewError,
  documentReasonText,
} from "@/lib/document-review/messages"
import type { BulkPreview } from "@/lib/zod/document-review"

import { BatchStatusPanel } from "./BatchStatusPanel"

type Stage =
  | { kind: "start" }
  | { kind: "preview"; preview: BulkPreview }
  | { kind: "result"; batchId: string }
  | { kind: "lookup"; batchId: string; message: string }
  | { kind: "restart"; message: string }

interface Props {
  endpoint: BulkEndpoint
  selection: BulkSelection
  /** câu mô tả phạm vi chọn (vd "các hồ sơ theo bộ lọc hiện tại") */
  scopeLabel: string
  /** cho phép chọn "gồm giấy tuỳ chọn" (lô một hồ sơ / bộ lọc) */
  allowOptional?: boolean
}

function groupExcluded(preview: BulkPreview): Array<{ code: string; count: number }> {
  const m = new Map<string, number>()
  for (const x of preview.excluded) m.set(x.reason_code, (m.get(x.reason_code) ?? 0) + 1)
  return [...m.entries()].map(([code, count]) => ({ code, count }))
}

export function BulkVerifyFlow({ endpoint, selection, scopeLabel, allowOptional = true }: Props) {
  const baseId = useId()
  const [stage, setStage] = useState<Stage>({ kind: "start" })
  const [includeOptional, setIncludeOptional] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const preview = usePreviewBulkVerify(endpoint)
  const execute = useExecuteBatch(endpoint)

  const doPreview = () => {
    setPreviewError(null)
    setRunError(null)
    setConfirmed(false)
    preview.mutate(
      { selection, includeOptional: allowOptional ? includeOptional : false },
      {
        onSuccess: (p) => setStage({ kind: "preview", preview: p }),
        onError: (e) => setPreviewError(describePreviewError(e)),
      },
    )
  }

  const doExecute = (p: BulkPreview) => {
    if (!confirmed || execute.isPending) return
    setRunError(null)
    execute.mutate(
      { batchId: p.batch_id, confirmationText: confirmationSentence(p.counts.documents) },
      {
        onSuccess: (view) => setStage({ kind: "result", batchId: view.batch_id }),
        onError: (e) => {
          const o = classifyExecuteError(e)
          if (o.kind === "lookup") setStage({ kind: "lookup", batchId: p.batch_id, message: o.message })
          else if (o.kind === "expired" || o.kind === "gone") setStage({ kind: "restart", message: o.message })
          else setRunError(o.message) // máy chủ từ chối TRƯỚC khi ghi (§5.3 bước 4) — lô CHƯA chạy
        },
      },
    )
  }

  if (stage.kind === "start" || stage.kind === "restart") {
    return (
      <div className="space-y-3" data-testid="lo-bat-dau">
        {stage.kind === "restart" && (
          <p role="alert" className="text-sm font-medium">
            {stage.message}
          </p>
        )}
        <p className="text-sm">
          Duyệt hàng loạt giấy bản giấy của {scopeLabel}. Máy chủ chọn đúng các giấy đủ điều kiện, giấy không đủ điều kiện
          được liệt kê kèm lý do. Chưa ghi gì cho tới khi bạn bấm &quot;Duyệt&quot;.
        </p>
        {allowOptional && (
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${baseId}-tuy-chon`}
              checked={includeOptional}
              onCheckedChange={(v) => setIncludeOptional(v === true)}
              disabled={preview.isPending}
            />
            <Label htmlFor={`${baseId}-tuy-chon`} className="font-normal">
              Gồm cả giấy tuỳ chọn
            </Label>
          </div>
        )}
        {previewError && (
          <p role="alert" className="text-sm text-destructive">
            {previewError}
          </p>
        )}
        <Button onClick={doPreview} disabled={preview.isPending}>
          {preview.isPending ? "Đang xem trước…" : stage.kind === "restart" ? "Xem trước lại" : "Xem trước"}
        </Button>
      </div>
    )
  }

  if (stage.kind === "preview") {
    const p = stage.preview
    const excluded = groupExcluded(p)
    return (
      <div className="space-y-3" data-testid="lo-xem-truoc">
        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4" data-testid="dem-xem-truoc">
          <div>
            <dt className="text-muted-foreground">Hồ sơ</dt>
            <dd className="font-semibold">{p.counts.profiles}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Giấy sẽ duyệt</dt>
            <dd className="font-semibold" data-testid="so-giay-se-duyet">
              {p.counts.documents}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Bắt buộc</dt>
            <dd className="font-semibold">{p.counts.required}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Tuỳ chọn</dt>
            <dd className="font-semibold">{p.counts.optional}</dd>
          </div>
        </dl>

        {excluded.length > 0 && (
          <section className="space-y-1 text-sm" data-testid="giay-bi-loai">
            <h4 className="font-semibold">Giấy không vào lô ({p.excluded.length})</h4>
            <ul className="list-disc pl-5">
              {excluded.map((g) => (
                <li key={g.code}>
                  {documentReasonText(g.code)}: {g.count}
                </li>
              ))}
            </ul>
          </section>
        )}

        {p.counts.documents === 0 ? (
          <p className="text-sm text-muted-foreground">Không có giấy nào đủ điều kiện để duyệt hàng loạt.</p>
        ) : (
          <div className="space-y-2 rounded-md border p-3">
            <div className="flex items-start gap-2">
              <Checkbox
                id={`${baseId}-xac-nhan`}
                checked={confirmed}
                onCheckedChange={(v) => setConfirmed(v === true)}
                disabled={execute.isPending}
              />
              <Label htmlFor={`${baseId}-xac-nhan`} className="font-normal leading-snug">
                {confirmationSentence(p.counts.documents)}
              </Label>
            </div>
            {runError && (
              <p role="alert" className="text-sm text-destructive">
                {runError}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => doExecute(p)} disabled={!confirmed || execute.isPending}>
                {execute.isPending ? "Đang duyệt…" : `Duyệt ${p.counts.documents} giấy`}
              </Button>
              <Button variant="outline" onClick={doPreview} disabled={execute.isPending || preview.isPending}>
                Xem trước lại
              </Button>
            </div>
          </div>
        )}
      </div>
    )
  }

  if (stage.kind === "result") {
    // phản hồi `execute` đã nằm trong cache của `useBatch` — bảng tra hiện ngay, hỏi lại nếu còn đang chạy
    return <BatchStatusPanel endpoint={endpoint} batchId={stage.batchId} />
  }

  return <BatchStatusPanel endpoint={endpoint} batchId={stage.batchId} notice={stage.message} />
}

