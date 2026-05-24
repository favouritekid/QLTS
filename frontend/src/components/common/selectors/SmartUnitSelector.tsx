// src/components/common/selectors/SmartUnitSelector.tsx
/**
 * SmartUnitSelector - Reusable Organization Unit Selector
 *
 * Features:
 * - Automatic data fetching via useOrganizationUnits hook
 * - Hierarchical display with indentation
 * - Circular dependency prevention (in edit mode)
 * - Searchable with Command component
 * - Works with both Select and Combobox patterns
 *
 * Usage:
 * - UnitDialog (parent selection)
 * - MajorProgramDialog (unit selection)
 * - DistributionRuleDialog (source/target unit selection)
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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import {
  useOrganizationUnits,
  flattenOrganizationTree,
  getAllDescendantIds,
} from "@/hooks/useOrganization";
import type { OrganizationUnit } from "@/types/organization.types";

// =============================================================================
// TYPES
// =============================================================================

interface FlattenedUnit {
  unit: OrganizationUnit;
  level: number;
  hasChildren: boolean;
  displayName: string;
}

export interface SmartUnitSelectorProps {
  /** Current selected unit ID (as string for form compatibility) */
  value?: string;
  /** Callback when selection changes */
  onChange: (value: string | undefined) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Allow "none" option (no parent / top level) */
  allowNone?: boolean;
  /** Label for "none" option */
  noneLabel?: string;
  /** Exclude specific unit ID and its descendants (for circular dependency prevention) */
  excludeUnitId?: number;
  /** Filter to only show units of specific types */
  filterTypes?: string[];
  /** Filter to only show active units */
  activeOnly?: boolean;
  /** Disable the selector */
  disabled?: boolean;
  /** Variant: 'select' for simple dropdown, 'combobox' for searchable */
  variant?: "select" | "combobox";
  /** Additional CSS classes */
  className?: string;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Find a unit in the tree by ID
 */
function findUnitInTree(units: OrganizationUnit[], id: number): OrganizationUnit | null {
  for (const unit of units) {
    if (unit.id === id) return unit;
    if (unit.children) {
      const found = findUnitInTree(unit.children, id);
      if (found) return found;
    }
  }
  return null;
}

/**
 * Process units for display with filtering and formatting
 */
function processUnits(
  allUnits: OrganizationUnit[],
  options: {
    excludeUnitId?: number;
    filterTypes?: string[];
    activeOnly?: boolean;
  }
): FlattenedUnit[] {
  const { excludeUnitId, filterTypes, activeOnly = true } = options;

  // Flatten the tree
  const flattened = flattenOrganizationTree(allUnits);

  // Get excluded IDs (unit + descendants)
  let excludedIds = new Set<number>();
  if (excludeUnitId) {
    const unitToExclude = findUnitInTree(allUnits, excludeUnitId);
    if (unitToExclude) {
      excludedIds = getAllDescendantIds(unitToExclude);
    }
  }

  // Filter and format
  return flattened
    .filter((item) => {
      // Filter by active status
      if (activeOnly && !item.unit.is_active) return false;

      // Filter by excluded IDs
      if (excludedIds.has(item.unit.id)) return false;

      // Filter by type
      if (filterTypes && filterTypes.length > 0) {
        if (!filterTypes.includes(item.unit.type)) return false;
      }

      return true;
    })
    .map((item) => {
      // Create proper hierarchical display with indentation
      const indent = "  ".repeat(item.level); // 2 spaces per level
      const prefix = item.level > 0 ? "└─ " : "";
      return {
        ...item,
        displayName: `${indent}${prefix}${item.unit.name}`,
      };
    });
}

// =============================================================================
// SELECT VARIANT COMPONENT
// =============================================================================

