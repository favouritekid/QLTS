/**
 * Admin — Quản lý KV theo Xã (vn_commune_area_map) — PR-A.
 *
 * Thin Suspense wrapper. Admin auth enforced by BE (`require_admin` trên mọi
 * endpoint) + nav role filter (`roles:["admin"]`).
 */
import { Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"

import { CommuneKvClient } from "./_components/CommuneKvClient"

export default function CommuneKvPage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto space-y-4 p-6">
          <Skeleton className="h-10 w-1/3" />
          <Skeleton className="h-[500px] w-full" />
        </div>
      }
    >
      <CommuneKvClient />
    </Suspense>
  )
}
