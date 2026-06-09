import { Suspense } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { ReopenRequestsInbox } from "./_components/ReopenRequestsInbox"

function Loading() {
  return (
    <div className="p-4 sm:p-6 space-y-4">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-96 rounded-lg" />
    </div>
  )
}

export default function ReopenRequestsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ReopenRequestsInbox />
    </Suspense>
  )
}
