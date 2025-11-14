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
 */
const CurrencyInput = React.forwardRef<HTMLInputElement, CurrencyInputProps>(
  ({ className, value, onChange, currency = "VND", locale = "vi-VN", ...props }, ref) => {
    const [displayValue, setDisplayValue] = React.useState<string>("");

    // ✅ FIX 1: Bọc formatNumber trong useCallback để tránh warning useEffect
    const formatNumber = React.useCallback(
      (num: number): string => {
        if (locale === "vi-VN") {
          // Vietnamese format: 1.000.000
          return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
        } else {
          // English format: 1,000,000
          return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        }
      },
      [locale]
    );

    // ❌ ĐÃ XÓA: parseNumber (không sử dụng)

    // Update display value when prop value changes
    React.useEffect(() => {
      if (value === null || value === undefined) {
        setDisplayValue("");
      } else {
        setDisplayValue(formatNumber(value));
      }
    }, [value, formatNumber]); // ✅ Đã thêm formatNumber vào dependency

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
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
            <span className="text-muted-foreground text-sm">{currency}</span>
          </div>
        )}
      </div>
    );
  }
);

CurrencyInput.displayName = "CurrencyInput";

export { CurrencyInput };
