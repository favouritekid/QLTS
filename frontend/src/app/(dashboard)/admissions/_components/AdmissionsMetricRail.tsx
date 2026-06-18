// src/app/(dashboard)/admissions/_components/AdmissionsMetricRail.tsx
/**
 * Metric rail — dải chỉ số liền mạch thay 6 StatCard rời.
 * Kỹ thuật seamless: container `bg-border` + `gap-px`, mỗi ô `bg-card` →
 * khe 1px lộ màu border làm hairline (responsive, không cần border-math).
 * Thuần trình bày; AdmissionsClient build `items` từ useAdmissionStats.
 */

"use client"

import { TrendingUp } from "lucide-react"
import { cn } from "@/lib/utils"

export interface MetricItem {
  key: string
  label: string
  value: string
  /** Tailwind class màu chấm accent (literal static). */
  dot: string
  trend?: boolean
}

export function AdmissionsMetricRail({ items }: { items: MetricItem[] }) {
  if (items.length === 0) return null
  return (
    <section
      aria-label="Chỉ số tuyển sinh"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border shadow-xs sm:grid-cols-3 lg:grid-cols-6"
    >
      {items.map((m) => (
        <div key={m.key} className="min-w-0 bg-card p-3 sm:p-5">
          <div className="flex items-baseline gap-1.5">
            <span className="font-display text-xl font-semibold tracking-tight tabular-nums sm:text-2xl">{m.value}</span>
            {m.trend && <TrendingUp className="size-4 text-emerald-600" aria-hidden="true" />}
          </div>
          <div className="mt-1.5 flex items-center gap-1.5">
            <span className={cn("size-1.5 shrink-0 rounded-full", m.dot)} />
            <span className="truncate text-xs text-muted-foreground">{m.label}</span>
          </div>
        </div>
      ))}
    </section>
  )
}
