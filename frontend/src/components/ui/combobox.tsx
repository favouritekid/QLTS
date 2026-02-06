// src/components/ui/combobox.tsx
"use client";

import * as React from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface ComboboxOption {
  value: string;
  label: string;
}

interface ComboboxProps {
  value: string;
  onChange: (value: string) => void;
  /** @deprecated Use `options` instead for value/label pairs */
  suggestions?: string[];
  /** Array of {value, label} objects for display */
  options?: ComboboxOption[];
  placeholder?: string;
  emptyText?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Combobox component for autocomplete selection
 *
 * Provides searchable dropdown with suggestions from a list.
 * Supports both simple strings and value/label pairs.
 *
 * @example
 * // Simple strings (value = label)
 * <Combobox
 *   value={province}
 *   onChange={setProvince}
 *   suggestions={["Hà Nội", "Hồ Chí Minh"]}
 * />
 *
 * @example
 * // Value/Label pairs (display label, store value)
 * <Combobox
 *   value={nationality}
 *   onChange={setNationality}
 *   options={[
 *     { value: "VN", label: "Việt Nam" },
 *     { value: "US", label: "Hoa Kỳ" }
 *   ]}
 * />
 */
export function Combobox({
  value,
  onChange,
  suggestions = [],
  options,
  placeholder = "Select or type...",
  emptyText = "No suggestions found.",
  searchPlaceholder = "Search...",
  disabled = false,
  className,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);

  // Normalize to options format
  const normalizedOptions = React.useMemo<ComboboxOption[]>(() => {
    if (options && options.length > 0) {
      return options;
    }
    // Backward compatibility: convert suggestions to options
    return suggestions.map(s => ({ value: s, label: s }));
  }, [options, suggestions]);

  // Find current label for display
  const currentLabel = React.useMemo(() => {
    const option = normalizedOptions.find(opt => opt.value === value);
    return option?.label || value;
  }, [value, normalizedOptions]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn("w-full justify-between", className)}
          disabled={disabled}
        >
          <span className="truncate">
            {currentLabel || placeholder}
          </span>
          <ChevronsUpDown aria-hidden="true" className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-full p-0" align="start">
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {normalizedOptions.map((option) => (
                <CommandItem
                  key={option.value}
                  value={option.label}
                  onSelect={() => {
                    onChange(option.value === value ? "" : option.value);
                    setOpen(false);
                  }}
                >
                  <Check
                    aria-hidden="true"
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === option.value ? "opacity-100" : "opacity-0"
                    )}
                  />
                  {option.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
