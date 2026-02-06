// src/components/common/form/SearchInput.tsx
"use client";

import * as React from "react";
import { Search, X, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface SearchInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> {
  /** Current search value */
  value: string;
  /** Callback when value changes (after debounce) */
  onChange: (value: string) => void;
  /** Debounce delay in milliseconds */
  debounceMs?: number;
  /** Show loading spinner */
  isLoading?: boolean;
  /** Show search icon */
  showSearchIcon?: boolean;
  /** Show clear button when there's input */
  showClearButton?: boolean;
  /** Additional CSS classes for the container */
  containerClassName?: string;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_DEBOUNCE_MS = 300;

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(
  (
    {
      value,
      onChange,
      debounceMs = DEFAULT_DEBOUNCE_MS,
      isLoading = false,
      showSearchIcon = true,
      showClearButton = true,
      placeholder = "Tim kiem...",
      containerClassName,
      className,
      disabled,
      ...props
    },
    ref
  ) => {
    // Local state for immediate UI feedback
    const [localValue, setLocalValue] = React.useState(value);
    const debounceRef = React.useRef<NodeJS.Timeout | null>(null);

    // Sync local value with external value
    React.useEffect(() => {
      setLocalValue(value);
    }, [value]);

    // Debounced change handler
    const handleChange = React.useCallback(
      (e: React.ChangeEvent<HTMLInputElement>) => {
        const newValue = e.target.value;
        setLocalValue(newValue);

        // Clear previous debounce
        if (debounceRef.current) {
          clearTimeout(debounceRef.current);
        }

        // Debounce the onChange callback
        debounceRef.current = setTimeout(() => {
          onChange(newValue);
        }, debounceMs);
      },
      [onChange, debounceMs]
    );

    // Clear handler
    const handleClear = React.useCallback(() => {
      setLocalValue("");
      onChange("");

      // Clear any pending debounce
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    }, [onChange]);

    // Cleanup on unmount
    React.useEffect(() => {
      return () => {
        if (debounceRef.current) {
          clearTimeout(debounceRef.current);
        }
      };
    }, []);

    const hasValue = localValue.length > 0;

    return (
      <div className={cn("relative", containerClassName)}>
        {/* Search icon */}
        {showSearchIcon && (
          <Search aria-hidden="true" className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        )}

        {/* Input */}
        <Input
          ref={ref}
          type="text"
          value={localValue}
          onChange={handleChange}
          placeholder={placeholder}
          disabled={disabled || isLoading}
          className={cn(
            showSearchIcon && "pl-9",
            (showClearButton && hasValue) || isLoading ? "pr-9" : "",
            className
          )}
          {...props}
        />

        {/* Right side icons */}
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          {/* Loading spinner */}
          {isLoading && <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin text-muted-foreground" />}

          {/* Clear button */}
          {!isLoading && showClearButton && hasValue && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 hover:bg-transparent"
              onClick={handleClear}
              disabled={disabled}
              aria-label="Xoa tim kiem"
            >
              <X className="h-4 w-4 text-muted-foreground hover:text-foreground" />
            </Button>
          )}
        </div>
      </div>
    );
  }
);

SearchInput.displayName = "SearchInput";

export default SearchInput;
