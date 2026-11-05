// src/app/(dashboard)/admin/council-documents/[setId]/page.tsx
import { Suspense } from "react"
import { notFound } from "next/navigation"

import { CouncilSetDetailClient } from "../_components/CouncilSetDetailClient"

// Tham số giữ chỗ cho bước kiểm build của Next.js 16 cacheComponents (như finance/fees/[feeId]).
export function generateStaticParams() {
  return [{ setId: "__placeholder__" }]
}

interface PageProps {
  params: Promise<{ setId: string }>
}

/** Chi tiết một bộ văn bản Hội đồng. URL chỉ mang id bộ — không mang dữ liệu cá nhân. */
export default async function CouncilSetDetailPage({ params }: PageProps) {
  const { setId } = await params
  if (setId === "__placeholder__" || !/^[1-9]\d{0,17}$/.test(setId)) {
    notFound()
  }
  return (
    <Suspense fallback={<p className="text-muted-foreground">Đang tải…</p>}>
      <CouncilSetDetailClient setId={Number(setId)} />
    </Suspense>
  )
}
