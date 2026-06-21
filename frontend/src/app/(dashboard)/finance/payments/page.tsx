// src/app/(dashboard)/finance/payments/page.tsx
/**
 * Folded into the "Thu học phí" workspace (PR2): the payment maker-checker queue
 * is now the workspace "Chờ duyệt" tab. This route redirects there (preserving
 * any query) so old links / bookmarks keep working.
 */

import { redirect } from "next/navigation"

export default async function PaymentsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const sp = await searchParams
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(sp)) {
    if (typeof value === "string") params.set(key, value)
  }
  // Land on the verification queue tab by default.
  if (!params.has("tab")) params.set("tab", "pending")
  redirect(`/finance/invoices?${params.toString()}`)
}
