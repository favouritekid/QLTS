// src/app/(dashboard)/finance/payments/page.tsx
/**
 * Payment Verification Queue Page (Server Component)
 *
 * Lists pending payments for Maker-Checker verification.
 * Managers/Admins verify payments created by Accountants.
 */

import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { PaymentListClient } from "./_components/PaymentListClient"

/**
 * Loading skeleton for payment list
 */
function PaymentListLoading() {
  return (
    <div className="h-full flex flex-col p-4 sm:p-6 space-y-4">
      {/* Header */}
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-64" />
      </div>

      {/* Stats */}
      <div className="flex gap-4">
        <Skeleton className="h-20 w-32 rounded-lg" />
        <Skeleton className="h-20 w-32 rounded-lg" />
      </div>

      {/* List */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[...Array(6)].map((_, i) => (
          <Skeleton key={i} className="h-52 rounded-lg" />
        ))}
      </div>
    </div>
  )
}

/**
 * Payment List Page
 */
export default function PaymentsPage() {
  return (
    <Suspense fallback={<PaymentListLoading />}>
      <PaymentListClient />
    </Suspense>
  )
}
