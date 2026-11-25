"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState, type ReactNode } from "react"
import { Loader2, Plus, RefreshCw } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDateTimeVN } from "@/lib/document-review/messages"
import { useReviewSessionList } from "@/lib/hooks/use-review-sessions"
import {
  LIST_EMPTY,
  RELOADING,
  REVIEW_DRAFT_NOTE,
  SESSION_STATUS_FILTERS,
  describeReviewSessionError,
  sessionStatusLabel,
  userRef,
} from "@/lib/review-sessions/messages"
import { reviewSessionHref, reviewSessionListHref, type ReviewSessionListFilters } from "@/lib/review-sessions/url"
import { LIST_PAGE_SIZE_DEFAULT } from "@/lib/zod/review-sessions"

import { CreateReviewSessionDialog } from "./CreateReviewSessionDialog"
import { LatestRunSummary } from "./LatestRunSummary"
import { ReviewErrorAlert } from "./ReviewErrorAlert"
import { thisYear, yearOptions } from "./years"

const SELECT_CLASS = "h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"

/**
 * M1 — danh sách lần xét (E2) + hộp "Tạo lần xét" (E1). Bộ lọc nằm trên URL (`?nam=&trang-thai=&trang=`): trang đọc
 * `searchParams` và truyền vào đây; đổi bộ lọc = đổi URL (MỘT nguồn). Thứ tự dòng do máy chủ (năm ↓, số thứ tự ↓) — không sắp lại.
 *
 * Không kiểm vai: nút "Tạo lần xét" luôn hiện (máy chủ chưa có cờ "được tạo" — KT-9 sẽ thêm `can_create`), máy chủ là chốt
 * (403 ⇒ câu "Chỉ Admin …"). Tải lỗi (kể cả 429) ⇒ hiện LỖI, không vẽ bảng cũ (đính chính 2 §1).
 */
export function ReviewSessionsListClient({ filters }: { filters: ReviewSessionListFilters }) {
  const router = useRouter()
  const [createOpen, setCreateOpen] = useState(false)
  const q = useReviewSessionList({
    academic_year: filters.year,
    status: filters.status,
    page: filters.page,
    page_size: LIST_PAGE_SIZE_DEFAULT,
  })
  const go = (next: ReviewSessionListFilters) => router.replace(reviewSessionListHref(next))

  let body: ReactNode
  if (q.isError) {
    body = <ReviewErrorAlert testId="ds-lan-xet-loi" message={describeReviewSessionError(q.error, "read").message} />
  } else if (!q.data) {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="ds-lan-xet-dang-tai">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải danh sách lần xét…
      </p>
    )
  } else if (q.data.items.length === 0) {
    const lastPage = q.data.total_pages
    body =
      q.data.total > 0 && lastPage > 0 ? (
        <div className="space-y-2 text-sm" data-testid="ds-lan-xet-qua-trang">
          <p>
            Trang {filters.page} không có dòng nào — danh sách có {lastPage} trang.
          </p>
          <Button variant="outline" size="sm" onClick={() => go({ ...filters, page: lastPage })}>
            Về trang cuối
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="ds-lan-xet-rong">
          {LIST_EMPTY}
        </p>
      )
  } else {
    const page = q.data
    body = (
      <div className="space-y-3">
        <Table data-testid="ds-lan-xet">
          <TableHeader>
            <TableRow>
              <TableHead>Năm</TableHead>
              <TableHead>Lần số</TableHead>
              <TableHead>Đợt</TableHead>
              <TableHead>Trạng thái</TableHead>
              <TableHead className="text-right">Số điểm sàn</TableHead>
              <TableHead>Lượt kiểm gần nhất</TableHead>
              <TableHead>Người tạo</TableHead>
              <TableHead>Ngày tạo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.items.map((s) => (
              <TableRow key={s.id} data-testid={`lan-xet-${s.id}`}>
                <TableCell>{s.academic_year}</TableCell>
                <TableCell>
                  <Link
                    href={reviewSessionHref(s.id)}
                    className="font-medium underline-offset-2 hover:underline"
                    data-testid={`lan-xet-${s.id}-mo`}
                  >
                    Lần số {s.seq_no}
                  </Link>
                </TableCell>
                <TableCell>{`${s.admission_round.round_name} (${s.admission_round.round_code})`}</TableCell>
                <TableCell>
                  <Badge variant="outline" data-testid={`lan-xet-${s.id}-trang-thai`}>
                    {sessionStatusLabel(s.status)}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">{s.floor_count}</TableCell>
                <TableCell>
                  <LatestRunSummary run={s.latest_run} testId={`lan-xet-${s.id}-luot`} />
                </TableCell>
                <TableCell>{userRef(s.created_by_user_id)}</TableCell>
                <TableCell>{formatDateTimeVN(s.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {page.total_pages > 1 ? (
          <div className="flex items-center justify-end gap-2 text-sm" data-testid="ds-lan-xet-phan-trang">
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page <= 1}
              onClick={() => go({ ...filters, page: filters.page - 1 })}
              data-testid="trang-truoc"
            >
              Trang trước
            </Button>
            <span data-testid="trang-hien-tai">
              Trang {page.page} / {page.total_pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page >= page.total_pages}
              onClick={() => go({ ...filters, page: filters.page + 1 })}
              data-testid="trang-sau"
            >
              Trang sau
            </Button>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Lần xét tuyển</h1>
          <p className="text-sm text-muted-foreground">{REVIEW_DRAFT_NOTE}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} data-testid="nut-tao-lan-xet">
          <Plus className="mr-1 h-4 w-4" />
          Tạo lần xét
        </Button>
      </header>

      <div className="flex flex-wrap items-end gap-3" data-testid="ds-lan-xet-bo-loc">
        <div className="w-36 space-y-1">
          <Label htmlFor="loc-nam">Năm</Label>
          <select
            id="loc-nam"
            data-testid="loc-nam"
            className={SELECT_CLASS}
            value={filters.year ?? ""}
            onChange={(e) =>
              go({ year: e.target.value ? Number(e.target.value) : undefined, status: filters.status, page: 1 })
            }
          >
            <option value="">Tất cả</option>
            {yearOptions(filters.year).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
        <div className="w-40 space-y-1">
          <Label htmlFor="loc-trang-thai">Trạng thái</Label>
          <select
            id="loc-trang-thai"
            data-testid="loc-trang-thai"
            className={SELECT_CLASS}
            value={filters.status ?? ""}
            onChange={(e) =>
              go({ year: filters.year, status: SESSION_STATUS_FILTERS.find((s) => s === e.target.value), page: 1 })
            }
          >
            <option value="">Tất cả</option>
            {SESSION_STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>
                {sessionStatusLabel(s)}
              </option>
            ))}
          </select>
        </div>
        <Button variant="outline" onClick={() => void q.refetch()} disabled={q.isFetching} data-testid="ds-lan-xet-tai-lai">
          <RefreshCw className="mr-1 h-4 w-4" />
          Tải lại
        </Button>
        {q.isFetching && q.data !== undefined ? (
          <span className="text-sm text-muted-foreground" data-testid="ds-lan-xet-dang-tai-lai">
            {RELOADING}
          </span>
        ) : null}
      </div>

      {body}

      <CreateReviewSessionDialog open={createOpen} onOpenChange={setCreateOpen} defaultYear={filters.year ?? thisYear()} />
    </div>
  )
}
