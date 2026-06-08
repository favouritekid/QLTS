import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { OverpaymentListClient } from "./_components/OverpaymentListClient"

function Loading() {
  return (
    <div className="p-4 sm:p-6 space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-96 rounded-lg" />
    </div>
  )
}

export default function OverpaymentsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <OverpaymentListClient />
    </Suspense>
  )
}
