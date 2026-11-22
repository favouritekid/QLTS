/**
 * Admin — Ghép trường THCS (owner 22-11): gom tên trường THCS gõ tay trong lịch sử
 * học hồ sơ, ghép với trường trong danh mục (hoặc tạo trường mã nội bộ NB), xem
 * trước lượt áp ghép. Admin-only (BE require_admin + nav role filter).
 */
import { Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"

import { ThcsMappingClient } from "./_components/ThcsMappingClient"

export default function ThcsSchoolMappingPage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto space-y-4 p-6">
          <Skeleton className="h-10 w-1/3" />
          <Skeleton className="h-[500px] w-full" />
        </div>
      }
    >
      <ThcsMappingClient />
    </Suspense>
  )
}
