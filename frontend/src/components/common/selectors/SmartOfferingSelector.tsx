// src/components/common/selectors/SmartOfferingSelector.tsx
/**
 * SmartOfferingSelector - Reusable Program Offering Selector
 *
 * Features:
 * - Automatic data fetching via useAllProgramOfferings hook
 * - Grouped by DEGREE LEVEL (Đại học, Cao đẳng, Trung cấp)
 * - Shows "Ngành - Loại hình" format
 * - Searchable with Command component
 * - Collapsible groups with smooth scrolling
 * - Filter by unit, degree level, or active status
 *
 * Usage:
 * - LeadDialog (offering selection)
 * - LeadFilters (offering filter)
 * - DistributionRuleDialog
 */

"use client";

import { useState, useMemo } from "react";
import { Check, ChevronDown, ChevronRight, ChevronsUpDown } from "lucide-react";
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
  triggerName: string;
  programName: string;
  degreeLevel: string;
  searchText: string;
}

// Degree level display order and labels
const DEGREE_LEVEL_ORDER: Record<string, number> = {
  "Đại học": 1,
  "Cao đẳng": 2,
  "Trung cấp": 3,
};

const DEGREE_LEVEL_LABELS: Record<string, string> = {
  "Đại học": "🎓 ĐẠI HỌC",
  "Cao đẳng": "📚 CAO ĐẲNG",
  "Trung cấp": "📖 TRUNG CẤP",
};

// Compact bậc cho nhãn TRIGGER (giá trị đã chọn). Dropdown đã phân nhóm theo
// bậc, nhưng khi đóng lại trigger mất ngữ cảnh nhóm → "Công nghệ ô tô" không
// phân biệt được TC vs CĐ (2 offering cùng tên khác bậc). Thêm bậc rút gọn vào
// nhãn trigger để disambiguate.
const DEGREE_LEVEL_SHORT: Record<string, string> = {
  "Đại học": "ĐH",
  "Cao đẳng": "CĐ",
  "Trung cấp": "TC",
};

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
    .map((offering) => {
      const programName = offering.program?.name || "Chưa xác định";
      const degreeLevel = offering.program?.degree_level || "Khác";
      const offeringType = offering.offering_type || "Chính quy";

      const shortLevel = DEGREE_LEVEL_SHORT[degreeLevel];
      return {
        ...offering,
        // Display format trong dropdown: "Ngành - Loại hình" (bậc đã ở group header)
        displayName: `${programName} - ${offeringType}`,
        // Nhãn TRIGGER kèm bậc (TC/CĐ/ĐH) để giá trị đã chọn không nhập nhằng
        // khi mất ngữ cảnh nhóm.
        triggerName: shortLevel
          ? `${programName} (${shortLevel}) - ${offeringType}`
          : `${programName} - ${offeringType}`,
        programName,
        degreeLevel,
        // Search text includes all relevant fields + the short bậc (TC/CĐ/ĐH)
        // so a user who sees "(TC)" in the trigger can type "TC" to find it.
        searchText: `${programName} ${offeringType} ${degreeLevel} ${shortLevel ?? ""}`.toLowerCase(),
      };
    })
    .sort((a, b) => {
      // Sort by degree level first, then by program name
      const levelA = DEGREE_LEVEL_ORDER[a.degreeLevel] || 99;
      const levelB = DEGREE_LEVEL_ORDER[b.degreeLevel] || 99;
      if (levelA !== levelB) return levelA - levelB;
      return a.programName.localeCompare(b.programName);
    });
}

/**
 * Group offerings by degree level
 */
