// src/app/(dashboard)/admin/council-documents/[setId]/page.tsx
import { Suspense } from "react"
import { notFound } from "next/navigation"

import { docBuoc } from "../_components/buoc"
import { CouncilSetDetailClient } from "../_components/CouncilSetDetailClient"

// Tham số giữ chỗ cho bước kiểm build của Next.js 16 cacheComponents (như finance/fees/[feeId]).
export function generateStaticParams() {
  return [{ setId: "__placeholder__" }]
}

interface PageProps {
  params: Promise<{ setId: string }>
  searchParams: Promise<{ buoc?: string | string[] }>
}

/**
 * Chi tiết một bộ văn bản Hội đồng. URL chỉ mang id bộ và TÊN BƯỚC (`?buoc=tai|doi-chieu|ghi-nhan`) — không mang
 * dữ liệu cá nhân. Tên bước đọc Ở ĐÂY (máy chủ) và kiểm theo danh sách đóng; client không đọc query string.
 *
 * `params` / `searchParams` là dữ liệu lúc chạy ⇒ chờ chúng BÊN TRONG `<Suspense>` (cacheComponents của Next 16 không
 * cho truy cập dữ liệu lúc chạy ngoài Suspense).
 */
export default function CouncilSetDetailPage(props: PageProps) {
  return (
    <Suspense fallback={<p className="text-muted-foreground">Đang tải…</p>}>
      <ChiTietBo {...props} />
    </Suspense>
  )
}

async function ChiTietBo({ params, searchParams }: PageProps) {
  const { setId } = await params
  const { buoc } = await searchParams
  if (setId === "__placeholder__" || !/^[1-9]\d{0,17}$/.test(setId)) {
    notFound()
  }
  return <CouncilSetDetailClient setId={Number(setId)} buocBanDau={docBuoc(buoc)} />
}
