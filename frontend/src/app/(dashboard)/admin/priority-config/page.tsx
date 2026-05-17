/**
 * /admin/priority-config — Q9 #07 PR3 admin FE entry point.
 *
 * Admin-only quy chế config. Backend require_admin enforces auth so
 * the page itself stays a thin wrapper around the client orchestrator.
 */

import { Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"

import { PriorityConfigClient } from "./_components/PriorityConfigClient"

export default function PriorityConfigPage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto space-y-4 p-6">
          <Skeleton className="h-10 w-1/3" />
          <div className="grid gap-6 lg:grid-cols-2">
            <Skeleton className="h-[400px]" />
            <Skeleton className="h-[400px]" />
          </div>
        </div>
      }
    >
      <PriorityConfigClient />
    </Suspense>
  )
}
