"use client"

import { useState, type ReactNode } from "react"
import Link from "next/link"
import { Loader2, RefreshCw } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { useReviewRuns } from "@/lib/hooks/use-review-sessions"
import {
  CONFIG_CHANGED_BADGE,
  RELOADING,
  RUNS_EMPTY,
  RUNS_HIDE,
  RUNS_LOADING,
  RUNS_SECTION_TITLE,
  RUNS_SHOW,
  describeReviewSessionError,
  durationLabel,
  runStatusLabel,
  tabCountEntries,
  userRef,
} from "@/lib/review-sessions/messages"
import { reviewRunHref } from "@/lib/review-sessions/url"
import { LIST_PAGE_SIZE_DEFAULT } from "@/lib/zod/review-sessions"

import { ReviewErrorAlert } from "./ReviewErrorAlert"

/**
 * M4 — danh sách lượt kiểm của lần xét (E7, 20 / trang, `id` giảm dần — thứ tự máy chủ, không sắp lại). Thiết kế §3.5: thời điểm
 * yêu cầu / xong · thời lượng · người chạy (S3: họ tên máy chủ trả; trống ⇒ "Người dùng #id") · trạng thái (nhãn Phụ lục A; lạ ⇒ chữ máy chủ) ·
 * 4 số `tab_counts` của máy chủ · nhãn "Cấu hình đã đổi" · bộ luật. Bấm ⇒ M5.
 *
 * CHỈ tải khi người dùng mở danh sách (bớt một lần gọi `ADMIN_READ` mỗi lần vào trang — R6). Query E7 theo khuôn DC-1 (`staleTime` /
 * `gcTime` 0, không `placeholderData`); tải lỗi (kể cả 429) ⇒ hiện LỖI, KHÔNG vẽ dòng cũ (đọc `isError` TRƯỚC `data`). Làm mới sau
 * mọi thao tác ghi do hook lo (`refreshAfterReviewWrite`).
 */
export function ReviewRunsSection({ sessionId }: { sessionId: number }) {
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const q = useReviewRuns(sessionId, { page, page_size: LIST_PAGE_SIZE_DEFAULT }, open)

  let body: ReactNode = null
  if (!open) {
    body = null
  } else if (q.isError) {
    body = (
      <div className="space-y-2">
        <ReviewErrorAlert testId="luot-kiem-loi" message={describeReviewSessionError(q.error, "read").message} />
        <Button variant="outline" size="sm" onClick={() => void q.refetch()} disabled={q.isFetching} data-testid="luot-kiem-tai-lai">
          <RefreshCw className="mr-1 h-4 w-4" />
          Tải lại
        </Button>
      </div>
    )
  } else if (!q.data) {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="luot-kiem-dang-tai">
        <Loader2 className="h-4 w-4 animate-spin" /> {RUNS_LOADING}
      </p>
    )
  } else if (q.data.items.length === 0) {
    body = (
      <p className="text-sm text-muted-foreground" data-testid="luot-kiem-rong">
        {RUNS_EMPTY}
      </p>
    )
  } else {
    const data = q.data
    body = (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => void q.refetch()} disabled={q.isFetching} data-testid="luot-kiem-tai-lai">
            <RefreshCw className="mr-1 h-4 w-4" />
            Tải lại
          </Button>
          {q.isFetching ? <span className="text-sm text-muted-foreground">{RELOADING}</span> : null}
        </div>
        <Table data-testid="luot-kiem-bang">
          <TableHeader>
            <TableRow>
              <TableHead>Lượt</TableHead>
              <TableHead>Trạng thái</TableHead>
              <TableHead>Yêu cầu lúc</TableHead>
              <TableHead>Xong lúc</TableHead>
              <TableHead>Thời lượng</TableHead>
              <TableHead>Người chạy</TableHead>
              <TableHead>Số theo nhóm</TableHead>
              <TableHead>Bộ luật</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((r) => {
              const counts = tabCountEntries(r.tab_counts)
              return (
                <TableRow key={r.id} data-testid={`luot-${r.id}`}>
                  <TableCell>
                    <Link href={reviewRunHref(sessionId, r.id)} className="font-medium underline-offset-2 hover:underline" data-testid={`luot-${r.id}-mo`}>
                      #{r.id}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" data-testid={`luot-${r.id}-trang-thai`}>
                      {runStatusLabel(r.status)}
                    </Badge>
                    {r.config_changed_since_run ? (
                      <Badge variant="warning" className="ml-2" data-testid={`luot-${r.id}-cau-hinh-doi`}>
                        {CONFIG_CHANGED_BADGE}
                      </Badge>
                    ) : null}
                  </TableCell>
                  <TableCell>{formatDateTimeVN(r.requested_at)}</TableCell>
                  <TableCell data-testid={`luot-${r.id}-xong`}>{r.finished_at ? formatDateTimeVN(r.finished_at) : "—"}</TableCell>
                  <TableCell data-testid={`luot-${r.id}-thoi-luong`}>{durationLabel(r.duration_ms)}</TableCell>
                  <TableCell data-testid={`luot-${r.id}-nguoi-chay`}>{userRef(r.requested_by_user_id, r.requested_by_full_name)}</TableCell>
                  <TableCell data-testid={`luot-${r.id}-so-nhom`}>
                    {counts.length ? counts.map((c) => `${c.label} ${c.count}`).join(" · ") : "—"}
                  </TableCell>
                  <TableCell data-testid={`luot-${r.id}-bo-luat`}>{r.rule_version}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
        {data.total_pages > 1 ? (
          <div className="flex items-center justify-end gap-2 text-sm" data-testid="luot-kiem-phan-trang">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="luot-trang-truoc">
              Trang trước
            </Button>
            <span data-testid="luot-trang-hien-tai">
              Trang {data.page} / {data.total_pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= data.total_pages}
              onClick={() => setPage(page + 1)}
              data-testid="luot-trang-sau"
            >
              Trang sau
            </Button>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <section className="space-y-2 rounded-md border p-4" data-testid="luot-kiem">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{RUNS_SECTION_TITLE}</h2>
        <Button variant="outline" size="sm" onClick={() => setOpen(!open)} data-testid="luot-kiem-mo">
          {open ? RUNS_HIDE : RUNS_SHOW}
        </Button>
      </div>
      {body}
    </section>
  )
}
