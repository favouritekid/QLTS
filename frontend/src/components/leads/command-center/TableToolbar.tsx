// src/components/leads/command-center/TableToolbar.tsx
/**
 * TableToolbar - Toolbar for table controls
 * 
 * Features:
 * - Compact/Normal view toggle
 * - Column visibility dropdown
 * - ✅ Option C: Keyboard shortcuts help
 */

"use client";

import React from "react";
import {
  AlignJustify,
  List,
  Columns,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { VisibilityState } from "@tanstack/react-table";
import { KeyboardShortcutsHelp } from "./KeyboardShortcutsHelp";

// =============================================================================
// TYPES
// =============================================================================

interface TableToolbarProps {
  isCompact: boolean;
  onCompactChange: (compact: boolean) => void;
  columnVisibility: VisibilityState;
  onColumnVisibilityChange: (columnId: string, isVisible: boolean) => void;
}

// Column config - order matters for display
const COLUMNS_CONFIG = [
  { id: "full_name", label: "Tên Lead" },
  { id: "phone", label: "Số điện thoại" },
  { id: "source", label: "Nguồn" },
  { id: "pipeline_stage", label: "Giai đoạn" },
  { id: "consultation_status", label: "Trạng thái TĐ" },
  { id: "assigned_officer", label: "Cán bộ" },
  { id: "created_at", label: "Ngày tạo" },
];

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function TableToolbar({
  isCompact,
  onCompactChange,
  columnVisibility,
  onColumnVisibilityChange,
}: TableToolbarProps) {
  // Count visible columns (default to visible if not in state)
  const visibleCount = COLUMNS_CONFIG.filter(
    (col) => columnVisibility[col.id] !== false
  ).length;

  return (
    <div className="flex items-center gap-2">
      <TooltipProvider delayDuration={300}>
        {/* Compact View Toggle */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onCompactChange(!isCompact)}
              className={cn(
                "h-8 w-8 p-0",
                isCompact && "bg-muted"
              )}
            >
              {isCompact ? (
                <List className="h-4 w-4" />
              ) : (
                <AlignJustify className="h-4 w-4" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {isCompact ? "Chế độ thường" : "Chế độ thu gọn"}
          </TooltipContent>
        </Tooltip>

        {/* Column Visibility */}
        <DropdownMenu>
          <Tooltip>
            <TooltipTrigger asChild>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 gap-1.5"
                >
                  <Columns className="h-4 w-4" />
                  <span className="text-xs">{visibleCount}</span>
                </Button>
              </DropdownMenuTrigger>
            </TooltipTrigger>
            <TooltipContent>Ẩn/hiện cột</TooltipContent>
          </Tooltip>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel>Hiển thị cột</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {COLUMNS_CONFIG.map((col) => {
              // Default to visible (true) if not in state
              const isVisible = columnVisibility[col.id] !== false;
              return (
                <DropdownMenuCheckboxItem
                  key={col.id}
                  checked={isVisible}
                  onCheckedChange={(checked) => {
                    onColumnVisibilityChange(col.id, checked);
                  }}
                  onSelect={(e) => e.preventDefault()}
                >
                  {col.label}
                </DropdownMenuCheckboxItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* ✅ Option C: Keyboard Shortcuts Help */}
        <KeyboardShortcutsHelp className="h-8 w-8 p-0" />
      </TooltipProvider>
    </div>
  );
}

export default TableToolbar;
