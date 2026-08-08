/**
 * Admin — Đồng bộ danh sách sang ký túc xá.
 *
 * Vỏ Suspense mỏng. Quyền do BE cưỡng chế (`require_admin` trên cả ba endpoint)
 * cộng bộ lọc vai ở navigation; trang này không tự kiểm quyền.
 */
import { Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"

import { DormSyncPanel } from "./_components/DormSyncPanel"

export default function DormSyncPage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto space-y-4 p-6">
          <Skeleton className="h-10 w-1/3" />
          <Skeleton className="h-[500px] w-full" />
        </div>
      }
    >
      <DormSyncPanel />
    </Suspense>
  )
}
