// src/components/ui/currency-input.tsx
"use client";

import * as React from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface CurrencyInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  value?: number | null;
  onChange?: (value: number | null) => void;
  currency?: string;
  locale?: string;
}

/**
 * CurrencyInput component with automatic thousand separators
 *
 * Features:
 * - Formats numbers with thousand separators (1,000,000)
 * - Supports Vietnamese locale (1.000.000)
 * - Allows only numeric input
 * - Handles null values
 *
 * @example
 * <CurrencyInput
 *   value={tuitionFee}
 *   onChange={(value) => field.onChange(value)}
 *   placeholder="VD: 15,000,000"
 *   currency="VND"
 * />
 */
const CurrencyInput = React.forwardRef<HTMLInputElement, CurrencyInputProps>(
  ({ className, value, onChange, currency = "VND", locale = "vi-VN", ...props }, ref) => {
    const [displayValue, setDisplayValue] = React.useState<string>("");

    // Format number with thousand separators
    const formatNumber = (num: number): string => {
      if (locale === "vi-VN") {
        // Vietnamese format: 1.000.000
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      } else {
        // English format: 1,000,000
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
      }
    };

    // Parse formatted string back to number
    const parseNumber = (str: string): number | null => {
      if (!str) return null;
      // Remove all separators (both . and ,)
      const cleaned = str.replace(/[.,]/g, "");
      const parsed = parseInt(cleaned, 10);
      return isNaN(parsed) ? null : parsed;
    };

    // Update display value when prop value changes
    React.useEffect(() => {
      if (value === null || value === undefined) {
        setDisplayValue("");
      } else {
        setDisplayValue(formatNumber(value));
      }
    }, [value]);

    // Handle input change
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const inputValue = e.target.value;

      // Allow empty input
      if (inputValue === "") {
        setDisplayValue("");
        onChange?.(null);
        return;
      }

      // Allow only digits and separators
      const digitsOnly = inputValue.replace(/[^\d]/g, "");

      if (digitsOnly === "") {
        setDisplayValue("");
        onChange?.(null);
        return;
      }

      // Parse and format
      const numericValue = parseInt(digitsOnly, 10);
      if (!isNaN(numericValue)) {
        const formatted = formatNumber(numericValue);
        setDisplayValue(formatted);
        onChange?.(numericValue);
      }
    };

    return (
      <div className="relative">
        <Input
          type="text"
          inputMode="numeric"
          value={displayValue}
          onChange={handleChange}
          className={cn("pr-12", className)}
          ref={ref}
          {...props}
        />
        {currency && (
          <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
            <span className="text-sm text-muted-foreground">{currency}</span>
          </div>
        )}
      </div>
    );
  }
);

CurrencyInput.displayName = "CurrencyInput";

export { CurrencyInput };
