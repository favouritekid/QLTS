"use client"

/**
 * GĐ1b §5.8 — "Lô duyệt giấy của tôi": lô đang chạy + đã kết thúc trong cửa sổ hiển thị 30 ngày (máy chủ lọc), 20 /
 * trang theo con trỏ. `scope = all` chỉ Admin — máy chủ quyết (403 / 404 ⇒ báo), giao diện không suy vai.
 */
import axios from "axios"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useBatchList, type BulkEndpoint } from "@/hooks/document-review/useBulkVerify"
import { batchStatusLabel, formatDateTimeVN } from "@/lib/document-review/messages"
import type { BatchListScope } from "@/lib/zod/document-review"

interface Props {
  endpoint: BulkEndpoint
  scope: BatchListScope
  onSelect: (batchId: string) => void
}

export function BatchListPanel({ endpoint, scope, onSelect }: Props) {
  const list = useBatchList(endpoint, scope)
  const items = list.data?.pages.flatMap((p) => p.items) ?? []
  const forbidden =
    axios.isAxiosError(list.error) && (list.error.response?.status === 403 || list.error.response?.status === 404)

  return (
    <div className="space-y-2" data-testid={`danh-sach-lo-${scope}`}>
      {list.isLoading && <p className="text-sm text-muted-foreground">Đang tải danh sách lô…</p>}
      {list.isError && (
        <p role="alert" className="text-sm text-destructive">
          {forbidden
            ? scope === "all"
              ? "Chỉ Admin xem được danh sách tất cả lô."
              : "Bạn không có quyền xem lô duyệt giấy."
            : "Không tải được danh sách lô — thử lại sau."}
        </p>
      )}
      {list.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted-foreground">Không có lô nào trong 30 ngày gần đây.</p>
      )}
      {items.length > 0 && (
        <ul className="divide-y rounded-md border">
          {items.map((b) => (
            <li key={b.batch_id} className="flex flex-wrap items-center justify-between gap-2 p-2 text-sm">
              <div className="space-y-0.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{batchStatusLabel(b.status)}</Badge>
                  <span>{formatDateTimeVN(b.created_at)}</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {b.profile_count} hồ sơ · đã ghi {b.counts.recorded} · lỗi {b.counts.error} · chưa xử lý{" "}
                  {b.counts.not_processed} · chưa rõ {b.counts.pending}
                </div>
              </div>
              <Button size="sm" variant="outline" onClick={() => onSelect(b.batch_id)}>
                Xem lô
              </Button>
            </li>
          ))}
        </ul>
      )}
      {list.hasNextPage && (
        <Button size="sm" variant="ghost" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
          {list.isFetchingNextPage ? "Đang tải…" : "Tải thêm"}
        </Button>
      )}
    </div>
  )
}
