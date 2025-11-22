// src/components/common/form/DatePicker.tsx
"use client";

import * as React from "react";
import { format, isValid, parse } from "date-fns";
import { vi } from "date-fns/locale";
import { Calendar as CalendarIcon, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface DatePickerProps {
  /** Current selected date */
  value?: Date | null;
  /** Callback when date changes */
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
  /** Specific dates to disable */
  disabledDates?: Date[];
  /** Container class name */
  containerClassName?: string;
  /** Additional class name */
  className?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_DATE_FORMAT = "dd/MM/yyyy";

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function DatePicker({
  value,
  onChange,
  dateFormat = DEFAULT_DATE_FORMAT,
  label,
  description,
  error,
  required,
  placeholder = "Chon ngay",
  disabled = false,
  clearable = true,
  minDate,
  maxDate,
  disabledDates,
  containerClassName,
  className,
}: DatePickerProps) {
  const [open, setOpen] = React.useState(false);
  const triggerId = React.useId();

  const hasError = !!error;

  // Format the selected date for display
  const displayValue = React.useMemo(() => {
    if (!value || !isValid(value)) return "";
    return format(value, dateFormat, { locale: vi });
  }, [value, dateFormat]);

  // Handle date selection
  const handleSelect = React.useCallback(
    (date: Date | undefined) => {
      onChange(date);
      setOpen(false);
    },
    [onChange]
  );

  // Handle clear
  const handleClear = React.useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onChange(undefined);
    },
    [onChange]
  );

  // Determine disabled dates function
  const disabledDatesFn = React.useCallback(
    (date: Date) => {
      if (minDate && date < minDate) return true;
      if (maxDate && date > maxDate) return true;
      if (disabledDates) {
        return disabledDates.some(
          (d) => d.toDateString() === date.toDateString()
        );
      }
      return false;
    },
    [minDate, maxDate, disabledDates]
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

      {/* Date picker */}
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
                aria-label="Xoa ngay"
              >
                <X className="h-4 w-4 text-muted-foreground hover:text-foreground" />
              </span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="single"
            selected={value || undefined}
            onSelect={handleSelect}
            disabled={disabledDatesFn}
            initialFocus
            locale={vi}
          />
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

export default DatePicker;
