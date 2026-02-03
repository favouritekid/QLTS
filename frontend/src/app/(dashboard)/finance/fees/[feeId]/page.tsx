// src/app/(dashboard)/finance/fees/[feeId]/page.tsx
/**
 * Fee Detail Page (Server Component)
 *
 * Shows comprehensive fee details with invoices and actions.
 */

import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { FeeDetailClient } from "./_components/FeeDetailClient"

interface PageProps {
  params: Promise<{ feeId: string }>
}

/**
 * Loading skeleton for fee detail
 */
function FeeDetailLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-6">
      {/* Back button */}
      <Skeleton className="h-8 w-24" />

      {/* Header */}
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-48" />
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>

      {/* Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Skeleton className="h-96 rounded-lg lg:col-span-2" />
        <Skeleton className="h-96 rounded-lg" />
      </div>
    </div>
  )
}

/**
 * Fee Detail Page
 */
export default async function FeeDetailPage({ params }: PageProps) {
  const { feeId } = await params

  return (
    <Suspense fallback={<FeeDetailLoading />}>
      <FeeDetailClient feeId={parseInt(feeId)} />
    </Suspense>
  )
}
