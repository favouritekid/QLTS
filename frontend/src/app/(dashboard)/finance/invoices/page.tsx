// src/app/(dashboard)/finance/invoices/page.tsx
/**
 * Invoice List Page (Server Component)
 *
 * Lists all invoices with filtering and search.
 * Supports fee_id and status query params for filtering.
 */

import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { InvoiceListClient } from "./_components/InvoiceListClient"

/**
 * Loading skeleton for invoice list
 */
function InvoiceListLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div className="space-y-2">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-4 w-56" />
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-10 w-40" />
      </div>

      {/* Table */}
      <div className="flex-1">
        <Skeleton className="h-full w-full rounded-lg" />
      </div>
    </div>
  )
}

/**
 * Invoice List Page
 */
export default function InvoicesPage() {
  return (
    <Suspense fallback={<InvoiceListLoading />}>
      <InvoiceListClient />
    </Suspense>
  )
}
