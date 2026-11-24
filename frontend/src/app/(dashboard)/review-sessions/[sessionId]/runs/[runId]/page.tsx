// src/app/(dashboard)/review-sessions/[sessionId]/runs/[runId]/page.tsx
/**
 * /review-sessions/{id}/runs/{runId} — GĐ2-B M5: một lượt kiểm (đợt F3: đầu trang + "Chỉ tiêu tham khảo" + "Điểm sàn đã dùng"; bốn
 * tab kết quả ở F4). Ngoài `/admin/*` như M1 / M2. Hai id kiểm DẠNG ở đây (số nguyên dương, tối đa 9 chữ số), sai ⇒ 404 của Next.
 * Có tồn tại / được xem hay không là việc của máy chủ (404 / 403 ⇒ màn báo câu §5).
 */
import { Suspense } from "react"
import { notFound } from "next/navigation"

import { REVIEW_ID_PARAM_PATTERN, readReviewRunRowFilters } from "@/lib/review-sessions/url"
import type { PageSearchParams } from "@/lib/utils/search-params"

import { ReviewRunDetailClient } from "../../../_components/ReviewRunDetailClient"

// Tham số giữ chỗ cho bước kiểm build của Next.js 16 cacheComponents (khuôn `magic-link/[action]/[token]`).
export function generateStaticParams() {
  return [{ sessionId: "__placeholder__", runId: "__placeholder__" }]
}

/**
 * F4: bốn tab + bộ lọc + trang nằm trên URL (`?tab=&nganh=&ly-do=&co=&trang=&co-trang=`) — đọc Ở ĐÂY, chỉ nhận đúng dạng
 * (`readReviewRunRowFilters`); chờ BÊN TRONG `<Suspense>` (cacheComponents). Vắng `searchParams` ⇒ mặc định.
 */
interface PageProps {
  params: Promise<{ sessionId: string; runId: string }>
  searchParams?: Promise<PageSearchParams>
}

export default function ReviewRunDetailPage(props: PageProps) {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Đang tải…</p>}>
      <RunDetail {...props} />
    </Suspense>
  )
}

async function RunDetail({ params, searchParams }: PageProps) {
  const { sessionId, runId } = await params
  if (!REVIEW_ID_PARAM_PATTERN.test(sessionId) || !REVIEW_ID_PARAM_PATTERN.test(runId)) {
    notFound()
  }
  const filters = readReviewRunRowFilters(searchParams ? await searchParams : {})
  // `key` = cặp id: đổi sang lượt khác ⇒ dựng mới (thẻ con đang mở không mang sang). Đổi bộ lọc (cùng lượt) ⇒ GIỮ thành phần.
  return (
    <ReviewRunDetailClient
      key={`${sessionId}/${runId}`}
      sessionId={Number(sessionId)}
      runId={Number(runId)}
      filters={filters}
    />
  )
}
