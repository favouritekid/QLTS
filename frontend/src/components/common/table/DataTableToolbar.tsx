// src/components/common/table/DataTableToolbar.tsx
"use client";

import * as React from "react";
import { Table } from "@tanstack/react-table";
import { Settings2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { SearchInput } from "../form/SearchInput";
import { cn } from "@/lib/utils";

// =============================================================================
// TYPES
// =============================================================================

export interface DataTableToolbarProps<TData> {
  /** Table instance */
  table: Table<TData>;
  /** Show search input */
  showSearch?: boolean;
  /** Search placeholder */
  searchPlaceholder?: string;
  /** Current global filter value */
  globalFilter: string;
  /** Callback when global filter changes */
  onGlobalFilterChange: (value: string) => void;
  /** Show column visibility toggle */
  showColumnToggle?: boolean;
  /** Loading state */
  isLoading?: boolean;
  /** Custom filters */
  filters?: React.ReactNode;
  /** Custom actions */
  actions?: React.ReactNode;
  /** Class name */
  className?: string;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function DataTableToolbar<TData>({
  table,
  showSearch = true,
  searchPlaceholder = "Tim kiem...",
  globalFilter,
  onGlobalFilterChange,
  showColumnToggle = true,
  isLoading = false,
  filters,
  actions,
  className,
}: DataTableToolbarProps<TData>) {
  // Get active column filters
  const activeFilters = table.getState().columnFilters;
  const hasFilters = activeFilters.length > 0 || globalFilter.length > 0;

  // Reset all filters
  const handleResetFilters = React.useCallback(() => {
    table.resetColumnFilters();
    onGlobalFilterChange("");
  }, [table, onGlobalFilterChange]);

  return (
    <div className={cn("flex flex-col sm:flex-row items-start sm:items-center gap-4", className)}>
      {/* Left side - Search and filters */}
      <div className="flex flex-1 items-center gap-2 flex-wrap">
        {/* Global search */}
        {showSearch && (
          <SearchInput
            value={globalFilter}
            onChange={onGlobalFilterChange}
            placeholder={searchPlaceholder}
            isLoading={isLoading}
            containerClassName="w-full sm:w-[300px]"
          />
        )}

        {/* Custom filters */}
        {filters}

        {/* Active filter badges */}
        {activeFilters.map((filter) => (
          <Badge
            key={filter.id}
            variant="secondary"
            className="flex items-center gap-1"
          >
            {filter.id}: {String(filter.value)}
            <Button
              variant="ghost"
              size="icon"
              className="h-4 w-4 p-0 hover:bg-transparent"
              onClick={() => table.getColumn(filter.id)?.setFilterValue(undefined)}
              aria-label="Xóa bộ lọc"
            >
              <X className="h-3 w-3" />
            </Button>
          </Badge>
        ))}

        {/* Reset filters button */}
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleResetFilters}
            className="h-10 md:h-8 px-3 lg:px-3"
          >
            Xoa bo loc
            <X className="ml-2 h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Right side - Actions and column toggle */}
      <div className="flex items-center gap-2">
        {/* Custom actions */}
        {actions}

        {/* Column visibility toggle */}
        {showColumnToggle && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="ml-auto h-10 md:h-8">
                <Settings2 className="mr-2 h-4 w-4" />
                Cột
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[180px]">
              <DropdownMenuLabel>Hiển thị cột</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {table
                .getAllColumns()
                .filter((column) => column.getCanHide())
                .map((column) => {
                  return (
                    <DropdownMenuCheckboxItem
                      key={column.id}
                      className="capitalize"
                      checked={column.getIsVisible()}
                      onCheckedChange={(value) => column.toggleVisibility(!!value)}
                    >
                      {column.id}
                    </DropdownMenuCheckboxItem>
                  );
                })}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  );
}

export default DataTableToolbar;
