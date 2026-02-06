// src/app/(dashboard)/finance/payments/return/page.tsx
import { Suspense } from "react"
import { PaymentReturnClient } from "./_components/PaymentReturnClient"
import { Skeleton } from "@/components/ui/skeleton"

export const metadata = {
  title: "Kết quả thanh toán - Finance",
  description: "Kết quả thanh toán online",
}

/**
 * Payment Return Page
 *
 * Handles the return from payment gateway after online payment.
 * Gateway sends query params: status, intent_id, reference, error, etc.
 */
export default function PaymentReturnPage() {
  return (
    <Suspense fallback={<PaymentReturnSkeleton />}>
      <PaymentReturnClient />
    </Suspense>
  )
}

function PaymentReturnSkeleton() {
  return (
    <div className="h-full flex flex-col items-center justify-center p-4 sm:p-6">
      <Skeleton className="h-16 w-16 rounded-full mb-6" />
      <Skeleton className="h-8 w-48 mb-2" />
      <Skeleton className="h-4 w-64 mb-8" />
      <Skeleton className="h-10 w-32" />
    </div>
  )
}
