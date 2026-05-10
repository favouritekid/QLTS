/**
 * QuotaMatrixOverview — Phase 3 hub cấu hình quota (Phase 2 v8.2 PR-2D.1 v3).
 *
 * Architecture (locked design Pass 14):
 *   Toggle [Theo ngành (default)] | [Ma trận toàn cảnh]
 *     ├─ ByMajorView    : 1 ngành chọn → matrix [method × đợt], cell = path exact
 *     └─ GlobalMatrixView: all ngành × đợt, cell = aggregate
 *
 *   Click cell → Drawer (read-only matrix, edit ở drawer):
 *     ├─ Ma trận toàn cảnh: cell → AggregateDrawer → PathDetailDrawer
 *     └─ Theo ngành: cell → PathDetailDrawer (1-step skip aggregate)
 *
 * Cell tiết chế (3 dòng): "Admit/Annual" + "Submit cap" + "Status"
 * KHÔNG inline edit. Drawer là configurator.
 */
"use client"

import { ChevronLeft, Copy, LayoutGrid, List } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"

import { ByMajorView } from "./QuotaMatrix/ByMajorView"
import { ClonePathsDialog } from "./QuotaMatrix/ClonePathsDialog"
import { GlobalMatrixView } from "./QuotaMatrix/GlobalMatrixView"

interface Props {
  academicYear: number
  onYearChange: (year: number) => void
  onBack: () => void
}

type ViewMode = "by-major" | "global"

export function QuotaMatrixOverview({ academicYear, onYearChange, onBack }: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>("by-major")
  const [cloneOpen, setCloneOpen] = useState(false)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ChevronLeft className="h-4 w-4 mr-1" aria-hidden="true" />
          Quay lại
        </Button>
        <h2 className="text-xl font-semibold font-display text-pretty">
          Cấu hình chỉ tiêu tuyển sinh
        </h2>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto"
          onClick={() => setCloneOpen(true)}
        >
          <Copy className="h-4 w-4 mr-1.5" aria-hidden="true" />
          Sao chép đợt
        </Button>
      </div>

      {/* Toggle */}
      <div
        role="tablist"
        aria-label="Chế độ xem ma trận"
        className="flex items-center gap-1 bg-muted rounded-lg p-1 w-fit"
      >
        <Button
          role="tab"
          aria-selected={viewMode === "by-major"}
          variant={viewMode === "by-major" ? "default" : "ghost"}
          size="sm"
          onClick={() => setViewMode("by-major")}
        >
          <List className="h-4 w-4 mr-1.5" aria-hidden="true" />
          Theo ngành
        </Button>
        <Button
          role="tab"
          aria-selected={viewMode === "global"}
          variant={viewMode === "global" ? "default" : "ghost"}
          size="sm"
          onClick={() => setViewMode("global")}
        >
          <LayoutGrid className="h-4 w-4 mr-1.5" aria-hidden="true" />
          Ma trận toàn cảnh
        </Button>
      </div>

      {cloneOpen && (
        <ClonePathsDialog
          academicYear={academicYear}
          onClose={() => setCloneOpen(false)}
        />
      )}

      {viewMode === "by-major" ? (
        <ByMajorView academicYear={academicYear} onYearChange={onYearChange} />
      ) : (
        <GlobalMatrixView academicYear={academicYear} onYearChange={onYearChange} />
      )}
    </div>
  )
}
