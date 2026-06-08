import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { RefundListClient } from "./_components/RefundListClient"

function Loading() {
  return (
    <div className="p-4 sm:p-6 space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-96 rounded-lg" />
    </div>
  )
}

export default function RefundsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <RefundListClient />
    </Suspense>
  )
}