function groupByDegreeLevel(offerings: ProcessedOffering[]): Map<string, ProcessedOffering[]> {
  const groups = new Map<string, ProcessedOffering[]>();

  // Initialize groups in order
  for (const level of Object.keys(DEGREE_LEVEL_ORDER)) {
    groups.set(level, []);
  }
  groups.set("Khác", []); // For unknown levels

  for (const offering of offerings) {
    const key = offering.degreeLevel;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(offering);
  }

  // Remove empty groups
  for (const [key, value] of groups.entries()) {
    if (value.length === 0) {
      groups.delete(key);
    }
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
  const groupedOfferings = useMemo(() => groupByDegreeLevel(offerings), [offerings]);
  const selectedOffering = offerings.find((o) => String(o.id) === value);

  return (
    <Select
      value={value}
      onValueChange={(val) => onChange(val === "all" ? undefined : val)}
      disabled={disabled || isLoading}
    >
      <SelectTrigger className={className}>
        <SelectValue placeholder={isLoading ? "Đang tải…" : placeholder}>
          {selectedOffering && (
            <span className="truncate">{selectedOffering.triggerName}</span>
          )}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="max-h-[350px] overflow-y-auto">
        {allowAll && (
          <SelectItem value="all">
            <span className="font-semibold">{allLabel}</span>
          </SelectItem>
        )}
        {isLoading ? (
          <SelectItem value="loading" disabled>
            Đang tải chương trình...
          </SelectItem>
        ) : offerings.length === 0 ? (
          <SelectItem value="empty" disabled>
            Không có chương trình khả dụng
          </SelectItem>
        ) : (
          Array.from(groupedOfferings.entries()).map(([degreeLevel, levelOfferings]) => (
            <SelectGroup key={degreeLevel}>
              <SelectLabel className="text-xs font-bold text-primary bg-background py-1.5 px-2 -mx-1 sticky top-0 z-10 border-b">
                {DEGREE_LEVEL_LABELS[degreeLevel] || degreeLevel} ({levelOfferings.length})
              </SelectLabel>
              {levelOfferings.map((offering) => (
                <SelectItem key={offering.id} value={String(offering.id)} className="pl-4">
                  <span className="truncate">{offering.displayName}</span>
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
// COMBOBOX VARIANT COMPONENT (with collapsible groups)
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
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");

  const groupedOfferings = useMemo(() => groupByDegreeLevel(offerings), [offerings]);
  const selectedOffering = offerings.find((o) => String(o.id) === value);

  // Filter offerings based on search query
  const filteredGroups = useMemo(() => {
    if (!searchQuery.trim()) return groupedOfferings;

    const query = searchQuery.toLowerCase();
    const filtered = new Map<string, ProcessedOffering[]>();

    for (const [level, levelOfferings] of groupedOfferings.entries()) {
      const matchingOfferings = levelOfferings.filter(
        (o) => o.searchText.includes(query)
      );
      if (matchingOfferings.length > 0) {
        filtered.set(level, matchingOfferings);
      }
    }

    return filtered;
  }, [groupedOfferings, searchQuery]);

  const toggleGroup = (level: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  };

  const displayValue = selectedOffering
    ? selectedOffering.triggerName
    : value === "all" || !value
      ? allLabel
      : placeholder;

  // Calculate total offerings count
  const totalCount = offerings.length;

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
            {isLoading ? "Đang tải…" : displayValue}
          </span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      {/* Mobile: fit viewport (avoid 420px overflow on 375px screens).
          Desktop (sm+): keep the 420px design width. */}
      <PopoverContent className="w-[calc(100vw-2rem)] max-w-[420px] sm:w-[420px] p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="Tìm kiếm ngành, loại hình..."
            value={searchQuery}
            onValueChange={setSearchQuery}
          />
          {/* onTouchMove/onWheel stopPropagation: when this combobox renders
              inside a Radix Dialog (e.g. LeadDialog), the Dialog's
              react-remove-scroll attaches a bubble-phase document touchmove
              listener that preventDefault()s scroll on this portaled popover
              (it lives outside the dialog's scroll-lock shard). Stopping
              propagation here keeps the event from reaching that listener so
              native touch scroll works on mobile. Verified @375px. */}
          <div
            className="max-h-[350px] overflow-y-auto overscroll-contain"
            onTouchMove={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
          >
            <CommandEmpty>Không tìm thấy chương trình nào.</CommandEmpty>
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
                  <span className="ml-auto text-xs text-muted-foreground">
                    ({totalCount})
                  </span>
                </CommandItem>
              </CommandGroup>
            )}
            {Array.from(filteredGroups.entries()).map(([degreeLevel, levelOfferings]) => {
              const isCollapsed = collapsedGroups.has(degreeLevel) && !searchQuery;
              const label = DEGREE_LEVEL_LABELS[degreeLevel] || degreeLevel;

              return (
                <CommandGroup key={degreeLevel}>
                  {/* Collapsible Header */}
                  <div
                    className="flex items-center justify-between px-2 py-1.5 text-xs font-bold text-primary bg-background cursor-pointer hover:bg-muted transition-colors sticky top-0 z-10 border-b"
                    onClick={() => toggleGroup(degreeLevel)}
                  >
                    <div className="flex items-center gap-1.5">
                      {isCollapsed ? (
                        <ChevronRight className="h-3.5 w-3.5" />
                      ) : (
                        <ChevronDown className="h-3.5 w-3.5" />
                      )}
                      <span>{label}</span>
                    </div>
                    <span className="text-muted-foreground font-normal">
                      {levelOfferings.length} chương trình
                    </span>
                  </div>

                  {/* Offerings (collapsible) */}
                  {!isCollapsed &&
                    levelOfferings.map((offering) => (
                      <CommandItem
                        key={offering.id}
                        value={offering.searchText}
                        onSelect={() => {
                          onChange(String(offering.id));
                          setOpen(false);
                        }}
                        className="pl-6"
                      >
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4 flex-shrink-0",
                            value === String(offering.id) ? "opacity-100" : "opacity-0"
                          )}
                        />
                        <span className="truncate">{offering.displayName}</span>
                      </CommandItem>
                    ))}
                </CommandGroup>
              );
            })}
          </div>
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
  placeholder = "Chọn chương trình",
  allowAll = false,
  allLabel = "Tất cả chương trình",
  filterDegreeLevel,
  activeOnly = true,
  disabled = false,
  variant = "combobox", // Default to combobox for better UX with search
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
