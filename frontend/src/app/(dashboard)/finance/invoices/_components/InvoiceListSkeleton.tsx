// src/app/(dashboard)/finance/invoices/_components/InvoiceListSkeleton.tsx
/**
 * Loading skeleton khớp row hóa đơn mới (monogram + danh tính 2 dòng + khoản thu
 * + tiền + status) để tránh first-paint giật. Desktop card-wrapped, mobile tiles.
 */

"use client"

import { Skeleton } from "@/components/ui/skeleton"

export function InvoiceListSkeleton() {
  return (
    <div className="space-y-3">
      {/* Desktop */}
      <div className="hidden rounded-2xl border border-border bg-card p-4 md:block">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 py-2.5">
            <Skeleton className="size-9 shrink-0 rounded-xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3.5 w-44" />
              <Skeleton className="h-3 w-28" />
            </div>
            <Skeleton className="hidden h-3.5 w-24 sm:block" />
            <Skeleton className="hidden h-5 w-20 rounded-full lg:block" />
            <div className="space-y-2 text-right">
              <Skeleton className="ml-auto h-3.5 w-24" />
              <Skeleton className="ml-auto h-3 w-16" />
            </div>
          </div>
        ))}
      </div>

      {/* Mobile */}
      <div className="space-y-2 md:hidden">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="rounded-2xl border border-l-2 border-border bg-card p-3">
            <div className="flex items-start gap-2.5">
              <Skeleton className="size-9 shrink-0 rounded-xl" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-36" />
                <Skeleton className="h-3 w-28" />
                <div className="flex items-center justify-between pt-1">
                  <Skeleton className="h-5 w-24" />
                  <Skeleton className="h-4 w-20 rounded-full" />
                </div>
                <Skeleton className="mt-2 h-9 w-full rounded-md" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
