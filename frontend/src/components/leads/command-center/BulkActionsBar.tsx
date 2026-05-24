// src/components/leads/command-center/BulkActionsBar.tsx
/**
 * BulkActionsBar - Floating action bar for bulk operations
 * 
 * Appears when multiple leads are selected, providing quick access to:
 * - Bulk assign to officer
 * - Bulk change pipeline stage
 * - Bulk export to Excel
 * - Bulk delete
 */

"use client";

import React from "react";
import {
  UserPlus,
  Layers,
  Download,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Lead } from "@/types/lead.types";

// =============================================================================
// TYPES
// =============================================================================

interface BulkActionsBarProps {
  selectedLeads: Lead[];
  onClearSelection: () => void;
  onBulkAssign: (leads: Lead[]) => void;
  onBulkChangeStage: (leads: Lead[]) => void;
  onBulkExport: (leads: Lead[]) => void;
  onBulkDelete: (leads: Lead[]) => void;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function BulkActionsBar({
  selectedLeads,
  onClearSelection,
  onBulkAssign,
  onBulkChangeStage,
  onBulkExport,
  onBulkDelete,
}: BulkActionsBarProps) {
  const count = selectedLeads.length;

  if (count === 0) return null;

  return (
    <div
      className={cn(
        "fixed bottom-6 left-1/2 z-50 -translate-x-1/2",
        "animate-in slide-in-from-bottom-4 fade-in-0 duration-200",
        "bg-background/95 supports-[backdrop-filter]:bg-background/80 backdrop-blur",
        "flex flex-wrap items-center justify-center gap-3 rounded-lg border px-4 py-3 shadow-lg",
        "max-w-[calc(100vw-1rem)]"
      )}
    >
      {/* Selection count */}
      <div className="flex items-center gap-2">
        <span className="bg-primary text-primary-foreground flex h-6 min-w-[24px] items-center justify-center rounded-full px-2 text-xs font-medium">
          {count}
        </span>
        <span className="text-sm font-medium">lead đã chọn</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClearSelection}
          className="h-11 w-11 sm:h-6 sm:w-6 p-0"
          aria-label="Bỏ chọn tất cả"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Divider */}
      <div className="bg-border h-6 w-px" />

      {/* Actions */}
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onBulkAssign(selectedLeads)}
          className="h-11 sm:h-8 gap-1.5"
        >
          <UserPlus className="h-4 w-4" />
          Gán cán bộ
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onBulkChangeStage(selectedLeads)}
          className="h-11 sm:h-8 gap-1.5"
        >
          <Layers className="h-4 w-4" />
          Đổi giai đoạn
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onBulkExport(selectedLeads)}
          className="h-11 sm:h-8 gap-1.5"
        >
          <Download className="h-4 w-4" />
          Xuất
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onBulkDelete(selectedLeads)}
          className="h-11 sm:h-8 gap-1.5 text-error-600 hover:text-error-700"
        >
          <Trash2 className="h-4 w-4" />
          Xóa
        </Button>
      </div>
    </div>
  );
}

export default BulkActionsBar;
