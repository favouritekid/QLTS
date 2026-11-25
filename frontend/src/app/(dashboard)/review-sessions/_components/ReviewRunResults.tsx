"use client"

import { useEffect, useState, type ReactNode } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Loader2, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useReviewRunRows } from "@/lib/hooks/use-review-sessions"
import { describeReviewSessionError, majorLabel, tabCountEntries } from "@/lib/review-sessions/messages"
import {
  PROFILE_GONE,
  consideredChoiceLabel,
  documentGapsText,
  ethnicPriorityLabel,
  flagLabel,
  hintLabel,
  labelList,
  numberLabel,
  perChoiceSummary,
  profileStatusLabel,
  reasonLabel,
  scoreLabel,
  unitRef,
  withinSeatsLabel,
} from "@/lib/review-sessions/row-labels"
import { ROW_PAGE_SIZES, reviewRunRowsHref, type ReviewRunRowFilters, type RowPageSize } from "@/lib/review-sessions/url"
import type { ReviewRow, ReviewRun } from "@/lib/zod/review-sessions"

import { ReviewErrorAlert } from "./ReviewErrorAlert"
import { ReviewRowDrawer } from "./ReviewRowDrawer"

const SELECT_CLASS = "h-10 w-full rounded-md border border-border bg-card px-2 text-sm md:h-9"

/** [ĐX] */
export const RESULTS_ALL = "Tất cả"
/** [ĐX] */
export const RESULTS_LOADING = "Đang tải danh sách…"
/** [ĐX] */
export const RESULTS_PAGE_LOADING = "Đang tải trang…"
/** [ĐX] */
export const RESULTS_EMPTY = "Không có dòng nào cho tab / bộ lọc này."
/** [ĐX] */
export const RESULTS_VIEW_ROW = "Xem"
/** Thiết kế §3.6: lọc ngành chỉ tiêu 0 / trống ⇒ dùng cờ / lý do (HĐ4 E9 — học vụ ấy không bao giờ là NV được xếp). [ĐX câu] */
export const RESULTS_MAJOR_FILTER_HINT =
  "Ngành chỉ tiêu 0 / chưa có chỉ tiêu không bao giờ là nguyện vọng được xếp — lọc bằng cờ \"Có nguyện vọng vào ngành đã đóng tuyển\" hoặc lý do \"Ngành chưa có chỉ tiêu\"."
/** Thiết kế §3.6 "Đang lọc: {total} dòng". */
export function resultsFiltered(total: number): string {
  return `Đang lọc: ${total} dòng`
}

type ColKey =
  | "name"
  | "unit"
  | "choice"
  | "total"
  | "floor"
  | "rank"
  | "ethnic"
  | "reasons"
  | "seats"
  | "hints"
  | "perChoice"
  | "profileStatus"
  | "docs"
  | "flags"

/** Thiết kế §3.6 "Bốn tab — cột chính" [ĐX]; tab lạ (GĐ2-C `excluded`) ⇒ cột chung. */
const TAB_COLUMNS: Record<string, readonly ColKey[]> = {
  auto: ["name", "unit", "choice", "total", "floor", "rank", "ethnic", "flags"],
  needs_decision: ["name", "unit", "choice", "total", "floor", "rank", "ethnic", "reasons", "seats", "hints", "flags"],
  not_passed: ["name", "unit", "reasons", "perChoice", "flags"],
  ineligible: ["name", "unit", "profileStatus", "reasons", "docs", "flags"],
}
const DEFAULT_COLUMNS: readonly ColKey[] = ["name", "unit", "reasons", "flags"]

const COL_TITLE: Record<ColKey, string> = {
  name: "Họ tên",
  unit: "Đơn vị",
  choice: "NV được xếp",
  total: "Tổng điểm",
  floor: "Sàn",
  rank: "Hạng",
  ethnic: "Ưu tiên dân tộc",
  reasons: "Lý do",
  seats: "Trong số chỗ",
  hints: "Gợi ý",
  perChoice: "Từng nguyện vọng",
  profileStatus: "Trạng thái hồ sơ",
  docs: "Giấy thiếu / chưa duyệt",
  flags: "Cờ",
}

function cell(row: ReviewRow, col: ColKey): ReactNode {
  switch (col) {
    case "name":
      return row.full_name === null ? (
        <span className="text-muted-foreground">{PROFILE_GONE}</span>
      ) : (
        <Link href={`/admissions/${row.profile_id}`} target="_blank" rel="noopener noreferrer" className="underline">
          {row.full_name}
        </Link>
      )
    case "unit":
      return unitRef(row.unit_id, row.unit_name)
    case "choice":
      return consideredChoiceLabel(row.considered_choice)
    case "total":
      return scoreLabel(row.review_total)
    case "floor":
      return scoreLabel(row.floor_score)
    case "rank":
      return numberLabel(row.rank_in_major)
    case "ethnic":
      return ethnicPriorityLabel(row.ethnic_priority_state)
    case "reasons":
      return labelList(row.reason_codes, reasonLabel)
    case "seats":
      return withinSeatsLabel(row.within_seats)
    case "hints":
      return labelList(row.decision_hints, hintLabel)
    case "perChoice":
      return perChoiceSummary(row.per_choice)
    case "profileStatus":
      return profileStatusLabel(row.profile_status)
    case "docs":
      return documentGapsText(row)
    case "flags":
      return labelList(row.flags, flagLabel)
    default:
      return null
  }
}

