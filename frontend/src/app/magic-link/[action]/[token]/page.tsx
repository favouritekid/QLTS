import { Suspense } from "react"
import { notFound } from "next/navigation"
import type { Metadata } from "next"

import { MagicLinkConsumeForm } from "@/components/forms/MagicLinkConsumeForm"
import {
  magicLinkActionSchema,
  type MagicLinkAction,
} from "@/lib/zod/magic-link"

// Per-action page <title>. Falls back to a neutral title if Next.js
// renders the placeholder build route.
const PAGE_TITLE: Record<MagicLinkAction, string> = {
  confirm: "Xác nhận nhập học",
  submit: "Gửi hồ sơ tuyển sinh",
  resubmit: "Nộp lại hồ sơ",
  withdraw: "Rút hồ sơ tuyển sinh",
}

const PAGE_DESCRIPTION: Record<MagicLinkAction, string> = {
  confirm: "Xác nhận hồ sơ nhập học của bạn",
  submit: "Gửi hồ sơ tuyển sinh của bạn",
  resubmit: "Nộp lại hồ sơ sau khi đã chỉnh sửa",
  withdraw: "Xác nhận rút hồ sơ tuyển sinh",
}

// Token URL must not be indexed by search engines. Defense-in-depth —
// the URL only ships via email, but a leaked screenshot / copy-paste
// into a public channel must not show up in a crawler index.
const NOINDEX_ROBOTS = { index: false, follow: false } as const

export async function generateMetadata({
  params,
}: {
  params: Promise<{ action: string; token: string }>
}): Promise<Metadata> {
  const { action } = await params
  const parsed = magicLinkActionSchema.safeParse(action)
  if (!parsed.success) {
    return { title: "Liên kết không hợp lệ", robots: NOINDEX_ROBOTS }
  }
  return {
    title: PAGE_TITLE[parsed.data],
    description: PAGE_DESCRIPTION[parsed.data],
    robots: NOINDEX_ROBOTS,
  }
}

// Token URL pages must never be cached by Next.js / CDN / proxy: each
// request must hit the BE consume endpoint at request time so the
// freshness gates (used / locked / expired) reflect server state.
export const dynamic = "force-dynamic"

// Placeholder params for Next.js 16 cacheComponents build validation.
// Real {action, token} pairs are resolved at request time; the
// placeholder route triggers notFound() so no build-time API hit occurs.
export function generateStaticParams() {
  return [{ action: "__placeholder__", token: "__placeholder__" }]
}

export default async function MagicLinkConsumePage({
  params,
}: {
  params: Promise<{ action: string; token: string }>
}) {
  const { action, token } = await params

  if (action === "__placeholder__" || token === "__placeholder__") {
    notFound()
  }

  // Validate the URL action enum at page boundary — anything outside the
  // 4-value enum is a malformed link, fail closed with 404.
  const parsed = magicLinkActionSchema.safeParse(action)
  if (!parsed.success) {
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
        <MagicLinkConsumeForm action={parsed.data} token={token} />
      </Suspense>
    </div>
  )
}
