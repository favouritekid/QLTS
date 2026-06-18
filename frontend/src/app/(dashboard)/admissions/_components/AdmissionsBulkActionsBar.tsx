// src/app/(dashboard)/admissions/_components/AdmissionsBulkActionsBar.tsx
/**
 * AdmissionsBulkActionsBar - Floating action bar for bulk operations
 *
 * Appears when multiple admission profiles are selected, providing quick access to:
 * - Bulk approve
 * - Bulk reject
 * - Bulk assign to officer
 * - Export to CSV
 */

"use client"

import React from "react"
import { CheckCircle, XCircle, UserPlus, Download, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

// =============================================================================
// TYPES
// =============================================================================

interface AdmissionsBulkActionsBarProps {
  selectedCount: number
  onClearSelection: () => void
  onBulkApprove: () => void
  onBulkReject: () => void
  onBulkAssign: () => void
  onExport: () => void
  // Required — derived from per-row `available_actions` intersection.
  // Defaulting to `true` historically leaked admin/manager actions to
  // officers with no way to perform them (404 on submit).
  canApprove: boolean
  canReject: boolean
  canAssign: boolean
  isLoading?: boolean
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function AdmissionsBulkActionsBar({
  selectedCount,
  onClearSelection,
  onBulkApprove,
  onBulkReject,
  onBulkAssign,
  onExport,
  canApprove,
  canReject,
  canAssign,
  isLoading = false,
}: AdmissionsBulkActionsBarProps) {
  if (selectedCount === 0) return null

  return (
    <div
      className={cn(
        // Mobile: float above the bottom nav (z-[60]); desktop keeps bottom-6.
        "fixed bottom-[calc(var(--bottom-nav-height-safe)_+_0.5rem)] lg:bottom-6 left-1/2 z-50 -translate-x-1/2",
        "animate-in slide-in-from-bottom-4 fade-in-0 duration-200",
        "bg-background/95 supports-[backdrop-filter]:bg-background/80 backdrop-blur",
        "flex flex-wrap items-center gap-2 sm:gap-3 rounded-2xl border px-3 sm:px-4 py-2 sm:py-3 shadow-lg",
        "max-w-[95vw] sm:max-w-none"
      )}
    >
      {/* Selection count */}
      <div className="flex items-center gap-2">
        <span className="bg-primary text-primary-foreground flex h-6 min-w-[24px] items-center justify-center rounded-full px-2 text-xs font-medium">
          {selectedCount}
        </span>
        <span className="text-sm font-medium hidden sm:inline">hồ sơ đã chọn</span>
        <span className="text-sm font-medium sm:hidden">chọn</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClearSelection}
          aria-label="Bỏ chọn"
          className="h-10 w-10 touch-manipulation p-0 md:h-8 md:w-8"
          disabled={isLoading}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>

      {/* Divider */}
      <div className="bg-border h-6 w-px hidden sm:block" />

      {/* Actions */}
      <div className="flex items-center gap-1">
        {canApprove && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onBulkApprove}
            aria-label="Duyệt"
            className="h-10 touch-manipulation gap-1.5 text-success-600 hover:text-success-700 md:h-8"
            disabled={isLoading}
          >
            <CheckCircle className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">Duyệt</span>
          </Button>
        )}

        {canReject && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onBulkReject}
            aria-label="Từ chối"
            className="h-10 touch-manipulation gap-1.5 text-error-600 hover:text-error-700 md:h-8"
            disabled={isLoading}
          >
            <XCircle className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">Từ chối</span>
          </Button>
        )}

        {canAssign && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onBulkAssign}
            aria-label="Gán officer"
            className="h-10 touch-manipulation gap-1.5 md:h-8"
            disabled={isLoading}
          >
            <UserPlus className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">Gán officer</span>
          </Button>
        )}

        <Button
          variant="ghost"
          size="sm"
          onClick={onExport}
          aria-label="Xuất CSV"
          className="h-10 touch-manipulation gap-1.5 md:h-8"
          disabled={isLoading}
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          <span className="hidden sm:inline">Xuất CSV</span>
        </Button>
      </div>
    </div>
  )
}

export default AdmissionsBulkActionsBar
