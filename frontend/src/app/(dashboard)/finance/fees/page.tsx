// src/app/(dashboard)/finance/fees/page.tsx
/**
 * Folded into the "Thu học phí" workspace (PR2): fees are managed inside the
 * profile drawer (Phí section) + "+ Tính phí". This route redirects to the
 * workspace, preserving any query (e.g. ?profile_id= from Admissions) so old
 * links / bookmarks keep working. The per-fee detail route (/finance/fees/[id])
 * is untouched.
 */

import { redirect } from "next/navigation"

import { legacyFeesRedirectTarget } from "./redirect-target"

export default async function FeesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const sp = await searchParams
  redirect(legacyFeesRedirectTarget(sp))
}
