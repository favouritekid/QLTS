// src/app/(dashboard)/finance/fees/page.tsx
/**
 * Fee List Page (Server Component)
 *
 * Lists all fees with filtering and search.
 * Supports profile_id query param for cross-reference from Admissions.
 */

import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { FeeListClient } from "./_components/FeeListClient"

/**
 * Loading skeleton for fee list
 */
function FeeListLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div className="space-y-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-4 w-48" />
        </div>
        <Skeleton className="h-10 w-32" />
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-10 w-32" />
        <Skeleton className="h-10 w-32" />
      </div>

      {/* Table */}
      <div className="flex-1">
        <Skeleton className="h-full w-full rounded-lg" />
      </div>
    </div>
  )
}

/**
 * Fee List Page
 */
export default function FeesPage() {
  return (
    <Suspense fallback={<FeeListLoading />}>
      <FeeListClient />
    </Suspense>
  )
}
