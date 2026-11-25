/**
 * GĐ2-B M1 — trạng thái bộ lọc của danh sách lần xét nằm trên URL (thiết kế §3, `/review-sessions?nam=&trang-thai=&trang=`):
 * MỘT nguồn — trang đọc `searchParams`, thành phần chỉ nhận giá trị đã đọc và đổi URL khi người dùng đổi bộ lọc.
 */
import {
  readChoiceSearchParam,
  readPageSearchParam,
  readYearSearchParam,
  type PageSearchParams,
  type SearchParamValue,
} from "@/lib/utils/search-params"

import { SESSION_STATUS_FILTERS, type SessionStatusFilter } from "./messages"

export const REVIEW_SESSIONS_ROUTE = "/review-sessions"

export interface ReviewSessionListFilters {
  year?: number
  status?: SessionStatusFilter
  page: number
}

/** Đọc bộ lọc từ `searchParams` của trang. Sai dạng ⇒ bỏ (năm / trạng thái) hoặc về trang 1. */
export function readReviewSessionListFilters(sp: PageSearchParams): ReviewSessionListFilters {
  return {
    year: readYearSearchParam(sp["nam"]),
    status: readChoiceSearchParam(sp["trang-thai"], SESSION_STATUS_FILTERS),
    page: readPageSearchParam(sp["trang"]) ?? 1,
  }
}

/** URL của danh sách với bộ lọc (trang 1 không ghi lên URL). */
export function reviewSessionListHref(filters: ReviewSessionListFilters): string {
  const parts: string[] = []
  if (filters.year !== undefined) parts.push(`nam=${filters.year}`)
  if (filters.status !== undefined) parts.push(`trang-thai=${filters.status}`)
  if (filters.page > 1) parts.push(`trang=${filters.page}`)
  return parts.length ? `${REVIEW_SESSIONS_ROUTE}?${parts.join("&")}` : REVIEW_SESSIONS_ROUTE
}

export function reviewSessionHref(sessionId: number): string {
  return `${REVIEW_SESSIONS_ROUTE}/${sessionId}`
}

/** M5 — một lượt kiểm (thiết kế §3 `/review-sessions/{id}/runs/{runId}`); đường dẫn lấy từ `id` máy chủ trả. */
export function reviewRunHref(sessionId: number, runId: number): string {
  return `${reviewSessionHref(sessionId)}/runs/${runId}`
}

/**
 * Id trên URL — số nguyên dương, tối đa 9 chữ số (trong miền `int4` của máy chủ). CÙNG mẫu `[sessionId]/page.tsx` (F1, giữ
 * nguyên tệp ấy để không chạm neo biến thể F0 / F1 — NỢ: gộp về hằng này khi tệp F1 được sửa lần tới).
 */
export const REVIEW_ID_PARAM_PATTERN = /^[1-9][0-9]{0,8}$/

// ═══════════════════════ F4 — bốn tab kết quả của M5: trạng thái trên URL ═══════════════════════
/**
 * Thiết kế §3 M5: `/review-sessions/{id}/runs/{runId}?tab=&nganh=&ly-do=&co=&trang=` (+ `co-trang` [ĐX] — cỡ trang 50 / 100 / 200, thiết kế
 * §3.6). Trang đọc `searchParams` (MỘT nguồn), thành phần chỉ nhận giá trị đã đọc và đổi URL khi người dùng đổi. Chỉ kiểm DẠNG (mẫu
 * HĐ4 E9); giá trị có nghĩa hay không do máy chủ (mã lạ ⇒ trang rỗng; tab lạ ⇒ 422).
 */
export const ROW_PAGE_SIZES = [50, 100, 200] as const
export type RowPageSize = (typeof ROW_PAGE_SIZES)[number]
const ROW_TAB_PATTERN = /^[a-z_]{1,40}$/
/** HĐ4 E9 `reason_code`: `^[A-Za-z0-9_:]+$`, 1–100. */
const ROW_REASON_PATTERN = /^[A-Za-z0-9_:]{1,100}$/
/** HĐ4 E9 `flag`: `^[a-z0-9_]+$`, 1–100. */
const ROW_FLAG_PATTERN = /^[a-z0-9_]{1,100}$/

export interface ReviewRunRowFilters {
  /** `undefined` ⇒ màn chọn tab đầu tiên máy chủ trả trong `tab_counts` */
  tab?: string
  /** `offering_academic_info_id` của NV được xếp */
  majorId?: number
  reason?: string
  flag?: string
  page: number
  pageSize: RowPageSize
}

function readPattern(value: SearchParamValue, pattern: RegExp): string | undefined {
  return typeof value === "string" && pattern.test(value) ? value : undefined
}

export function readReviewRunRowFilters(sp: PageSearchParams): ReviewRunRowFilters {
  const size = readChoiceSearchParam(sp["co-trang"], ROW_PAGE_SIZES.map(String))
  const major = readPattern(sp["nganh"], REVIEW_ID_PARAM_PATTERN)
  return {
    tab: readPattern(sp["tab"], ROW_TAB_PATTERN),
    majorId: major === undefined ? undefined : Number(major),
    reason: readPattern(sp["ly-do"], ROW_REASON_PATTERN),
    flag: readPattern(sp["co"], ROW_FLAG_PATTERN),
    page: readPageSearchParam(sp["trang"]) ?? 1,
    pageSize: size === undefined ? 50 : (Number(size) as RowPageSize),
  }
}

/** URL của M5 với bộ lọc (trang 1 / cỡ 50 không ghi lên URL). */
export function reviewRunRowsHref(sessionId: number, runId: number, f: ReviewRunRowFilters): string {
  const parts: string[] = []
  if (f.tab !== undefined) parts.push(`tab=${encodeURIComponent(f.tab)}`)
  if (f.majorId !== undefined) parts.push(`nganh=${f.majorId}`)
  if (f.reason !== undefined) parts.push(`ly-do=${encodeURIComponent(f.reason)}`)
  if (f.flag !== undefined) parts.push(`co=${encodeURIComponent(f.flag)}`)
  if (f.page > 1) parts.push(`trang=${f.page}`)
  if (f.pageSize !== 50) parts.push(`co-trang=${f.pageSize}`)
  const base = reviewRunHref(sessionId, runId)
  return parts.length ? `${base}?${parts.join("&")}` : base
}
