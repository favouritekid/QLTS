// src/components/common/selectors/MultiOfferingSelector.tsx
/**
 * MultiOfferingSelector - Multi-select Program Offering Selector
 *
 * Features:
 * - Checkbox-based multi-select
 * - Grouped by DEGREE LEVEL (Đại học, Cao đẳng, Trung cấp)
 * - Shows "Ngành - Loại hình" format
 * - Collapsible groups
 * - Search filter
 *
 * Usage:
 * - LeadFilters (offering filter with multi-select)
 */

"use client";

import { useState, useMemo } from "react";
import { ChevronDown, ChevronRight, Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useAllProgramOfferings } from "@/hooks/useOrganization";
import type { ProgramOffering } from "@/types/organization.types";

// =============================================================================
// TYPES
// =============================================================================

export interface MultiOfferingSelectorProps {
  /** Array of selected offering IDs (as strings for form compatibility) */
  values: string[];
  /** Callback when selection changes */
  onChange: (values: string[]) => void;
  /** Filter to only show active offerings */
  activeOnly?: boolean;
  /** Additional CSS classes */
  className?: string;
}

interface ProcessedOffering extends ProgramOffering {
  displayName: string;
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

// =============================================================================
// HELPER FUNCTIONS (reused from SmartOfferingSelector)
// =============================================================================

function processOfferings(
  offerings: ProgramOffering[],
  options: { activeOnly?: boolean }
): ProcessedOffering[] {
  const { activeOnly = true } = options;

  return offerings
    .filter((offering) => {
      if (activeOnly && !offering.is_active) return false;
      return true;
    })
    .map((offering) => {
      const programName = offering.program?.name || "Chưa xác định";
      const degreeLevel = offering.program?.degree_level || "Khác";
      const offeringType = offering.offering_type || "Chính quy";

      return {
        ...offering,
        displayName: `${programName} - ${offeringType}`,
        programName,
        degreeLevel,
        searchText: `${programName} ${offeringType} ${degreeLevel}`.toLowerCase(),
      };
    })
    .sort((a, b) => {
      const levelA = DEGREE_LEVEL_ORDER[a.degreeLevel] || 99;
      const levelB = DEGREE_LEVEL_ORDER[b.degreeLevel] || 99;
      if (levelA !== levelB) return levelA - levelB;
      return a.programName.localeCompare(b.programName);
    });
}

function groupByDegreeLevel(offerings: ProcessedOffering[]): Map<string, ProcessedOffering[]> {
  const groups = new Map<string, ProcessedOffering[]>();

  for (const level of Object.keys(DEGREE_LEVEL_ORDER)) {
    groups.set(level, []);
  }
  groups.set("Khác", []);

  for (const offering of offerings) {
    const key = offering.degreeLevel;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(offering);
  }

  for (const [key, value] of groups.entries()) {
    if (value.length === 0) {
      groups.delete(key);
    }
  }

  return groups;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function MultiOfferingSelector({
  values,
  onChange,
  activeOnly = true,
  className,
}: MultiOfferingSelectorProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");

  // Fetch offerings
  const { data: offerings = [], isLoading } = useAllProgramOfferings();

  // Process offerings
  const processedOfferings = useMemo(
    () => processOfferings(offerings, { activeOnly }),
    [offerings, activeOnly]
  );

  // Group offerings
  const groupedOfferings = useMemo(
    () => groupByDegreeLevel(processedOfferings),
    [processedOfferings]
  );

  // Filter by search
  const filteredGroups = useMemo(() => {
    if (!searchQuery.trim()) return groupedOfferings;

    const query = searchQuery.toLowerCase();
    const filtered = new Map<string, ProcessedOffering[]>();

    for (const [level, levelOfferings] of groupedOfferings.entries()) {
      const matchingOfferings = levelOfferings.filter((o) =>
        o.searchText.includes(query)
      );
      if (matchingOfferings.length > 0) {
        filtered.set(level, matchingOfferings);
      }
    }

    return filtered;
  }, [groupedOfferings, searchQuery]);

  // Toggle group collapse
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

  // Toggle offering selection
  const handleToggle = (offeringId: string) => {
    if (values.includes(offeringId)) {
      onChange(values.filter((v) => v !== offeringId));
    } else {
      onChange([...values, offeringId]);
    }
  };

  // Count selected in each group
  const getGroupSelectedCount = (levelOfferings: ProcessedOffering[]) => {
    return levelOfferings.filter((o) => values.includes(String(o.id))).length;
  };

  if (isLoading) {
    return (
      <div className={cn("text-muted-foreground text-sm", className)}>
        Đang tải...
      </div>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      {/* Search Input */}
      <div className="relative">
        <Search className="text-muted-foreground absolute top-2 left-2 h-4 w-4" />
        <Input
          placeholder="Tìm chương trình..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="h-8 pl-8 pr-8 text-sm"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery("")}
            className="text-muted-foreground hover:text-foreground absolute top-2 right-2"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Groups */}
      <div className="max-h-64 space-y-1 overflow-y-auto">
        {Array.from(filteredGroups.entries()).map(([degreeLevel, levelOfferings]) => {
          const isCollapsed = collapsedGroups.has(degreeLevel) && !searchQuery;
          const label = DEGREE_LEVEL_LABELS[degreeLevel] || degreeLevel;
          const selectedCount = getGroupSelectedCount(levelOfferings);

          return (
            <div key={degreeLevel} className="rounded-md border">
              {/* Group Header */}
              <button
                type="button"
                onClick={() => toggleGroup(degreeLevel)}
                className="hover:bg-muted/50 flex w-full items-center justify-between px-2 py-1.5 text-left transition-colors"
              >
                <div className="flex items-center gap-1.5">
                  {isCollapsed ? (
                    <ChevronRight className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" />
                  )}
                  <span className="text-xs font-semibold">{label}</span>
                </div>
                <div className="flex items-center gap-2">
                  {selectedCount > 0 && (
                    <span className="bg-primary text-primary-foreground rounded-full px-1.5 py-0.5 text-[10px]">
                      {selectedCount}
                    </span>
                  )}
                  <span className="text-muted-foreground text-[10px]">
                    {levelOfferings.length}
                  </span>
                </div>
              </button>

              {/* Group Items */}
              {!isCollapsed && (
                <div className="border-t px-2 py-1.5">
                  <div className="space-y-1.5">
                    {levelOfferings.map((offering) => (
                      <div
                        key={offering.id}
                        className="flex items-center space-x-2"
                      >
                        <Checkbox
                          id={`offering-${offering.id}`}
                          checked={values.includes(String(offering.id))}
                          onCheckedChange={() => handleToggle(String(offering.id))}
                        />
                        <Label
                          htmlFor={`offering-${offering.id}`}
                          className="cursor-pointer truncate text-xs font-normal"
                          title={offering.displayName}
                        >
                          {offering.displayName}
                        </Label>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {filteredGroups.size === 0 && (
          <div className="text-muted-foreground py-4 text-center text-sm">
            {searchQuery ? "Không tìm thấy chương trình" : "Không có chương trình khả dụng"}
          </div>
        )}
      </div>
    </div>
  );
}

export default MultiOfferingSelector;