/** Khoá có trong bản đếm của máy chủ (giữ thứ tự máy chủ) + giá trị đang chọn nếu lạ (mã lạ ⇒ trang rỗng ở máy chủ). */
function countOptions(counts: Record<string, number>, selected: string | undefined): { code: string; count: number | null }[] {
  const opts: { code: string; count: number | null }[] = Object.keys(counts).map((code) => ({ code, count: counts[code] }))
  if (selected !== undefined && !(selected in counts)) opts.push({ code: selected, count: null })
  return opts
}

/**
 * M5 thẻ "Kết quả" (thiết kế §3.6; đợt F4): bốn tab theo `summary.tab_counts` của E8 (số của CẢ lượt — không đổi theo bộ lọc), bảng dòng
 * E9 theo tab + bộ lọc (VÀ) + trang; trạng thái nằm trên URL (`reviewRunRowsHref`). Thứ tự dòng do máy chủ (không sắp lại). Ô
 * `null` ⇒ "—"; điểm là chuỗi máy chủ. Bấm "Xem" ⇒ ngăn chi tiết M6 (đúng dòng đã có, không gọi thêm). Tải lỗi (kể cả 429) ⇒ hiện LỖI,
 * không vẽ dòng cũ. Chỉ dùng cho lượt `done` (màn cha quyết theo `status` máy chủ).
 */
