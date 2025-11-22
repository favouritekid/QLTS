// src/components/common/selectors/SmartOfferingSelector.tsx
/**
 * SmartOfferingSelector - Reusable Program Offering Selector
 *
 * Features:
 * - Automatic data fetching via useAllProgramOfferings hook
 * - Grouped by major program
 * - Shows offering type and degree level
 * - Searchable with Command component
 * - Filter by unit, degree level, or active status
 *
 * Usage:
 * - LeadDialog (offering selection)
 * - LeadFilters (offering filter)
 * - DistributionRuleDialog
 */

"use client";

import { useState, useMemo } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useAllProgramOfferings } from "@/hooks/useOrganization";
import type { ProgramOffering } from "@/types/organization.types";

// =============================================================================
// TYPES
// =============================================================================

export interface SmartOfferingSelectorProps {
  /** Current selected offering ID (as string for form compatibility) */
  value?: string;
  /** Callback when selection changes */
  onChange: (value: string | undefined) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Allow "all" option */
  allowAll?: boolean;
  /** Label for "all" option */
  allLabel?: string;
  /** Filter to only show offerings of specific degree level */
  filterDegreeLevel?: string;
  /** Filter to only show active offerings */
  activeOnly?: boolean;
  /** Disable the selector */
  disabled?: boolean;
  /** Variant: 'select' for grouped dropdown, 'combobox' for searchable */
  variant?: "select" | "combobox";
  /** Additional CSS classes */
  className?: string;
}

