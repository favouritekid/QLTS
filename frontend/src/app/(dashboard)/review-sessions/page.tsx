// src/app/(dashboard)/review-sessions/page.tsx
/**
 * /review-sessions — GĐ2-B M1: danh sách lần xét nháp + tạo lần xét (thiết kế giao diện GĐ2-B §3.2). Đường NGOÀI `/admin/*`
 * (KT-5 / R4): GĐ2-C mở màn này cho Ban thư ký, mà `proxy.ts` đẩy cán bộ khỏi `/admin/*` trước khi trang chạy. Ai xem / làm được
 * gì do MÁY CHỦ quyết (GĐ2-B: chỉ Admin); trang không kiểm vai.
 *
 * Bộ lọc nằm trên URL (`?nam=&trang-thai=&trang=`) — đọc Ở ĐÂY và chỉ nhận đúng dạng (`readReviewSessionListFilters`); sai dạng
 * ⇒ bỏ / về trang 1. `searchParams` là dữ liệu lúc chạy ⇒ chờ BÊN TRONG `<Suspense>` (cacheComponents của Next 16).
 */
import { Suspense } from "react"

import { readReviewSessionListFilters } from "@/lib/review-sessions/url"
import type { PageSearchParams } from "@/lib/utils/search-params"

import { ReviewSessionsListClient } from "./_components/ReviewSessionsListClient"

interface PageProps {
  searchParams: Promise<PageSearchParams>
}

export default function ReviewSessionsPage({ searchParams }: PageProps) {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Đang tải…</p>}>
      <ReviewSessionsFromUrl searchParams={searchParams} />
    </Suspense>
  )
}

async function ReviewSessionsFromUrl({ searchParams }: PageProps) {
  const filters = readReviewSessionListFilters(await searchParams)
  return <ReviewSessionsListClient filters={filters} />
}