export function ReviewRunResults({
  sessionId,
  runId,
  run,
  filters,
}: {
  sessionId: number
  runId: number
  run: ReviewRun
  filters: ReviewRunRowFilters
}) {
  const router = useRouter()
  const tabs = tabCountEntries(run.summary?.tab_counts)
  const selectedTab = filters.tab ?? tabs[0]?.tab
  const q = useReviewRunRows(sessionId, runId, {
    tab: selectedTab,
    offering_academic_info_id: filters.majorId,
    reason_code: filters.reason,
    flag: filters.flag,
    page: filters.page,
    page_size: filters.pageSize,
  })
  const [openProfileId, setOpenProfileId] = useState<number | null>(null)
  const go = (next: ReviewRunRowFilters) => router.replace(reviewRunRowsHref(sessionId, runId, next))
  const setFilter = (patch: Partial<ReviewRunRowFilters>) => go({ ...filters, tab: selectedTab, ...patch, page: 1 })

  // Thiết kế §3.6: trang vượt cuối ⇒ `items: []` ⇒ quay về trang cuối (số trang của máy chủ).
  const lastPage = q.data && !q.isPlaceholderData ? q.data.total_pages : 0
  const beyondLast = lastPage > 0 && filters.page > lastPage
  useEffect(() => {
    if (beyondLast) router.replace(reviewRunRowsHref(sessionId, runId, { ...filters, tab: selectedTab, page: lastPage }))
  }, [beyondLast, lastPage, filters, router, runId, selectedTab, sessionId])

  const majors = (run.quota_view?.majors ?? []).filter((m) => m.candidates > 0)
  const reasons = countOptions(run.summary?.reason_counts ?? {}, filters.reason)
  const flags = countOptions(run.summary?.flag_counts ?? {}, filters.flag)
  const filtering = filters.majorId !== undefined || filters.reason !== undefined || filters.flag !== undefined
  const columns = (selectedTab !== undefined ? TAB_COLUMNS[selectedTab] : undefined) ?? DEFAULT_COLUMNS

  let body: ReactNode
  if (q.isError) {
    body = (
      <div className="space-y-2">
        <ReviewErrorAlert testId="kq-loi" message={describeReviewSessionError(q.error, "read").message} />
        <Button variant="outline" size="sm" onClick={() => void q.refetch()} disabled={q.isFetching} data-testid="kq-tai-lai">
          <RefreshCw className="mr-1 h-4 w-4" />
          Tải lại
        </Button>
      </div>
    )
  } else if (!q.data) {
    body = (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="kq-dang-tai">
        <Loader2 className="h-4 w-4 animate-spin" /> {RESULTS_LOADING}
      </p>
    )
  } else {
    const page = q.data
    const openRow = page.items.find((r) => r.profile_id === openProfileId) ?? null
    body = (
      <div className="space-y-2">
        {q.isPlaceholderData ? (
          <p className="text-sm text-muted-foreground" data-testid="kq-dang-tai-trang">
            {RESULTS_PAGE_LOADING}
          </p>
        ) : null}
        {page.items.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="kq-rong">
            {RESULTS_EMPTY}
          </p>
        ) : (
          <Table data-testid="kq-bang">
            <TableHeader>
              <TableRow>
                {columns.map((c) => (
                  <TableHead key={c}>{COL_TITLE[c]}</TableHead>
                ))}
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {page.items.map((r) => (
                <TableRow key={r.profile_id} data-testid={`dong-${r.profile_id}`}>
                  {columns.map((c) => (
                    <TableCell key={c} data-testid={`dong-${r.profile_id}-${c}`}>
                      {cell(r, c)}
                    </TableCell>
                  ))}
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => setOpenProfileId(r.profile_id)} data-testid={`dong-${r.profile_id}-xem`}>
                      {RESULTS_VIEW_ROW}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {page.total_pages > 1 ? (
          <div className="flex items-center justify-end gap-2 text-sm" data-testid="kq-phan-trang">
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page <= 1}
              onClick={() => go({ ...filters, tab: selectedTab, page: filters.page - 1 })}
              data-testid="kq-trang-truoc"
            >
              Trang trước
            </Button>
            <span data-testid="kq-trang-hien-tai">
              Trang {page.page} / {page.total_pages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={filters.page >= page.total_pages}
              onClick={() => go({ ...filters, tab: selectedTab, page: filters.page + 1 })}
              data-testid="kq-trang-sau"
            >
              Trang sau
            </Button>
          </div>
        ) : null}
        <ReviewRowDrawer row={openRow} majors={run.quota_view?.majors ?? []} onClose={() => setOpenProfileId(null)} />
      </div>
    )
  }

  return (
    <section className="space-y-3" data-testid="kq">
      <div className="flex flex-wrap gap-2" data-testid="kq-tab">
        {tabs.map((t) => (
          <Button
            key={t.tab}
            variant={t.tab === selectedTab ? "default" : "outline"}
            size="sm"
            aria-pressed={t.tab === selectedTab}
            onClick={() => go({ ...filters, tab: t.tab, page: 1 })}
            data-testid={`kq-tab-${t.tab}`}
          >
            {t.label} <span className="ml-1 tabular-nums">{t.count}</span>
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-3" data-testid="kq-bo-loc">
        <div className="w-64 space-y-1">
          <Label htmlFor="kq-loc-nganh">Ngành được xếp</Label>
          <select
            id="kq-loc-nganh"
            data-testid="kq-loc-nganh"
            className={SELECT_CLASS}
            value={filters.majorId ?? ""}
            onChange={(e) => setFilter({ majorId: e.target.value ? Number(e.target.value) : undefined })}
          >
            <option value="">{RESULTS_ALL}</option>
            {majors.map((m) => (
              <option key={m.offering_academic_info_id} value={m.offering_academic_info_id}>
                {`${majorLabel(m.major_code, m.major_name)} · ${m.offering_type ?? "—"}`}
              </option>
            ))}
          </select>
        </div>
        <div className="w-64 space-y-1">
          <Label htmlFor="kq-loc-ly-do">Lý do</Label>
          <select
            id="kq-loc-ly-do"
            data-testid="kq-loc-ly-do"
            className={SELECT_CLASS}
            value={filters.reason ?? ""}
            onChange={(e) => setFilter({ reason: e.target.value || undefined })}
          >
            <option value="">{RESULTS_ALL}</option>
            {reasons.map((o) => (
              <option key={o.code} value={o.code}>
                {o.count === null ? reasonLabel(o.code) : `${reasonLabel(o.code)} (${o.count})`}
              </option>
            ))}
          </select>
        </div>
        <div className="w-64 space-y-1">
          <Label htmlFor="kq-loc-co">Cờ</Label>
          <select
            id="kq-loc-co"
            data-testid="kq-loc-co"
            className={SELECT_CLASS}
            value={filters.flag ?? ""}
            onChange={(e) => setFilter({ flag: e.target.value || undefined })}
          >
            <option value="">{RESULTS_ALL}</option>
            {flags.map((o) => (
              <option key={o.code} value={o.code}>
                {o.count === null ? flagLabel(o.code) : `${flagLabel(o.code)} (${o.count})`}
              </option>
            ))}
          </select>
        </div>
        <div className="w-28 space-y-1">
          <Label htmlFor="kq-co-trang">Mỗi trang</Label>
          <select
            id="kq-co-trang"
            data-testid="kq-co-trang"
            className={SELECT_CLASS}
            value={filters.pageSize}
            onChange={(e) => setFilter({ pageSize: Number(e.target.value) as RowPageSize })}
          >
            {ROW_PAGE_SIZES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        {filtering && q.data && !q.isPlaceholderData ? (
          <span className="text-sm text-muted-foreground" data-testid="kq-dang-loc">
            {resultsFiltered(q.data.total)}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">{RESULTS_MAJOR_FILTER_HINT}</p>

      {body}
    </section>
  )
}
