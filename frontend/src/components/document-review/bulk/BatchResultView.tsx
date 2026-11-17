"use client"

/**
 * GĐ1b §5.9 — kết quả TƯỜNG MINH của một lô (câu 1 A′): bốn nhóm Đã ghi / Lỗi / Chưa xử lý / Chưa rõ, theo ĐÚNG số và
 * dòng máy chủ trả (`counts`, `items[].result`). Giao diện không tự đếm lại, không suy kết quả.
 */
import { Badge, type BadgeProps } from "@/components/ui/badge"
import {
  BATCH_RESULT_LABELS,
  batchItemText,
  batchStatusLabel,
  formatDateTimeVN,
} from "@/lib/document-review/messages"
import { BATCH_ITEM_RESULTS, type BatchItemResult, type BatchView } from "@/lib/zod/document-review"

const RESULT_VARIANT: Record<BatchItemResult, BadgeProps["variant"]> = {
  recorded: "success",
  error: "error",
  not_processed: "secondary",
  pending: "warning",
}

function statusVariant(status: string): BadgeProps["variant"] {
  switch (status) {
    case "completed":
      return "success"
    case "stopped":
    case "interrupted":
    case "interrupted_unfinalized":
      return "error"
    case "expired":
      return "secondary"
    default:
      return "info"
  }
}

export function BatchResultView({ view }: { view: BatchView }) {
  return (
    <div className="space-y-3" data-testid="ket-qua-lo">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant={statusVariant(view.status)} data-testid="trang-thai-lo">
          {batchStatusLabel(view.status)}
        </Badge>
        <span className="text-muted-foreground">Mã lô: {view.batch_id}</span>
      </div>
      <div className="text-xs text-muted-foreground">
        Tạo lúc {formatDateTimeVN(view.created_at)}
        {view.started_at ? ` · chạy lúc ${formatDateTimeVN(view.started_at)}` : ""}
        {view.finished_at ? ` · kết thúc ${formatDateTimeVN(view.finished_at)}` : ""}
        {view.finalized_at ? ` · chốt lúc ${formatDateTimeVN(view.finalized_at)}` : ""}
      </div>
      {view.finalize_reason && <p className="text-sm">Lý do chốt: {view.finalize_reason}</p>}

      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5" data-testid="dem-lo">
        <div>
          <dt className="text-muted-foreground">Hồ sơ</dt>
          <dd className="font-semibold">{view.counts.profiles}</dd>
        </div>
        {BATCH_ITEM_RESULTS.map((r) => (
          <div key={r}>
            <dt className="text-muted-foreground">{BATCH_RESULT_LABELS[r]}</dt>
            <dd className="font-semibold" data-testid={`dem-${r}`}>
              {view.counts[r]}
            </dd>
          </div>
        ))}
      </dl>

      {BATCH_ITEM_RESULTS.map((r) => {
        const items = view.items.filter((i) => i.result === r)
        if (items.length === 0) return null
        return (
          <section key={r} className="space-y-1">
            <h4 className="text-sm font-semibold">
              <Badge variant={RESULT_VARIANT[r]}>{BATCH_RESULT_LABELS[r]}</Badge> ({items.length})
            </h4>
            <ul className="space-y-1 text-sm" data-testid={`muc-${r}`}>
              {items.map((i) => (
                <li key={i.document_row_id} className="flex flex-wrap gap-x-2">
                  <span>Hồ sơ #{i.profile_id}</span>
                  <span className="text-muted-foreground">{i.document_type_code ?? `giấy #${i.document_row_id}`}</span>
                  {batchItemText(i) && <span>— {batchItemText(i)}</span>}
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
