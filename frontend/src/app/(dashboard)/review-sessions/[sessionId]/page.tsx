// src/app/(dashboard)/review-sessions/[sessionId]/page.tsx
/**
 * /review-sessions/{id} — GĐ2-B M2: chi tiết lần xét + thanh nút theo `available_actions` + huỷ (M7). Ngoài `/admin/*` như M1.
 * URL chỉ mang id lần xét; id kiểm DẠNG ở đây (số nguyên dương, tối đa 9 chữ số — trong miền `int4` của máy chủ), sai ⇒ 404 của
 * Next. Có tồn tại / được xem hay không là việc của máy chủ (404 / 403 ⇒ màn báo câu §5).
 */
import { Suspense } from "react"
import { notFound } from "next/navigation"

import { ReviewSessionDetailClient } from "../_components/ReviewSessionDetailClient"

// Tham số giữ chỗ cho bước kiểm build của Next.js 16 cacheComponents (như admin/council-documents/[setId], finance/fees/[feeId]).
export function generateStaticParams() {
  return [{ sessionId: "__placeholder__" }]
}

interface PageProps {
  params: Promise<{ sessionId: string }>
}

export default function ReviewSessionDetailPage(props: PageProps) {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Đang tải…</p>}>
      <SessionDetail {...props} />
    </Suspense>
  )
}

async function SessionDetail({ params }: PageProps) {
  const { sessionId } = await params
  if (!/^[1-9][0-9]{0,8}$/.test(sessionId)) {
    notFound()
  }
  return <ReviewSessionDetailClient sessionId={Number(sessionId)} />
}
