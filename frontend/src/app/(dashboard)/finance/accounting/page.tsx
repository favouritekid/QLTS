// src/app/(dashboard)/finance/accounting/page.tsx
/**
 * Accounting Period Management Page (Server Component)
 *
 * Manage accounting periods - create, close, and view summary.
 * Admin-only functionality for financial period management.
 */

import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { AccountingPeriodClient } from "./_components/AccountingPeriodClient"

/**
 * Loading skeleton for accounting periods
 */
function AccountingLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div className="space-y-2">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-4 w-48" />
        </div>
        <Skeleton className="h-10 w-32" />
      </div>

      {/* Current Period Card */}
      <Skeleton className="h-32 w-full rounded-lg" />

      {/* Filters */}
      <div className="flex gap-2">
        <Skeleton className="h-10 w-48" />
      </div>

      {/* Table */}
      <div className="flex-1">
        <Skeleton className="h-full w-full rounded-lg" />
      </div>
    </div>
  )
}

/**
 * Accounting Period Page
 */
export default function AccountingPage() {
  return (
    <Suspense fallback={<AccountingLoading />}>
      <AccountingPeriodClient />
    </Suspense>
  )
}
