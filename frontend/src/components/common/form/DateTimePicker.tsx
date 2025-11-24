// src/components/common/form/DateTimePicker.tsx
"use client";

import * as React from "react";
import { format, isValid, set, parse } from "date-fns";
import { vi } from "date-fns/locale";
import { Calendar as CalendarIcon, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface DateTimePickerProps {
  /** Current selected datetime */
  value?: Date | null;
  /** Callback when datetime changes */
  onChange: (date: Date | undefined) => void;
  /** Date format for display */
  dateFormat?: string;
  /** Field label */
  label?: string;
  /** Helper text shown below input */
  description?: string;
  /** Error message */
  error?: string;
  /** Mark field as required */
  required?: boolean;
  /** Placeholder text */
  placeholder?: string;
  /** Disable the picker */
  disabled?: boolean;
  /** Show clear button */
  clearable?: boolean;
  /** Disable dates before this date */
  minDate?: Date;
  /** Disable dates after this date */
  maxDate?: Date;
  /** Container class name */
  containerClassName?: string;
  /** Additional class name */
  className?: string;
  /** Use 12-hour format (default: true for Vietnamese) */
  use12Hour?: boolean;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_DATE_FORMAT = "dd/MM/yyyy HH:mm";
const DEFAULT_DATE_FORMAT_12H = "dd/MM/yyyy hh:mm a";

// Generate hour options
const HOURS_24 = Array.from({ length: 24 }, (_, i) => i);
const HOURS_12 = Array.from({ length: 12 }, (_, i) => i === 0 ? 12 : i);
const MINUTES = Array.from({ length: 60 }, (_, i) => i);
const PERIODS = ["SA", "CH"] as const; // SA = Sáng (AM), CH = Chiều (PM)

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

function formatTwoDigits(num: number): string {
  return num.toString().padStart(2, "0");
}

function get12HourFrom24(hour24: number): { hour12: number; period: "SA" | "CH" } {
  const period = hour24 >= 12 ? "CH" : "SA";
  let hour12 = hour24 % 12;
  if (hour12 === 0) hour12 = 12;
  return { hour12, period };
}

function get24HourFrom12(hour12: number, period: "SA" | "CH"): number {
  if (period === "SA") {
    return hour12 === 12 ? 0 : hour12;
  } else {
    return hour12 === 12 ? 12 : hour12 + 12;
  }
}

// =============================================================================
// TIME PICKER COLUMN COMPONENT
// =============================================================================

interface TimeColumnProps {
  values: (number | string)[];
  selectedValue: number | string;
  onChange: (value: number | string) => void;
  formatFn?: (value: number | string) => string;
  label: string;
}

function TimeColumn({ values, selectedValue, onChange, formatFn, label }: TimeColumnProps) {
  const selectedRef = React.useRef<HTMLButtonElement>(null);

  // Scroll to selected item on mount
  React.useEffect(() => {
    if (selectedRef.current) {
      selectedRef.current.scrollIntoView({ block: "center", behavior: "auto" });
    }
  }, [selectedValue]);

  return (
    <div className="flex flex-col">
      <div className="text-xs font-medium text-center py-1 text-muted-foreground border-b">
        {label}
      </div>
      <ScrollArea className="h-[200px]">
        <div className="flex flex-col p-1">
          {values.map((value) => {
            const isSelected = value === selectedValue;
            const displayValue = formatFn ? formatFn(value) : String(value);

            return (
              <button
                key={value}
                ref={isSelected ? selectedRef : undefined}
                type="button"
                onClick={() => onChange(value)}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-md transition-colors text-center",
                  isSelected
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                )}
              >
                {displayValue}
              </button>
            );
          })}
        </div>
      </ScrollArea>
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function DateTimePicker({
  value,
  onChange,
  dateFormat,
  label,
  description,
  error,
  required,
  placeholder = "Chọn ngày giờ",
  disabled = false,
  clearable = true,
  minDate,
  maxDate,
  containerClassName,
  className,
  use12Hour = true,
}: DateTimePickerProps) {
  const [open, setOpen] = React.useState(false);
  const triggerId = React.useId();

  const hasError = !!error;

  // Determine format based on 12/24 hour setting
  const effectiveDateFormat = dateFormat || (use12Hour ? DEFAULT_DATE_FORMAT_12H : DEFAULT_DATE_FORMAT);

  // Extract time components from value
  const { hour24, minute, hour12, period } = React.useMemo(() => {
    if (!value || !isValid(value)) {
      return { hour24: 9, minute: 0, hour12: 9, period: "SA" as const };
    }
    const h24 = value.getHours();
    const m = value.getMinutes();
    const { hour12, period } = get12HourFrom24(h24);
    return { hour24: h24, minute: m, hour12, period };
  }, [value]);

  // Format the selected datetime for display
  const displayValue = React.useMemo(() => {
    if (!value || !isValid(value)) return "";

    if (use12Hour) {
      // Custom format for Vietnamese 12-hour display
      const day = formatTwoDigits(value.getDate());
      const month = formatTwoDigits(value.getMonth() + 1);
      const year = value.getFullYear();
      const { hour12, period } = get12HourFrom24(value.getHours());
      const min = formatTwoDigits(value.getMinutes());
      return `${day}/${month}/${year} ${formatTwoDigits(hour12)}:${min} ${period}`;
    }

    return format(value, effectiveDateFormat, { locale: vi });
  }, [value, effectiveDateFormat, use12Hour]);

  // Handle date selection from calendar
  const handleDateSelect = React.useCallback(
    (date: Date | undefined) => {
      if (!date) {
        onChange(undefined);
        return;
      }

      // Preserve existing time if value exists, otherwise use default
      const currentHour = value ? value.getHours() : 9;
      const currentMinute = value ? value.getMinutes() : 0;

      const newDate = set(date, {
        hours: currentHour,
        minutes: currentMinute,
        seconds: 0,
        milliseconds: 0,
      });

      onChange(newDate);
    },
    [onChange, value]
  );

  // Handle hour change (12-hour format)
  const handleHour12Change = React.useCallback(
    (newHour12: number | string) => {
      const h12 = typeof newHour12 === "string" ? parseInt(newHour12) : newHour12;
      const newHour24 = get24HourFrom12(h12, period);

      const baseDate = value || new Date();
      const newDate = set(baseDate, {
        hours: newHour24,
        seconds: 0,
        milliseconds: 0,
      });

      onChange(newDate);
    },
    [onChange, value, period]
  );

  // Handle hour change (24-hour format)
  const handleHour24Change = React.useCallback(
    (newHour: number | string) => {
      const h = typeof newHour === "string" ? parseInt(newHour) : newHour;

      const baseDate = value || new Date();
      const newDate = set(baseDate, {
        hours: h,
        seconds: 0,
        milliseconds: 0,
      });

      onChange(newDate);
    },
    [onChange, value]
  );

  // Handle minute change
  const handleMinuteChange = React.useCallback(
    (newMinute: number | string) => {
      const m = typeof newMinute === "string" ? parseInt(newMinute) : newMinute;

      const baseDate = value || new Date();
      const newDate = set(baseDate, {
        minutes: m,
        seconds: 0,
        milliseconds: 0,
      });

      onChange(newDate);
    },
    [onChange, value]
  );

  // Handle period change (AM/PM)
  const handlePeriodChange = React.useCallback(
    (newPeriod: number | string) => {
      const p = newPeriod as "SA" | "CH";
      const newHour24 = get24HourFrom12(hour12, p);

      const baseDate = value || new Date();
      const newDate = set(baseDate, {
        hours: newHour24,
        seconds: 0,
        milliseconds: 0,
      });

      onChange(newDate);
    },
    [onChange, value, hour12]
  );

  // Handle clear
  const handleClear = React.useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onChange(undefined);
    },
    [onChange]
  );

  // Handle "Today" button
  const handleToday = React.useCallback(() => {
    const now = new Date();
    onChange(now);
  }, [onChange]);

  // Determine disabled dates function
  const disabledDatesFn = React.useCallback(
    (date: Date) => {
      if (minDate && date < set(minDate, { hours: 0, minutes: 0, seconds: 0, milliseconds: 0 })) {
        return true;
      }
      if (maxDate && date > set(maxDate, { hours: 23, minutes: 59, seconds: 59, milliseconds: 999 })) {
        return true;
      }
      return false;
    },
    [minDate, maxDate]
  );

  return (
    <div className={cn("space-y-2", containerClassName)}>
      {/* Label */}
      {label && (
        <Label
          htmlFor={triggerId}
          className={cn(hasError && "text-destructive")}
        >
          {label}
          {required && <span className="text-destructive ml-1">*</span>}
        </Label>
      )}

      {/* DateTime picker */}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            id={triggerId}
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className={cn(
              "w-full justify-start text-left font-normal",
              !value && "text-muted-foreground",
              hasError && "border-destructive focus-visible:ring-destructive",
              className
            )}
          >
            <CalendarIcon className="mr-2 h-4 w-4" />
            {displayValue || placeholder}

            {/* Clear button */}
            {clearable && value && !disabled && (
              <span
                className="ml-auto"
                onClick={handleClear}
                role="button"
                aria-label="Xóa"
              >
                <X className="h-4 w-4 text-muted-foreground hover:text-foreground" />
              </span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          {/* Input display */}
          <div className="p-3 border-b">
            <Input
              value={displayValue}
              readOnly
              className="text-center font-medium"
              placeholder={placeholder}
            />
          </div>

          <div className="flex">
            {/* Calendar */}
            <div className="border-r">
              <Calendar
                mode="single"
                selected={value || undefined}
                onSelect={handleDateSelect}
                disabled={disabledDatesFn}
                locale={vi}
                initialFocus
              />
              {/* Today & Clear buttons */}
              <div className="flex justify-between px-3 pb-3 gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleClear}
                  className="text-destructive hover:text-destructive"
                >
                  Xóa
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleToday}
                >
                  Hôm nay
                </Button>
              </div>
            </div>

            {/* Time picker columns */}
            <div className="flex divide-x">
              {use12Hour ? (
                <>
                  {/* Hour (12-hour) */}
                  <TimeColumn
                    values={HOURS_12}
                    selectedValue={hour12}
                    onChange={handleHour12Change}
                    formatFn={(v) => formatTwoDigits(v as number)}
                    label="Giờ"
                  />
                  {/* Minute */}
                  <TimeColumn
                    values={MINUTES}
                    selectedValue={minute}
                    onChange={handleMinuteChange}
                    formatFn={(v) => formatTwoDigits(v as number)}
                    label="Phút"
                  />
                  {/* Period (SA/CH) */}
                  <TimeColumn
                    values={[...PERIODS]}
                    selectedValue={period}
                    onChange={handlePeriodChange}
                    label=""
                  />
                </>
              ) : (
                <>
                  {/* Hour (24-hour) */}
                  <TimeColumn
                    values={HOURS_24}
                    selectedValue={hour24}
                    onChange={handleHour24Change}
                    formatFn={(v) => formatTwoDigits(v as number)}
                    label="Giờ"
                  />
                  {/* Minute */}
                  <TimeColumn
                    values={MINUTES}
                    selectedValue={minute}
                    onChange={handleMinuteChange}
                    formatFn={(v) => formatTwoDigits(v as number)}
                    label="Phút"
                  />
                </>
              )}
            </div>
          </div>
        </PopoverContent>
      </Popover>

      {/* Description */}
      {description && !error && (
        <p className="text-sm text-muted-foreground">{description}</p>
      )}

      {/* Error message */}
      {error && (
        <p className="text-sm font-medium text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default DateTimePicker;
