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
    <div className="bg-muted/40 flex min-h-screen items-start justify-center p-4">
      <Suspense
        fallback={
          <div
            role="status"
            aria-live="polite"
            className="text-muted-foreground mt-16"
          >
            Đang tải…
          </div>
        }
      >
        <SmsProgramClient code={code} majorProgramId={majorProgramId} />
      </Suspense>
    </div>
  )
}
