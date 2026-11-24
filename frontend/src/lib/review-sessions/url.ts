/**
 * GĐ2-B M1 — trạng thái bộ lọc của danh sách lần xét nằm trên URL (thiết kế §3, `/review-sessions?nam=&trang-thai=&trang=`):
 * MỘT nguồn — trang đọc `searchParams`, thành phần chỉ nhận giá trị đã đọc và đổi URL khi người dùng đổi bộ lọc.
 */
import {
  readChoiceSearchParam,
  readPageSearchParam,
  readYearSearchParam,
  type PageSearchParams,
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
