// src/components/common/form/FormNumber.tsx
"use client";

import * as React from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface FormNumberProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "onChange" | "value"> {
  /** Current value */
  value: number | undefined | null;
  /** Callback when value changes */
  onChange: (value: number | undefined) => void;
  /** Field label */
  label?: string;
  /** Helper text shown below input */
  description?: string;
  /** Error message */
  error?: string;
  /** Mark field as required */
  required?: boolean;
  /** Container class name */
  containerClassName?: string;
  /** Use thousands separator (e.g., 1,000,000) */
  useThousandsSeparator?: boolean;
  /** Allow negative numbers */
  allowNegative?: boolean;
  /** Decimal places allowed (0 for integers only) */
  decimalPlaces?: number;
  /** Prefix (e.g., "$") */
  prefix?: string;
  /** Suffix (e.g., "VND") */
  suffix?: string;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Format number with thousands separator
 */
function formatWithSeparator(value: number | undefined | null, decimalPlaces: number): string {
  if (value === undefined || value === null || isNaN(value)) {
    return "";
  }

  const parts = value.toFixed(decimalPlaces).split(".");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return parts.join(".");
}

/**
 * Parse formatted string back to number
 */
function parseFormattedNumber(value: string): number | undefined {
  // Remove all commas and spaces
  const cleaned = value.replace(/[,\s]/g, "");
  if (cleaned === "" || cleaned === "-") {
    return undefined;
  }
  const parsed = parseFloat(cleaned);
  return isNaN(parsed) ? undefined : parsed;
}

/**
 * Validate if a character is allowed in the input
 */
function isValidChar(char: string, allowNegative: boolean, decimalPlaces: number): boolean {
  // Always allow digits
  if (/[0-9]/.test(char)) return true;
  // Allow decimal point if decimals are allowed
  if (char === "." && decimalPlaces > 0) return true;
  // Allow minus sign if negative numbers are allowed
  if (char === "-" && allowNegative) return true;
  // Allow comma (will be stripped during parse)
  if (char === ",") return true;
  return false;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const FormNumber = React.forwardRef<HTMLInputElement, FormNumberProps>(
  (
    {
      value,
      onChange,
      label,
      description,
      error,
      required,
      containerClassName,
      className,
      id,
      useThousandsSeparator = false,
      allowNegative = false,
      decimalPlaces = 0,
      prefix,
      suffix,
      min,
      max,
      disabled,
      onBlur,
      ...props
    },
    ref
  ) => {
    const inputId = id || React.useId();
    const [displayValue, setDisplayValue] = React.useState<string>("");

    // Sync display value with external value
    React.useEffect(() => {
      if (useThousandsSeparator) {
        setDisplayValue(formatWithSeparator(value, decimalPlaces));
      } else {
        setDisplayValue(value !== undefined && value !== null ? String(value) : "");
      }
    }, [value, useThousandsSeparator, decimalPlaces]);

    // Handle input change
    const handleChange = React.useCallback(
      (e: React.ChangeEvent<HTMLInputElement>) => {
        const inputValue = e.target.value;

        // Allow empty input
        if (inputValue === "") {
          setDisplayValue("");
          onChange(undefined);
          return;
        }

        // Validate characters
        const cleanedValue = inputValue
          .split("")
          .filter((char) => isValidChar(char, allowNegative, decimalPlaces))
          .join("");

        // Handle minus sign (only at the beginning)
        let processedValue = cleanedValue;
        if (processedValue.includes("-")) {
          const minusCount = (processedValue.match(/-/g) || []).length;
          if (minusCount > 1 || !processedValue.startsWith("-")) {
            processedValue = processedValue.replace(/-/g, "");
            if (allowNegative && inputValue.startsWith("-")) {
              processedValue = "-" + processedValue;
            }
          }
        }

        // Handle decimal point (only one allowed)
        if (processedValue.split(".").length > 2) {
          return; // Invalid - multiple decimal points
        }

        // Limit decimal places
        if (decimalPlaces >= 0) {
          const parts = processedValue.split(".");
          if (parts[1] && parts[1].length > decimalPlaces) {
            parts[1] = parts[1].slice(0, decimalPlaces);
            processedValue = parts.join(".");
          }
        }

        // Parse and validate number
        const numValue = parseFormattedNumber(processedValue);

        // Enforce min/max if provided
        if (numValue !== undefined) {
          if (min !== undefined && numValue < Number(min)) return;
          if (max !== undefined && numValue > Number(max)) return;
          if (!allowNegative && numValue < 0) return;
        }

        // Update display and value
        if (useThousandsSeparator && numValue !== undefined) {
          setDisplayValue(formatWithSeparator(numValue, decimalPlaces));
        } else {
          setDisplayValue(processedValue);
        }

        onChange(numValue);
      },
      [onChange, allowNegative, decimalPlaces, useThousandsSeparator, min, max]
    );

    // Handle blur - format the number
    const handleBlur = React.useCallback(
      (e: React.FocusEvent<HTMLInputElement>) => {
        if (useThousandsSeparator && value !== undefined && value !== null) {
          setDisplayValue(formatWithSeparator(value, decimalPlaces));
        }
        onBlur?.(e);
      },
      [value, useThousandsSeparator, decimalPlaces, onBlur]
    );

    const hasError = !!error;

    return (
      <div className={cn("space-y-2", containerClassName)}>
        {/* Label */}
        {label && (
          <Label
            htmlFor={inputId}
            className={cn(hasError && "text-destructive")}
          >
            {label}
            {required && <span className="text-destructive ml-1">*</span>}
          </Label>
        )}

        {/* Input wrapper */}
        <div className="relative flex items-center">
          {/* Prefix */}
          {prefix && (
            <span className="absolute left-3 text-muted-foreground text-sm">
              {prefix}
            </span>
          )}

          <Input
            ref={ref}
            id={inputId}
            type="text"
            inputMode="decimal"
            value={displayValue}
            onChange={handleChange}
            onBlur={handleBlur}
            disabled={disabled}
            className={cn(
              hasError && "border-destructive focus-visible:ring-destructive",
              prefix && "pl-8",
              suffix && "pr-12",
              "text-right",
              className
            )}
            aria-invalid={hasError}
            aria-describedby={
              error ? `${inputId}-error` : description ? `${inputId}-description` : undefined
            }
            {...props}
          />

          {/* Suffix */}
          {suffix && (
            <span className="absolute right-3 text-muted-foreground text-sm">
              {suffix}
            </span>
          )}
        </div>

        {/* Description */}
        {description && !error && (
          <p
            id={`${inputId}-description`}
            className="text-sm text-muted-foreground"
          >
            {description}
          </p>
        )}

        {/* Error message */}
        {error && (
          <p
            id={`${inputId}-error`}
            className="text-sm font-medium text-destructive"
            role="alert"
          >
            {error}
          </p>
        )}
      </div>
    );
  }
);

FormNumber.displayName = "FormNumber";

export default FormNumber;
