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
import { CalendarIcon, Check, X } from "lucide-react";
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

  // Handle popover open - initialize draft with current range
  const handleOpenChange = (open: boolean) => {
    if (open) {
      setDraftRange(dateRange);
    } else {
      // Reset draft when closing without apply
      setDraftRange(undefined);
    }
    setIsOpen(open);
  };

  // Handle date selection with smart logic
  const handleSelect = (range: DateRange | undefined) => {
    if (!range) return;
    setDraftRange(range);
  };

  // Apply the draft range
  const handleApply = () => {
    if (draftRange?.from && draftRange?.to) {
      setCustomRange(draftRange);
      setIsOpen(false);
      setDraftRange(undefined);
    } else if (draftRange?.from) {
      // If only from is selected, set same date for both (single day)
      setCustomRange({ from: draftRange.from, to: draftRange.from });
      setIsOpen(false);
      setDraftRange(undefined);
    }
  };

  // Cancel and close
  const handleCancel = () => {
    setDraftRange(undefined);
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
              <div className="text-sm text-muted-foreground">
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
                  </>
                ) : (
                  "Chọn ngày bắt đầu"
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
