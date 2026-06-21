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

// Large-screen column count derived from item count so a 4-metric rail (finance)
// fills 4 columns instead of leaving gaps in a fixed 6-col grid, while the
// admissions 6-metric rail keeps its original `lg:grid-cols-6`. Literal classes
// (Tailwind JIT can't see computed strings).
const LG_COLS: Record<number, string> = {
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
  5: "lg:grid-cols-5",
  6: "lg:grid-cols-6",
}

// Mid-screen (sm/md, 640–1023px) column count chosen so the rail divides evenly
// and never leaves an orphan cell exposing the `bg-border` hairline. A 4-metric
// rail (finance) wraps 2×2 instead of 3+1; 3/5/6 keep 3 columns. Literal classes
// (Tailwind JIT can't see computed strings).
const SM_COLS: Record<number, string> = {
  3: "sm:grid-cols-3",
  4: "sm:grid-cols-2",
  5: "sm:grid-cols-3",
  6: "sm:grid-cols-3",
}

export function AdmissionsMetricRail({
  items,
  ariaLabel = "Chỉ số tuyển sinh",
}: {
  items: MetricItem[]
  /** Accessible label for the rail region. Defaults to the admissions label. */
  ariaLabel?: string
}) {
  if (items.length === 0) return null
  const lgCols = LG_COLS[items.length] ?? "lg:grid-cols-6"
  const smCols = SM_COLS[items.length] ?? "sm:grid-cols-3"
  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border shadow-xs",
        smCols,
        lgCols,
      )}
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
