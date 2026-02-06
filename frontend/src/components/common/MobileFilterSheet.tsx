// src/components/common/MobileFilterSheet.tsx
/**
 * MobileFilterSheet - Bottom sheet for filters on mobile devices
 *
 * Provides a touch-friendly filter UI that slides up from the bottom.
 * Features:
 * - Drag handle for visual affordance
 * - Filter groups with labels
 * - Apply/Reset buttons
 * - Safe area padding for notched devices
 *
 * Usage:
 * ```tsx
 * const [filtersOpen, setFiltersOpen] = useState(false);
 * const [filters, setFilters] = useState({ status: "", search: "" });
 *
 * <MobileFilterSheet
 *   open={filtersOpen}
 *   onOpenChange={setFiltersOpen}
 *   title="Bộ lọc"
 *   onApply={() => applyFilters()}
 *   onReset={() => resetFilters()}
 *   activeCount={countActiveFilters()}
 * >
 *   <MobileFilterSheet.Group label="Trạng thái">
 *     <Select value={filters.status} onValueChange={...}>
 *       ...
 *     </Select>
 *   </MobileFilterSheet.Group>
 *   <MobileFilterSheet.Group label="Tìm kiếm">
 *     <Input value={filters.search} onChange={...} />
 *   </MobileFilterSheet.Group>
 * </MobileFilterSheet>
 * ```
 */
"use client";

import * as React from "react";
import { Filter, X, RotateCcw } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

interface MobileFilterSheetProps {
  /** Controlled open state */
  open: boolean;
  /** Callback when open state changes */
  onOpenChange: (open: boolean) => void;
  /** Sheet title */
  title?: string;
  /** Filter children */
  children: React.ReactNode;
  /** Callback when apply button is clicked */
  onApply?: () => void;
  /** Callback when reset button is clicked */
  onReset?: () => void;
  /** Number of active filters (shows badge) */
  activeCount?: number;
  /** Apply button text */
  applyText?: string;
  /** Reset button text */
  resetText?: string;
  /** Additional class name */
  className?: string;
}

interface FilterGroupProps {
  /** Group label */
  label: string;
  /** Group children */
  children: React.ReactNode;
  /** Additional class name */
  className?: string;
}

interface FilterTriggerProps {
  /** Callback when trigger is clicked */
  onClick: () => void;
  /** Number of active filters */
  activeCount?: number;
  /** Button text (default: "Bộ lọc") */
  text?: string;
  /** Additional class name */
  className?: string;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

function MobileFilterSheet({
  open,
  onOpenChange,
  title = "Bộ lọc",
  children,
  onApply,
  onReset,
  activeCount = 0,
  applyText = "Áp dụng",
  resetText = "Đặt lại",
  className,
}: MobileFilterSheetProps) {
  const handleApply = () => {
    onApply?.();
    onOpenChange(false);
  };

  const handleReset = () => {
    onReset?.();
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className={cn(
          // Override default padding
          "p-0",
          // Rounded top corners
          "rounded-t-2xl",
          // Max height
          "max-h-[85vh]",
          // Safe area padding
          "pb-[env(safe-area-inset-bottom)]",
          className
        )}
      >
        {/* Drag Handle */}
        <div className="flex justify-center pt-3 pb-2">
          <div className="w-10 h-1 rounded-full bg-muted-foreground/30" />
        </div>

        {/* Header */}
        <SheetHeader className="px-4 pb-4 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Filter className="h-5 w-5 text-muted-foreground" />
              <SheetTitle className="text-base">{title}</SheetTitle>
              {activeCount > 0 && (
                <Badge variant="secondary" className="ml-1">
                  {activeCount}
                </Badge>
              )}
            </div>
            {onReset && activeCount > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleReset}
                className="text-muted-foreground"
              >
                <RotateCcw className="h-4 w-4 mr-1" />
                {resetText}
              </Button>
            )}
          </div>
        </SheetHeader>

        {/* Filter Content */}
        <div className="px-4 py-4 space-y-4 overflow-y-auto max-h-[calc(85vh-140px)]">
          {children}
        </div>

        {/* Footer with Apply Button */}
        <div className="px-4 py-4 border-t bg-background">
          <Button
            onClick={handleApply}
            className="w-full min-h-[48px]"
          >
            {applyText}
            {activeCount > 0 && (
              <Badge variant="secondary" className="ml-2 bg-primary-foreground/20">
                {activeCount}
              </Badge>
            )}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// =============================================================================
// FILTER GROUP
// =============================================================================

function FilterGroup({ label, children, className }: FilterGroupProps) {
  return (
    <div className={cn("space-y-2", className)}>
      <label className="text-sm font-medium text-foreground">{label}</label>
      {children}
    </div>
  );
}

// =============================================================================
// FILTER TRIGGER BUTTON
// =============================================================================

function FilterTrigger({
  onClick,
  activeCount = 0,
  text = "Bộ lọc",
  className,
}: FilterTriggerProps) {
  return (
    <Button
      variant="outline"
      onClick={onClick}
      className={cn("min-h-[44px]", className)}
    >
      <Filter className="h-4 w-4 mr-2" />
      {text}
      {activeCount > 0 && (
        <Badge variant="secondary" className="ml-2">
          {activeCount}
        </Badge>
      )}
    </Button>
  );
}

// =============================================================================
// EXPORTS
// =============================================================================

// Attach subcomponents
MobileFilterSheet.Group = FilterGroup;
MobileFilterSheet.Trigger = FilterTrigger;

export { MobileFilterSheet, FilterGroup, FilterTrigger };
export type { MobileFilterSheetProps, FilterGroupProps, FilterTriggerProps };
