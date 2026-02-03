// src/app/(dashboard)/finance/page.tsx
/**
 * Finance Dashboard Page (Server Component)
 *
 * Shows finance overview with key metrics:
 * - Pending payments count
 * - Overdue invoices
 * - Today's collections
 * - Monthly collections
 */

import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { FinanceDashboardClient } from "./_components/FinanceDashboardClient"

/**
 * Loading skeleton for dashboard
 */
function DashboardLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-72" />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-lg" />
        ))}
      </div>

      {/* Quick actions and recent */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Skeleton className="h-64 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    </div>
  )
}

/**
 * Finance Dashboard Page
 */
export default function FinanceDashboardPage() {
  return (
    <Suspense fallback={<DashboardLoading />}>
      <FinanceDashboardClient />
    </Suspense>
  )
}
