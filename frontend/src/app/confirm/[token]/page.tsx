import { Suspense } from "react"
import { notFound } from "next/navigation"
import type { Metadata } from "next"

import { ConfirmAdmissionForm } from "@/components/forms/ConfirmAdmissionForm"

export const metadata: Metadata = {
  title: "Xác nhận nhập học",
  description: "Xác nhận hồ sơ nhập học của bạn",
}

// Placeholder param for Next.js 16 cacheComponents build validation.
// Real tokens are handled at runtime — the placeholder route triggers
// notFound() so no build-time request is sent to the API.
export function generateStaticParams() {
  return [{ token: "__placeholder__" }]
}

export default async function ConfirmAdmissionPage({
  params,
}: {
  params: Promise<{ token: string }>
}) {
  const { token } = await params

  if (token === "__placeholder__") {
    notFound()
  }

  return (
    <div className="bg-muted/40 flex min-h-screen items-center justify-center p-4">
      <Suspense
        fallback={
          <div role="status" aria-live="polite" className="text-muted-foreground">
            Đang tải…
          </div>
        }
      >
        <ConfirmAdmissionForm token={token} />
      </Suspense>
    </div>
  )
}
