// src/components/admin/organization/UnitList.tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Building2, Plus, Search, ChevronRight, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { UnitDialog } from "./UnitDialog";
import type { OrganizationUnit } from "@/types/organization.types";

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface UnitListProps {
  units: OrganizationUnit[];
  isLoading: boolean;
  selectedUnitId: number | null;
  onSelectUnit: (id: number | null) => void;
}

// =====================================================================
// UNIT TREE ITEM
// =====================================================================

interface UnitTreeItemProps {
  unit: OrganizationUnit;
  level: number;
  selectedUnitId: number | null;
  onSelectUnit: (id: number) => void;
  expandedUnits: Set<number>;
  onToggleExpand: (id: number) => void;
  showInactive: boolean; // Filter inactive children
}

function UnitTreeItem({
  unit,
  level,
  selectedUnitId,
  onSelectUnit,
  expandedUnits,
  onToggleExpand,
  showInactive,
}: UnitTreeItemProps) {
  const isSelected = unit.id === selectedUnitId;
  const hasChildren = unit.children && unit.children.length > 0;
  const isExpanded = expandedUnits.has(unit.id);
  const isInactive = !unit.is_active;
  // ✅ FIX: Remove level limit - allow unlimited nesting
  const canExpand = hasChildren;

  return (
    <div>
      {/* Unit Item */}
      <div
        className={cn(
          "hover:bg-accent flex cursor-pointer items-center gap-2 px-3 py-2 transition-colors",
          isSelected && "bg-accent border-primary border-l-2",
          isInactive && "opacity-50"
        )}
        style={{ paddingLeft: `${level * 1.5 + 0.75}rem` }}
        onClick={() => onSelectUnit(unit.id)}
      >
        {/* Expand/Collapse Icon */}
        {canExpand ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand(unit.id);
            }}
            className="hover:bg-muted rounded p-0.5"
          >
            {isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        ) : (
          <div className="h-5 w-5" /> // Spacer for alignment when no children
        )}

        {/* Icon */}
        <Building2 className="text-muted-foreground h-4 w-4 flex-shrink-0" />

        {/* Name */}
        <span className={cn("flex-1 truncate text-sm", isSelected && "font-medium")}>
          {unit.name}
        </span>

        {/* Badges */}
        <div className="flex items-center gap-1">
          {isInactive && (
            <Badge variant="outline" className="text-xs">
              Đã xóa
            </Badge>
          )}
          {/* Show user count badge */}
          {unit.user_count !== undefined && unit.user_count > 0 && (
            <Badge variant="secondary" className="text-xs">
              {unit.user_count}
            </Badge>
          )}
        </div>
      </div>

      {/* Children - ✅ FIX: Remove level limit to support unlimited nesting */}
      {hasChildren && isExpanded && (
        <div>
          {unit.children
            .filter((child) => (showInactive ? true : child.is_active))
            .map((child) => (
              <UnitTreeItem
                key={child.id}
                unit={child}
                level={level + 1}
                selectedUnitId={selectedUnitId}
                onSelectUnit={onSelectUnit}
                expandedUnits={expandedUnits}
                onToggleExpand={onToggleExpand}
                showInactive={showInactive}
              />
            ))}
        </div>
      )}
    </div>
  );
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function UnitList({ units, isLoading, selectedUnitId, onSelectUnit }: UnitListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [unitDialogOpen, setUnitDialogOpen] = useState(false);
  const [expandedUnits, setExpandedUnits] = useState<Set<number>>(new Set());
  const [showInactive, setShowInactive] = useState(false);

  // Handle expand/collapse
  const handleToggleExpand = (id: number) => {
    setExpandedUnits((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // ✅ Filter units with tree-aware search
  // Shows parent units if they match OR if any of their children match
  const filterUnits = (units: OrganizationUnit[]): OrganizationUnit[] => {
    if (!searchQuery) return units;

    return units.filter((unit) => {
      const matchesSearch = unit.name.toLowerCase().includes(searchQuery.toLowerCase());
      // ✅ CORRECT: Show parent if any children match (tree filtering)
      // This allows users to see the full hierarchy when searching
      const hasMatchingChildren =
        unit.children && unit.children.length > 0 && filterUnits(unit.children).length > 0;

      return matchesSearch || hasMatchingChildren;
    });
  };

  const filteredUnits = filterUnits(units);

  // ✅ CRITICAL FIX: Only render root units (children are rendered recursively by UnitTreeItem)
  const rootUnits = filteredUnits.filter((unit) => unit.parent_id === null);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="space-y-3 border-b p-4">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold font-display">
            <Building2 className="h-5 w-5" />
            Đơn vị tổ chức
          </h2>
          <Button size="sm" onClick={() => setUnitDialogOpen(true)}>
            <Plus className="mr-1 h-4 w-4" />
            Tạo
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="text-muted-foreground absolute top-2.5 left-3 h-4 w-4" />
          <Input
            placeholder="Tìm kiếm đơn vị..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-9 pl-9"
          />
        </div>

        {/* Show Inactive Checkbox */}
        <div className="flex items-center space-x-2">
          <Checkbox
            id="show-inactive"
            checked={showInactive}
            onCheckedChange={(checked) => setShowInactive(checked === true)}
          />
          <label
            htmlFor="show-inactive"
            className="text-muted-foreground cursor-pointer text-sm select-none"
          >
            Hiển thị đơn vị đã lưu trữ
          </label>
        </div>
      </div>

      {/* Units Tree */}
      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : rootUnits.length === 0 ? (
          <div className="text-muted-foreground p-8 text-center text-sm">
            {searchQuery ? "Không tìm thấy đơn vị nào" : "Chưa có đơn vị. Tạo đơn vị đầu tiên."}
          </div>
        ) : (
          <div className="py-2">
            {rootUnits.map((unit) => (
              <UnitTreeItem
                key={unit.id}
                unit={unit}
                level={0}
                selectedUnitId={selectedUnitId}
                onSelectUnit={onSelectUnit}
                expandedUnits={expandedUnits}
                onToggleExpand={handleToggleExpand}
                showInactive={showInactive}
              />
            ))}
          </div>
        )}
      </ScrollArea>

      {/* Create Unit Dialog */}
      <UnitDialog open={unitDialogOpen} onOpenChange={setUnitDialogOpen} unit={null} />
    </div>
  );
}
