// src/components/officer/dashboard/DateRangeFilter.tsx
/**
 * Dashboard Date Range Filter
 * Provides preset buttons + custom date picker with Apply/Cancel for global dashboard filtering.
 * 
 * UX Improvements:
 * - Local draft state: changes not applied until "Apply" clicked
 * - Smart range selection: click before start = new start, click after = new end
 * - Apply/Cancel buttons in popover footer
 */
"use client";

import { useState } from "react";
import { CalendarIcon, Check, X, RotateCcw } from "lucide-react";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
import type { DateRange } from "react-day-picker";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  useDashboardDate,
  DATE_PRESET_LABELS,
  type DatePreset,
} from "@/contexts/DashboardDateContext";

const PRESETS: DatePreset[] = ["7d", "30d", "this_month"];

export function DateRangeFilter() {
  const { dateRange, preset, setPreset, setCustomRange } = useDashboardDate();
  
  // Local draft state for date selection
  const [draftRange, setDraftRange] = useState<DateRange | undefined>(undefined);
  const [isOpen, setIsOpen] = useState(false);
  // Selection mode: 'start' = waiting for start date, 'end' = waiting for end date
  const [selectionMode, setSelectionMode] = useState<'start' | 'end'>('start');

  // Handle popover open - initialize draft with current range
  const handleOpenChange = (open: boolean) => {
    if (open) {
      setDraftRange(dateRange);
      // If there's an existing range, user likely wants to adjust
      setSelectionMode(dateRange?.from ? 'end' : 'start');
    } else {
      // Reset draft when closing without apply
      setDraftRange(undefined);
      setSelectionMode('start');
    }
    setIsOpen(open);
  };

  // Handle date selection with smart logic
  const handleSelect = (range: DateRange | undefined) => {
    if (!range) return;
    
    // If in 'start' mode or no range yet, this click sets new start
    if (selectionMode === 'start' || !draftRange?.from) {
      setDraftRange({ from: range.from, to: undefined });
      setSelectionMode('end');
    } else {
      // In 'end' mode - set or update end date
      setDraftRange(range);
    }
  };

  // Reset selection to pick new start date
  const handleResetSelection = () => {
    setDraftRange(undefined);
    setSelectionMode('start');
  };

  // Apply the draft range
  const handleApply = () => {
    if (draftRange?.from && draftRange?.to) {
      setCustomRange(draftRange);
      setIsOpen(false);
      setDraftRange(undefined);
      setSelectionMode('start');
    } else if (draftRange?.from) {
      // If only from is selected, set same date for both (single day)
      setCustomRange({ from: draftRange.from, to: draftRange.from });
      setIsOpen(false);
      setDraftRange(undefined);
      setSelectionMode('start');
    }
  };

  // Cancel and close
  const handleCancel = () => {
    setDraftRange(undefined);
    setSelectionMode('start');
    setIsOpen(false);
  };

  // Check if apply is valid
  const canApply = draftRange?.from !== undefined;

  // Display range (use draft if open, else actual)
  const displayRange = isOpen && draftRange ? draftRange : dateRange;

  return (
    <div className="flex items-center gap-2 bg-muted/50 rounded-lg px-3 py-1.5 border">
      {/* Preset Buttons */}
      <div className="flex items-center gap-1.5">
        {PRESETS.map((p) => (
          <Button
            key={p}
            variant={preset === p ? "default" : "ghost"}
            size="sm"
            className={cn(
              "h-7 px-2.5 text-xs font-medium",
              preset === p && "shadow-sm"
            )}
            onClick={() => setPreset(p)}
          >
            {DATE_PRESET_LABELS[p]}
          </Button>
        ))}
      </div>

      {/* Separator */}
      <div className="w-px h-5 bg-border" />

      {/* Custom Date Picker */}
      <Popover open={isOpen} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            variant={preset === "custom" ? "default" : "ghost"}
            size="sm"
            className={cn(
              "h-7 px-2.5 text-xs font-medium gap-1.5",
              preset === "custom" && "shadow-sm"
            )}
          >
            <CalendarIcon className="h-3.5 w-3.5" />
            {preset === "custom" && dateRange?.from ? (
              <>
                {format(dateRange.from, "dd/MM", { locale: vi })}
                {dateRange.to && (
                  <> - {format(dateRange.to, "dd/MM", { locale: vi })}</>
                )}
              </>
            ) : (
              "Tùy chọn"
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="end">
          <div className="flex flex-col">
            {/* Calendar */}
            <Calendar
              mode="range"
              defaultMonth={displayRange?.from}
              selected={draftRange}
              onSelect={handleSelect}
              numberOfMonths={2}
              locale={vi}
            />
            
            {/* Footer with selection info and buttons */}
            <div className="flex items-center justify-between border-t px-4 py-3 bg-muted/30">
              {/* Selection Preview */}
              <div className="text-sm text-muted-foreground flex items-center gap-2">
                {draftRange?.from ? (
                  <>
                    <span className="font-medium text-foreground">
                      {format(draftRange.from, "dd/MM/yyyy", { locale: vi })}
                    </span>
                    {draftRange.to && draftRange.to.getTime() !== draftRange.from.getTime() && (
                      <>
                        {" → "}
                        <span className="font-medium text-foreground">
                          {format(draftRange.to, "dd/MM/yyyy", { locale: vi })}
                        </span>
                      </>
                    )}
                    {/* Reset button to pick new start date */}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleResetSelection}
                      className="h-6 w-6 p-0 ml-1 text-muted-foreground hover:text-foreground"
                      title="Chọn lại ngày bắt đầu"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                    </Button>
                  </>
                ) : (
                  <span className="text-amber-600">👆 Chọn ngày bắt đầu</span>
                )}
              </div>
              
              {/* Action Buttons */}
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleCancel}
                  className="h-8 px-3 text-xs"
                >
                  <X className="h-3.5 w-3.5 mr-1" />
                  Hủy
                </Button>
                <Button
                  size="sm"
                  onClick={handleApply}
                  disabled={!canApply}
                  className="h-8 px-3 text-xs"
                >
                  <Check className="h-3.5 w-3.5 mr-1" />
                  Áp dụng
                </Button>
              </div>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
