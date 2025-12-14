// src/components/leads/command-center/TableToolbar.tsx
/**
 * TableToolbar - Toolbar for table controls
 * 
 * Features:
 * - 3-level density toggle (Condensed/Regular/Relaxed)
 * - Column visibility dropdown
 * - ✅ Option C: Keyboard shortcuts help
 */

"use client";

import React from "react";
import {
  Columns,
  Minus,
  Equal,
  Menu,
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

export type DensityMode = 'condensed' | 'regular' | 'relaxed';

interface TableToolbarProps {
  densityMode: DensityMode;
  onDensityChange: (mode: DensityMode) => void;
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
  { id: "lead_score", label: "Điểm" },
  { id: "created_at", label: "Hoạt động" },
];

const DENSITY_OPTIONS: { value: DensityMode; label: string; icon: React.ElementType }[] = [
  { value: 'condensed', label: 'Thu gọn', icon: Minus },
  { value: 'regular', label: 'Thường', icon: Equal },
  { value: 'relaxed', label: 'Thoáng', icon: Menu },
];

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function TableToolbar({
  densityMode,
  onDensityChange,
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
        {/* Density Toggle - Segmented Control */}
        <div className="flex items-center rounded-md border bg-muted/50 p-0.5">
          {DENSITY_OPTIONS.map((option) => {
            const Icon = option.icon;
            const isActive = densityMode === option.value;
            return (
              <Tooltip key={option.value}>
                <TooltipTrigger asChild>
                  <button
                    onClick={() => onDensityChange(option.value)}
                    className={cn(
                      "h-7 w-7 flex items-center justify-center rounded-sm transition-all",
                      isActive 
                        ? "bg-background shadow-sm text-foreground" 
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent>{option.label}</TooltipContent>
              </Tooltip>
            );
          })}
        </div>

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

