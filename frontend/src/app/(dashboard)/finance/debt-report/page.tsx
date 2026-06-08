import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { DebtReportClient } from "./_components/DebtReportClient"

function Loading() {
  return (
    <div className="p-4 sm:p-6 space-y-4">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((item) => (
          <Skeleton key={item} className="h-24 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-96 rounded-lg" />
    </div>
  )
}

export default function DebtReportPage() {
  return (
    <Suspense fallback={<Loading />}>
      <DebtReportClient />
    </Suspense>
  )
}