interface ProcessedOffering extends ProgramOffering {
  displayName: string;
  programName: string;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Process offerings with filtering and formatting
 */
function processOfferings(
  offerings: ProgramOffering[],
  options: {
    filterDegreeLevel?: string;
    activeOnly?: boolean;
  }
): ProcessedOffering[] {
  const { filterDegreeLevel, activeOnly = true } = options;

  return offerings
    .filter((offering) => {
      // Filter by active status
      if (activeOnly && !offering.is_active) return false;

      // Filter by degree level
      if (filterDegreeLevel && offering.program?.degree_level !== filterDegreeLevel)
        return false;

      return true;
    })
    .map((offering) => ({
      ...offering,
      displayName: `${offering.offering_type} - ${offering.program?.name || "Unknown"}`,
      programName: offering.program?.name || "Unknown Program",
    }))
    .sort((a, b) => a.programName.localeCompare(b.programName));
}

/**
 * Group offerings by program
 */
function groupByProgram(offerings: ProcessedOffering[]): Map<string, ProcessedOffering[]> {
  const groups = new Map<string, ProcessedOffering[]>();

  for (const offering of offerings) {
    const key = offering.programName;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(offering);
  }

  return groups;
}

// =============================================================================
// SELECT VARIANT COMPONENT
// =============================================================================

function SelectVariant({
  value,
  onChange,
  placeholder,
  allowAll,
  allLabel,
  disabled,
  offerings,
  isLoading,
  className,
}: {
  value?: string;
  onChange: (value: string | undefined) => void;
  placeholder: string;
  allowAll: boolean;
  allLabel: string;
  disabled: boolean;
  offerings: ProcessedOffering[];
  isLoading: boolean;
  className?: string;
}) {
  const groupedOfferings = useMemo(() => groupByProgram(offerings), [offerings]);
  const selectedOffering = offerings.find((o) => String(o.id) === value);

  return (
    <Select
      value={value}
      onValueChange={(val) => onChange(val === "all" ? undefined : val)}
      disabled={disabled || isLoading}
    >
      <SelectTrigger className={className}>
        <SelectValue placeholder={isLoading ? "Dang tai..." : placeholder}>
          {selectedOffering && (
            <span className="truncate">{selectedOffering.displayName}</span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="max-h-[300px]">
        {allowAll && (
          <SelectItem value="all">
            <span className="font-semibold">{allLabel}</span>
          </SelectItem>
        )}
        {isLoading ? (
          <SelectItem value="loading" disabled>
            Dang tai chuong trinh...
          </SelectItem>
        ) : offerings.length === 0 ? (
          <SelectItem value="empty" disabled>
            Khong co chuong trinh kha dung
          </SelectItem>
        ) : (
          Array.from(groupedOfferings.entries()).map(([programName, programOfferings]) => (
            <SelectGroup key={programName}>
              <SelectLabel className="text-xs font-semibold text-muted-foreground">
                {programName}
              </SelectLabel>
              {programOfferings.map((offering) => (
                <SelectItem key={offering.id} value={String(offering.id)}>
                  <div className="flex items-center gap-2">
                    <span>{offering.offering_type}</span>
                    {offering.program?.degree_level && (
                      <span className="text-xs text-muted-foreground">
                        ({offering.program.degree_level})
                      </span>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectGroup>
          ))
        )}
      </SelectContent>
    </Select>
  );
}

// =============================================================================
// COMBOBOX VARIANT COMPONENT
// =============================================================================

function ComboboxVariant({
  value,
  onChange,
  placeholder,
  allowAll,
  allLabel,
  disabled,
  offerings,
  isLoading,
  className,
}: {
  value?: string;
  onChange: (value: string | undefined) => void;
  placeholder: string;
  allowAll: boolean;
  allLabel: string;
  disabled: boolean;
  offerings: ProcessedOffering[];
  isLoading: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const groupedOfferings = useMemo(() => groupByProgram(offerings), [offerings]);
  const selectedOffering = offerings.find((o) => String(o.id) === value);

  const displayValue = selectedOffering
    ? selectedOffering.displayName
    : value === "all" || !value
      ? allLabel
      : placeholder;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled || isLoading}
          className={cn("w-full justify-between", className)}
        >
          <span className="truncate">
            {isLoading ? "Dang tai..." : displayValue}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[400px] p-0" align="start">
        <Command>
          <CommandInput placeholder="Tim kiem chuong trinh..." />
          <CommandEmpty>Khong tim thay chuong trinh nao.</CommandEmpty>
          {allowAll && (
            <CommandGroup>
              <CommandItem
                value="all"
                onSelect={() => {
                  onChange(undefined);
                  setOpen(false);
                }}
              >
                <Check
                  className={cn(
                    "mr-2 h-4 w-4",
                    !value || value === "all" ? "opacity-100" : "opacity-0"
                  )}
                />
                <span className="font-semibold">{allLabel}</span>
              </CommandItem>
            </CommandGroup>
          )}
          {Array.from(groupedOfferings.entries()).map(([programName, programOfferings]) => (
            <CommandGroup key={programName} heading={programName}>
              {programOfferings.map((offering) => (
                <CommandItem
                  key={offering.id}
                  value={`${offering.programName} ${offering.offering_type}`}
                  onSelect={() => {
                    onChange(String(offering.id));
                    setOpen(false);
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      value === String(offering.id) ? "opacity-100" : "opacity-0"
                    )}
                  />
                  <div className="flex items-center gap-2">
                    <span>{offering.offering_type}</span>
                    {offering.program?.degree_level && (
                      <span className="text-xs text-muted-foreground">
                        ({offering.program.degree_level})
                      </span>
                    )}
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </Command>
      </PopoverContent>
    </Popover>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function SmartOfferingSelector({
  value,
  onChange,
  placeholder = "Chon chuong trinh",
  allowAll = false,
  allLabel = "Tat ca chuong trinh",
  filterDegreeLevel,
  activeOnly = true,
  disabled = false,
  variant = "select",
  className,
}: SmartOfferingSelectorProps) {
  // Fetch offerings
  const { data: offerings = [], isLoading } = useAllProgramOfferings();

  // Process offerings with filtering
  const processedOfferings = useMemo(
    () =>
      processOfferings(offerings, {
        filterDegreeLevel,
        activeOnly,
      }),
    [offerings, filterDegreeLevel, activeOnly]
  );

  // Render based on variant
  const commonProps = {
    value,
    onChange,
    placeholder,
    allowAll,
    allLabel,
    disabled,
    offerings: processedOfferings,
    isLoading,
    className,
  };

  if (variant === "combobox") {
    return <ComboboxVariant {...commonProps} />;
  }

  return <SelectVariant {...commonProps} />;
}

export default SmartOfferingSelector;
