/**
 * Admin — Quản lý Trường THPT (vn_school + KV assignment) — PR-B.
 *
 * Thin Suspense wrapper. Admin auth = BE require_admin + nav role filter.
 */
import { Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"

import { SchoolClient } from "./_components/SchoolClient"

export default function VnSchoolsPage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto space-y-4 p-6">
          <Skeleton className="h-10 w-1/3" />
          <Skeleton className="h-[500px] w-full" />
        </div>
      }
    >
      <SchoolClient />
    </Suspense>
  )
}
