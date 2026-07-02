import { Suspense } from "react"
import { notFound } from "next/navigation"
import type { Metadata } from "next"

import { SmsLandingClient } from "@/components/sms/SmsLandingClient"

// Trang landing công khai mang bearer code (§19) — KHÔNG cho index.
export const metadata: Metadata = {
  title: "Thông tin tuyển sinh",
  robots: { index: false, follow: false },
}

// Placeholder cho Next.js build validation; code thật xử lý runtime.
export function generateStaticParams() {
  return [{ code: "__placeholder__" }]
}

export default async function SmsLandingPage({
  params,
}: {
  params: Promise<{ code: string }>
}) {
  const { code } = await params

  if (code === "__placeholder__") {
    notFound()
  }

  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50" />}>
      <SmsLandingClient code={code} />
    </Suspense>
  )
}