function SelectVariant({
  value,
  onChange,
  placeholder,
  allowNone,
  noneLabel,
  disabled,
  units,
  isLoading,
  className,
}: {
  value?: string;
  onChange: (value: string | undefined) => void;
  placeholder: string;
  allowNone: boolean;
  noneLabel: string;
  disabled: boolean;
  units: FlattenedUnit[];
  isLoading: boolean;
  className?: string;
}) {
  return (
    <Select
      value={value}
      onValueChange={(val) => onChange(val === "none" ? undefined : val)}
      disabled={disabled || isLoading}
    >
      <SelectTrigger className={cn("truncate [&>span]:truncate [&>span]:max-w-[90%]", className)}>
        <SelectValue placeholder={isLoading ? "Dang tai..." : placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-[300px]">
        {allowNone && (
          <SelectItem value="none">
            <span className="font-semibold">{noneLabel}</span>
          </SelectItem>
        )}
        {isLoading ? (
          <SelectItem value="loading" disabled>
            Dang tai danh sach don vi...
          </SelectItem>
        ) : units.length === 0 ? (
          <SelectItem value="empty" disabled>
            Khong co don vi kha dung
          </SelectItem>
        ) : (
          units.map((item) => (
            <SelectItem
              key={item.unit.id}
              value={String(item.unit.id)}
              className="font-mono text-sm"
              title={`${item.unit.name} (${item.unit.type})`}
            >
              <span className={cn("block truncate", item.level === 0 ? "font-semibold" : "")}>
                {item.displayName}
              </span>
            </SelectItem>
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
  allowNone,
  noneLabel,
  disabled,
  units,
  isLoading,
  className,
}: {
  value?: string;
  onChange: (value: string | undefined) => void;
  placeholder: string;
  allowNone: boolean;
  noneLabel: string;
  disabled: boolean;
  units: FlattenedUnit[];
  isLoading: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  // Find selected unit for display
  const selectedUnit = useMemo(() => {
    if (!value || value === "none") return null;
    return units.find((u) => String(u.unit.id) === value);
  }, [value, units]);

  const displayValue = selectedUnit
    ? selectedUnit.unit.name
    : value === "none" || !value
      ? noneLabel
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
      {/* Mobile: fit viewport instead of fixed 400px (overflow on 375px). */}
      <PopoverContent className="w-[calc(100vw-2rem)] max-w-[400px] sm:w-[400px] p-0" align="start">
        <Command>
          <CommandInput placeholder="Tim kiem don vi..." />
          <CommandEmpty>Khong tim thay don vi nao.</CommandEmpty>
          {/* onTouchMove/onWheel stopPropagation: see SmartOfferingSelector —
              defeats Radix Dialog react-remove-scroll touch-lock so the
              portaled popover list scrolls on mobile. */}
          <CommandGroup
            className="max-h-[300px] overflow-auto overscroll-contain"
            onTouchMove={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
          >
            {allowNone && (
              <CommandItem
                value="none"
                onSelect={() => {
                  onChange(undefined);
                  setOpen(false);
                }}
              >
                <Check
                  className={cn(
                    "mr-2 h-4 w-4",
                    !value || value === "none" ? "opacity-100" : "opacity-0"
                  )}
                />
                <span className="font-semibold">{noneLabel}</span>
              </CommandItem>
            )}
            {units.map((item) => (
              <CommandItem
                key={item.unit.id}
                value={`${item.unit.name} ${item.unit.type}`}
                onSelect={() => {
                  onChange(String(item.unit.id));
                  setOpen(false);
                }}
              >
                <Check
                  className={cn(
                    "mr-2 h-4 w-4",
                    value === String(item.unit.id) ? "opacity-100" : "opacity-0"
                  )}
                />
                <div className="flex items-center gap-2">
                  <span className={cn("font-mono", item.level === 0 && "font-semibold")}>
                    {item.displayName}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    ({item.unit.type})
                  </span>
                </div>
              </CommandItem>
            ))}
          </CommandGroup>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function SmartUnitSelector({
  value,
  onChange,
  placeholder = "Chon don vi",
  allowNone = false,
  noneLabel = "Khong co (cap cao nhat)",
  excludeUnitId,
  filterTypes,
  activeOnly = true,
  disabled = false,
  variant = "select",
  className,
}: SmartUnitSelectorProps) {
  // Fetch units
  const { data: allUnits = [], isLoading } = useOrganizationUnits();

  // Process units with filtering
  const processedUnits = useMemo(
    () =>
      processUnits(allUnits, {
        excludeUnitId,
        filterTypes,
        activeOnly,
      }),
    [allUnits, excludeUnitId, filterTypes, activeOnly]
  );

  // Render based on variant
  const commonProps = {
    value,
    onChange,
    placeholder,
    allowNone,
    noneLabel,
    disabled,
    units: processedUnits,
    isLoading,
    className,
  };

  if (variant === "combobox") {
    return <ComboboxVariant {...commonProps} />;
  }

  return <SelectVariant {...commonProps} />;
}

export default SmartUnitSelector;
