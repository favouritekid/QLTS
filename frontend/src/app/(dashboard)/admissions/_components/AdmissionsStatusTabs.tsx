// src/app/(dashboard)/admissions/_components/AdmissionsStatusTabs.tsx
/**
 * Status tabs dạng gạch chân (editorial) thay pill nền. Dữ liệu tab + count
 * truyền từ AdmissionsClient (reuse ADMISSION_STATUS_TABS + tabCounts).
 */

"use client"

import { useEffect, useRef } from "react"
import { cn } from "@/lib/utils"

interface TabItem {
  key: string
  label: string
}

export function AdmissionsStatusTabs({
  tabs,
  activeTab,
  counts,
  onTabClick,
}: {
  tabs: readonly TabItem[]
  activeTab: string
  counts?: Record<string, number>
  onTabClick: (key: string) => void
}) {
  // Cuộn tab active vào tầm nhìn khi đổi bằng code (vd filter set activeTab sang
  // tab khuất phải) — block:nearest tránh cuộn dọc trang.
  const activeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    // optional-call: jsdom KHÔNG implement scrollIntoView → `?.()` no-op trong
    // test (tránh throw vỡ render), vẫn chạy thật trên trình duyệt.
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" })
  }, [activeTab])

  return (
    <div className="scroll-shadow-x min-w-0 snap-x overflow-x-auto border-b border-border">
      <div className="flex w-max items-center gap-1" role="tablist" aria-label="Lọc nhanh theo trạng thái">
        {tabs.map((t) => {
          const active = activeTab === t.key
          const count = counts?.[t.key]
          return (
            <button
              key={t.key}
              ref={active ? activeRef : undefined}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onTabClick(t.key)}
              className={cn(
                "relative snap-start touch-manipulation whitespace-nowrap px-3 py-3 text-sm font-medium transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="inline-flex items-center gap-1.5">
                {t.label}
                {count !== undefined && (
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-2xs tabular-nums",
                      active ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
                    )}
                  >
                    {count}
                  </span>
                )}
              </span>
              {active && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" />}
            </button>
          )
        })}
      </div>
    </div>
  )
}
