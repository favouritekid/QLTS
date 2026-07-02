import { Suspense } from "react"
import { notFound } from "next/navigation"
import type { Metadata } from "next"

import { SmsProgramClient } from "@/components/sms/SmsProgramClient"

// Trang ngành công khai mang bearer code (§16.1) — KHÔNG cho index.
export const metadata: Metadata = {
  title: "Thông tin ngành tuyển sinh",
  robots: { index: false, follow: false },
}

export function generateStaticParams() {
  return [{ code: "__placeholder__", programId: "0" }]
}

export default async function SmsProgramPage({
  params,
}: {
  params: Promise<{ code: string; programId: string }>
}) {
  const { code, programId } = await params
  const majorProgramId = Number(programId)

  if (code === "__placeholder__" || !Number.isInteger(majorProgramId) || majorProgramId < 1) {
    notFound()
  }

  return (
    <Suspense fallback={<div className="min-h-screen bg-slate-50" />}>
      <SmsProgramClient code={code} majorProgramId={majorProgramId} />
    </Suspense>
  )
}
