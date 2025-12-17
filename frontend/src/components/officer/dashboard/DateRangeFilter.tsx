// src/components/officer/dashboard/DateRangeFilter.tsx
/**
 * Dashboard Date Range Filter
 * Provides preset buttons + custom date picker for global dashboard filtering.
 */
"use client";

import { CalendarIcon } from "lucide-react";
import { format } from "date-fns";
import { vi } from "date-fns/locale";

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

  return (
    <div className="flex items-center gap-2 bg-muted/50 rounded-lg px-3 py-1.5 border">
      {/* Preset Buttons */}
      <div className="flex items-center gap-1">
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
      <Popover>
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
          <Calendar
            mode="range"
            defaultMonth={dateRange?.from}
            selected={dateRange}
            onSelect={(range) => {
              if (range) setCustomRange(range);
            }}
            numberOfMonths={2}
            locale={vi}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
