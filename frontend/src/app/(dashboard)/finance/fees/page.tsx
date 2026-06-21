// src/app/(dashboard)/finance/fees/page.tsx
/**
 * Folded into the "Thu học phí" workspace (PR2): fees are managed inside the
 * profile drawer (Phí section) + "+ Tính phí". This route redirects to the
 * workspace, preserving any query (e.g. ?profile_id= from Admissions) so old
 * links / bookmarks keep working. The per-fee detail route (/finance/fees/[id])
 * is untouched.
 */

import { redirect } from "next/navigation"

export default async function FeesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const sp = await searchParams
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(sp)) {
    if (typeof value !== "string") continue
    if (key === "profile_id") {
      // Old fee deep-links (FeeStatusLink / FeeCard) meant "show this profile's
      // fees" — now inside the drawer. Open it (?profile=), NOT the list filter
      // (?profile_id=, which the admission TuitionTab uses for a different intent).
      params.set("profile", value)
    } else if (key === "status") {
      // Old fees page status filter → workspace tab. The dashboard's pending-fees
      // CTA (status=pending) = awaiting collection = the "issued" (Chờ thu) tab.
      // NOT tab=pending — that key is the payment-queue sentinel.
      if (value === "pending") params.set("tab", "issued")
    } else {
      // tab, action=calculate, q, … pass through unchanged.
      params.set(key, value)
    }
  }
  const qs = params.toString()
  redirect(`/finance/invoices${qs ? `?${qs}` : ""}`)
}
