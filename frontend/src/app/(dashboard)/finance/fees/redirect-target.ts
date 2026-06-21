// src/app/(dashboard)/finance/fees/redirect-target.ts
/**
 * Maps a legacy `/finance/fees` query onto the "Thu học phí" workspace
 * (`/finance/invoices`). Pure + exported so the param mapping is unit-tested
 * without Next's server-only `redirect()`. See `page.tsx`.
 */
export function legacyFeesRedirectTarget(
  sp: Record<string, string | string[] | undefined>,
): string {
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
  return `/finance/invoices${qs ? `?${qs}` : ""}`
}
