// src/components/leads/command-center/LeadsTable.tsx
/**
 * LeadsTable - Advanced data table for leads
 * 
 * Features:
 * - @tanstack/react-table for state management
 * - @tanstack/react-virtual for virtualization (Option A)
 * - Row selection with keyboard navigation
 * - Sortable columns with column resize
 * - Compact/Normal view modes
 * - Column visibility toggle
 * - Footer with pagination
 * - Keyboard shortcuts
 */

"use client";

import React, { useMemo, useCallback, useEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
  type ColumnResizeMode,
  type VisibilityState,
} from "@tanstack/react-table";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  MoreHorizontal,
  ChevronLeft,
  SearchX,
  ChevronRight,
  GripVertical,
} from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Lead } from "@/types/lead.types";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { TableToolbar, type DensityMode } from "./TableToolbar";
import { BulkActionsBar } from "./BulkActionsBar";
import { CopyableCell } from "@/components/common/CopyableCell";

// =============================================================================
// TYPES
// =============================================================================

interface LeadsTableProps {
  leads: Lead[];
  selectedLeadId: number | null;
  onSelectLead: (lead: Lead) => void;
  onEditLead: (lead: Lead) => void;
  onDeleteLead: (lead: Lead) => void;
  isLoading?: boolean;
  // Pagination props
  page?: number;
  pageSize?: number;
  totalCount?: number;
  onPageChange?: (page: number) => void;
  // Bulk action handlers
  onBulkAssign?: (leads: Lead[]) => void;
  onBulkChangeStage?: (leads: Lead[]) => void;
  onBulkExport?: (leads: Lead[]) => void;
  onBulkDelete?: (leads: Lead[]) => void;
  // Search focus
  onSearchFocus?: () => void;
  // Reset selection when this key changes (e.g., after bulk action)
  resetSelectionKey?: number;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const COLUMN_VISIBILITY_STORAGE_KEY = "leads_table_columns";
const DENSITY_MODE_STORAGE_KEY = "leads_table_density";

// Density configuration
const DENSITY_CONFIG: Record<DensityMode, { rowHeight: number; cellPadding: string; headerHeight: string }> = {
  condensed: { rowHeight: 36, cellPadding: 'py-1', headerHeight: 'h-8' },
  regular: { rowHeight: 48, cellPadding: 'py-2', headerHeight: 'h-10' },
  relaxed: { rowHeight: 60, cellPadding: 'py-3', headerHeight: 'h-12' },
};

const columnHelper = createColumnHelper<Lead>();

const getSourceLabel = (value: string) =>
  LEAD_SOURCE_OPTIONS.find((o) => o.value === value)?.label || value;

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function LeadsTable({
  leads,
  selectedLeadId,
  onSelectLead,
  onEditLead,
  onDeleteLead,
  isLoading = false,
  page = 1,
  pageSize = 50,
  totalCount = 0,
  onPageChange,
  onBulkAssign,
  onBulkChangeStage,
  onBulkExport,
  onBulkDelete,
  onSearchFocus,
  resetSelectionKey,
}: LeadsTableProps) {
  const tableContainerRef = useRef<HTMLDivElement>(null);
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [columnResizeMode] = React.useState<ColumnResizeMode>("onChange");
  const [focusedRowIndex, setFocusedRowIndex] = React.useState<number>(-1);
  
  // Load persisted states
  const [densityMode, setDensityMode] = React.useState<DensityMode>(() => {
    if (typeof window === "undefined") return 'regular';
    const saved = localStorage.getItem(DENSITY_MODE_STORAGE_KEY);
    return (saved as DensityMode) || 'regular';
  });
  
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>(() => {
    if (typeof window === "undefined") return {};
    try {
      const saved = localStorage.getItem(COLUMN_VISIBILITY_STORAGE_KEY);
      return saved ? JSON.parse(saved) : {};
    } catch {
      return {};
    }
  });

  const totalPages = Math.ceil(totalCount / pageSize);
  const densityConfig = DENSITY_CONFIG[densityMode];

  // Persist density mode
  useEffect(() => {
    localStorage.setItem(DENSITY_MODE_STORAGE_KEY, densityMode);
  }, [densityMode]);

  // Persist column visibility
  useEffect(() => {
    localStorage.setItem(COLUMN_VISIBILITY_STORAGE_KEY, JSON.stringify(columnVisibility));
  }, [columnVisibility]);

  // Reset row selection when resetSelectionKey changes (after bulk actions)
  useEffect(() => {
    if (resetSelectionKey !== undefined) {
      setRowSelection({});
    }
  }, [resetSelectionKey]);

  // Column definitions
  const columns = useMemo(
    () => [
      // Checkbox column
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected() ||
              (table.getIsSomePageRowsSelected() && "indeterminate")
            }
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
            aria-label="Select all"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            onClick={(e) => e.stopPropagation()}
            aria-label="Select row"
          />
        ),
        size: 40,
        enableResizing: false,
        enableHiding: false,
      }),

      // Name column
      columnHelper.accessor("full_name", {
        header: ({ column }) => (
          <Button
            variant="ghost"
            className="-ml-3 h-8 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Tên Lead
            {column.getIsSorted() === "asc" ? (
              <ArrowUp className="ml-1 h-3.5 w-3.5" />
            ) : column.getIsSorted() === "desc" ? (
              <ArrowDown className="ml-1 h-3.5 w-3.5" />
            ) : (
              <ArrowUpDown className="ml-1 h-3.5 w-3.5 opacity-50" />
            )}
          </Button>
        ),
        cell: ({ row }) => (
          <div className="text-sm font-medium">{row.original.full_name || "—"}</div>
        ),
        size: 180,
      }),

      // Phone column - with copy to clipboard
      columnHelper.accessor("phone", {
        header: "SĐT",
        cell: ({ row }) => (
          <CopyableCell
            value={row.original.phone}
            label="số điện thoại"
            className="text-muted-foreground font-mono text-sm tabular-nums"
          />
        ),
        size: 120,
      }),

      // Source column
      columnHelper.accessor("source", {
        header: "Nguồn",
        cell: ({ row }) => {
          const source = row.original.source;
          if (!source) return <span className="text-muted-foreground">—</span>;
          return (
            <Badge variant="outline" className="text-xs font-normal">
              {getSourceLabel(source)}
            </Badge>
          );
        },
        size: 100,
      }),

      // Pipeline Stage column
      columnHelper.accessor("pipeline_stage", {
        header: "Giai đoạn",
        cell: ({ row }) => {
          const stage = row.original.pipeline_stage;
          if (!stage) return <span className="text-muted-foreground">—</span>;
          const color = STAGE_COLORS[stage.id] || "#6B7280";
          return (
            <Badge
              className="text-xs font-normal"
              style={{
                backgroundColor: `${color}20`,
                color: color,
                borderColor: color,
              }}
            >
              {stage.name}
            </Badge>
          );
        },
        size: 120,
      }),

      // Consultation Status column - text color from status.color
      columnHelper.accessor("consultation_status", {
        header: "Trạng thái TĐ",
        cell: ({ row }) => {
          const status = row.original.consultation_status;
          if (!status) return <span className="text-muted-foreground">—</span>;
          return (
            <Badge
              variant="secondary"
              className="text-xs font-normal"
            >
              <span style={{ color: status.color || "inherit" }}>
                {status.name}
              </span>
            </Badge>
          );
        },
        size: 130,
      }),

      // Officer column
      columnHelper.accessor("assigned_officer", {
        header: "Cán bộ",
        cell: ({ row }) => {
          const officer = row.original.assigned_officer;
          if (!officer) return <span className="text-muted-foreground text-sm">Chưa gán</span>;
          return (
            <div className="text-sm">{officer.full_name}</div>
          );
        },
        size: 140,
      }),

      // Lead Score column
      columnHelper.accessor("lead_score", {
        header: "Điểm",
        cell: ({ row }) => {
          const score = row.original.lead_score ?? 0;
          // Color coding based on score ranges
          let colorClass = "text-muted-foreground";
          if (score >= 70) colorClass = "text-green-600 font-semibold";
          else if (score >= 50) colorClass = "text-blue-600 font-medium";
          else if (score >= 30) colorClass = "text-yellow-600";
          return (
            <div className={cn("text-sm text-right tabular-nums pr-2", colorClass)}>
              {score}
            </div>
          );
        },
        size: 60,
      }),

      // Created at column - MEDIUM font
      columnHelper.accessor("created_at", {
        header: ({ column }) => (
          <Button
            variant="ghost"
            className="-ml-3 h-8 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Ngày tạo
            {column.getIsSorted() === "asc" ? (
              <ArrowUp className="ml-1 h-3.5 w-3.5" />
            ) : column.getIsSorted() === "desc" ? (
              <ArrowDown className="ml-1 h-3.5 w-3.5" />
            ) : (
              <ArrowUpDown className="ml-1 h-3.5 w-3.5 opacity-50" />
            )}
          </Button>
        ),
        cell: ({ row }) => {
          const date = row.original.created_at;
          if (!date) return "—";
          return (
            <div className="text-muted-foreground text-sm">
              {format(new Date(date), "dd/MM/yyyy", { locale: vi })}
            </div>
          );
        },
        size: 100,
      }),

      // Actions column
      columnHelper.display({
        id: "actions",
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onEditLead(row.original)}>
                Chỉnh sửa
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => onDeleteLead(row.original)}
                className="text-destructive"
              >
                Xóa
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
        size: 50,
        enableResizing: false,
        enableHiding: false,
      }),
    ],
    [onEditLead, onDeleteLead]
  );

  // Table instance
  const table = useReactTable({
    data: leads,
    columns,
    state: {
      sorting,
      rowSelection,
      columnVisibility,
    },
    enableRowSelection: true,
    enableColumnResizing: true,
    columnResizeMode,
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // Get all rows for virtualization
  const rows = table.getRowModel().rows;

  // ✅ Option A: Virtualization setup
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => tableScrollRef.current,
    estimateSize: () => densityConfig.rowHeight, // Dynamic row height based on density mode
    overscan: 5, // Render 5 extra rows above/below viewport
  });
  const virtualRows = rowVirtualizer.getVirtualItems();

  // Get selected leads
  const selectedLeads = useMemo(() => {
    const selectedRows = table.getSelectedRowModel().rows;
    return selectedRows.map((row) => row.original);
  }, [table, rowSelection]);

  // Handle row click
  const handleRowClick = useCallback(
    (lead: Lead, index: number) => {
      onSelectLead(lead);
      setFocusedRowIndex(index);
    },
    [onSelectLead]
  );

  // Clear selection
  const handleClearSelection = useCallback(() => {
    setRowSelection({});
  }, []);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // / to focus search
      if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        const target = e.target as HTMLElement;
        if (target.tagName !== "INPUT" && target.tagName !== "TEXTAREA") {
          e.preventDefault();
          onSearchFocus?.();
          return;
        }
      }

      // If focus is on table
      if (!tableContainerRef.current?.contains(document.activeElement)) {
        return;
      }

      const rows = table.getRowModel().rows;
      if (rows.length === 0) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.min(prev + 1, rows.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < rows.length) {
            onSelectLead(rows[focusedRowIndex].original);
          }
          break;
        case " ":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < rows.length) {
            rows[focusedRowIndex].toggleSelected();
          }
          break;
        case "Escape":
          e.preventDefault();
          handleClearSelection();
          setFocusedRowIndex(-1);
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [table, focusedRowIndex, onSelectLead, onSearchFocus, handleClearSelection]);

  // Loading skeleton
  if (isLoading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 10 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" ref={tableContainerRef} tabIndex={0}>
      {/* Toolbar */}
      <div className="bg-muted/30 flex shrink-0 items-center justify-between border-b px-4 py-2">
        <span className="text-muted-foreground text-sm">
          {selectedLeads.length > 0 ? (
            <span className="text-primary font-medium">{selectedLeads.length} đã chọn</span>
          ) : (
            `${leads.length} lead`
          )}
        </span>
        <TableToolbar
          densityMode={densityMode}
          onDensityChange={setDensityMode}
          columnVisibility={columnVisibility}
          onColumnVisibilityChange={(columnId, isVisible) => {
            setColumnVisibility((prev) => ({
              ...prev,
              [columnId]: isVisible,
            }));
          }}
        />
      </div>

      {/* Table with Virtualization */}
      <div 
        ref={tableScrollRef}
        className="flex-1 overflow-x-auto overflow-y-auto"
      >
        <Table className="w-full">
          <TableHeader className="bg-muted/50 sticky top-0 z-10">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className={cn(
                      "relative whitespace-nowrap",
                      densityConfig.headerHeight
                    )}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                    {/* Resize handle */}
                    {header.column.getCanResize() && (
                      <div
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        className={cn(
                          "absolute top-0 right-0 h-full w-1 cursor-col-resize select-none touch-none",
                          "hover:bg-primary/50 active:bg-primary",
                          header.column.getIsResizing() && "bg-primary"
                        )}
                      />
                    )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-48 text-center">
                  <div className="flex flex-col items-center justify-center gap-3">
                    <SearchX className="h-12 w-12 text-muted-foreground/40" />
                    <div>
                      <p className="font-medium text-foreground">Không tìm thấy lead</p>
                      <p className="text-muted-foreground text-sm">Thử điều chỉnh bộ lọc hoặc tìm kiếm</p>
                    </div>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              <>
                {/* Virtualization spacer - top */}
                {virtualRows.length > 0 && virtualRows[0].start > 0 && (
                  <tr style={{ height: virtualRows[0].start }} />
                )}
                {/* Virtualized rows */}
                {virtualRows.map((virtualRow) => {
                  const row = rows[virtualRow.index];
                  const isSelected = row.original.id === selectedLeadId;
                  const isFocused = virtualRow.index === focusedRowIndex;
                  return (
                    <TableRow
                      key={row.id}
                      data-index={virtualRow.index}
                      data-state={isSelected ? "selected" : undefined}
                      onClick={() => handleRowClick(row.original, virtualRow.index)}
                      className={cn(
                        "cursor-pointer transition-all duration-150",
                        "border-b border-border/50", // Consistent row dividers
                        "hover:bg-muted/50",
                        // Zebra stripes for better readability
                        virtualRow.index % 2 === 1 && !isSelected && !isFocused && "bg-muted/40",
                        // Selected row - prominent background and left border
                        isSelected && "bg-primary/10 border-l-primary border-l-3 hover:bg-primary/15",
                        // Focused row (keyboard nav) - visible highlight
                        isFocused && !isSelected && "bg-blue-50 dark:bg-blue-950/30 border-l-blue-500 border-l-2"
                      )}
                      style={{ height: virtualRow.size }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          style={{ width: cell.column.getSize() }}
                          className={densityConfig.cellPadding}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })}
                {/* Virtualization spacer - bottom */}
                {virtualRows.length > 0 && (
                  <tr style={{ height: rowVirtualizer.getTotalSize() - (virtualRows[virtualRows.length - 1]?.end || 0) }} />
                )}
              </>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Footer with Pagination */}
      <div className="bg-muted/30 flex shrink-0 items-center justify-between border-t px-4 py-2">
        <div className="text-muted-foreground text-sm">
          Hiển thị {leads.length > 0 ? (page - 1) * pageSize + 1 : 0}-
          {Math.min(page * pageSize, totalCount)} / {totalCount.toLocaleString()} lead
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange?.(page - 1)}
            disabled={page <= 1}
            className="h-8 w-8 p-0"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-muted-foreground min-w-[100px] text-center text-sm">
            Trang {page} / {totalPages || 1}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange?.(page + 1)}
            disabled={page >= totalPages}
            className="h-8 w-8 p-0"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Bulk Actions Bar */}
      {onBulkAssign && onBulkChangeStage && onBulkExport && onBulkDelete && (
        <BulkActionsBar
          selectedLeads={selectedLeads}
          onClearSelection={handleClearSelection}
          onBulkAssign={onBulkAssign}
          onBulkChangeStage={onBulkChangeStage}
          onBulkExport={onBulkExport}
          onBulkDelete={onBulkDelete}
        />
      )}
    </div>
  );
}

export default LeadsTable;
