// src/components/common/table/DataTable.tsx
"use client";

import * as React from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
  type VisibilityState,
  type RowSelectionState,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { Pagination } from "./Pagination";
import { DataTableToolbar } from "./DataTableToolbar";

// =============================================================================
// TYPES
// =============================================================================

export interface DataTableProps<TData, TValue> {
  /** Column definitions */
  columns: ColumnDef<TData, TValue>[];
  /** Data to display */
  data: TData[];
  /** Loading state */
  isLoading?: boolean;
  /** Show toolbar */
  showToolbar?: boolean;
  /** Show search in toolbar */
  showSearch?: boolean;
  /** Search placeholder */
  searchPlaceholder?: string;
  /** Searchable columns */
  searchableColumns?: string[];
  /** Show column visibility toggle */
  showColumnToggle?: boolean;
  /** Show pagination */
  showPagination?: boolean;
  /** Server-side pagination */
  serverSidePagination?: boolean;
  /** Total items (for server-side pagination) */
  totalItems?: number;
  /** Current page (for server-side pagination) */
  page?: number;
  /** Page size (for server-side pagination) */
  pageSize?: number;
  /** Callback when page changes (for server-side pagination) */
  onPageChange?: (page: number) => void;
  /** Callback when page size changes (for server-side pagination) */
  onPageSizeChange?: (size: number) => void;
  /** Enable row selection */
  enableRowSelection?: boolean;
  /** Callback when selection changes */
  onRowSelectionChange?: (rows: TData[]) => void;
  /** Empty state message */
  emptyMessage?: string;
  /** Table container class name */
  containerClassName?: string;
  /** Table class name */
  tableClassName?: string;
}

// =============================================================================
// SKELETON LOADER
// =============================================================================

function TableSkeleton({ columns, rows = 5 }: { columns: number; rows?: number }) {
  return (
    <TableBody>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TableRow key={rowIndex}>
          {Array.from({ length: columns }).map((_, colIndex) => (
            <TableCell key={colIndex}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </TableBody>
  );
}

// =============================================================================
// EMPTY STATE
// =============================================================================

function EmptyState({ colSpan, message }: { colSpan: number; message: string }) {
  return (
    <TableBody>
      <TableRow>
        <TableCell colSpan={colSpan} className="h-24 text-center">
          <div className="flex flex-col items-center justify-center text-muted-foreground">
            <p>{message}</p>
          </div>
        </TableCell>
      </TableRow>
    </TableBody>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function DataTable<TData, TValue>({
  columns,
  data,
  isLoading = false,
  showToolbar = true,
  showSearch = true,
  searchPlaceholder = "Tim kiem...",
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  searchableColumns: _searchableColumns, // TODO: Implement column-specific search
  showColumnToggle = true,
  showPagination = true,
  serverSidePagination = false,
  totalItems,
  page = 1,
  pageSize = 10,
  onPageChange,
  onPageSizeChange,
  enableRowSelection = false,
  onRowSelectionChange,
  emptyMessage = "Khong co du lieu",
  containerClassName,
  tableClassName,
}: DataTableProps<TData, TValue>) {
  // State
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({});
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [globalFilter, setGlobalFilter] = React.useState("");

  // Initialize table
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    // Sorting
    onSortingChange: setSorting,
    getSortedRowModel: getSortedRowModel(),
    // Filtering
    onColumnFiltersChange: setColumnFilters,
    getFilteredRowModel: getFilteredRowModel(),
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: "includesString",
    // Visibility
    onColumnVisibilityChange: setColumnVisibility,
    // Selection
    onRowSelectionChange: setRowSelection,
    enableRowSelection,
    // Pagination (client-side)
    getPaginationRowModel: serverSidePagination ? undefined : getPaginationRowModel(),
    // State
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
      globalFilter,
      pagination: serverSidePagination
        ? undefined
        : {
            pageIndex: 0,
            pageSize,
          },
    },
  });

  // Handle row selection change
  React.useEffect(() => {
    if (onRowSelectionChange) {
      const selectedRows = table.getSelectedRowModel().rows.map((row) => row.original);
      onRowSelectionChange(selectedRows);
    }
  }, [rowSelection, table, onRowSelectionChange]);

  // Calculate pagination values
  const paginationTotal = serverSidePagination
    ? totalItems || 0
    : table.getFilteredRowModel().rows.length;
  const paginationPage = serverSidePagination ? page : table.getState().pagination.pageIndex + 1;
  const paginationPageSize = serverSidePagination ? pageSize : table.getState().pagination.pageSize;

  // Handle client-side page change
  const handlePageChange = React.useCallback(
    (newPage: number) => {
      if (serverSidePagination && onPageChange) {
        onPageChange(newPage);
      } else {
        table.setPageIndex(newPage - 1);
      }
    },
    [serverSidePagination, onPageChange, table]
  );

  // Handle page size change
  const handlePageSizeChange = React.useCallback(
    (newSize: number) => {
      if (serverSidePagination && onPageSizeChange) {
        onPageSizeChange(newSize);
      } else {
        table.setPageSize(newSize);
      }
    },
    [serverSidePagination, onPageSizeChange, table]
  );

  return (
    <div className={cn("space-y-4", containerClassName)}>
      {/* Toolbar */}
      {showToolbar && (
        <DataTableToolbar
          table={table}
          showSearch={showSearch}
          searchPlaceholder={searchPlaceholder}
          globalFilter={globalFilter}
          onGlobalFilterChange={setGlobalFilter}
          showColumnToggle={showColumnToggle}
          isLoading={isLoading}
        />
      )}

      {/* Table */}
      <div className="rounded-md border">
        <Table className={tableClassName}>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>

          {/* Loading state */}
          {isLoading && <TableSkeleton columns={columns.length} />}

          {/* Empty state */}
          {!isLoading && data.length === 0 && (
            <EmptyState colSpan={columns.length} message={emptyMessage} />
          )}

          {/* Data rows */}
          {!isLoading && data.length > 0 && (
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && "selected"}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          )}
        </Table>
      </div>

      {/* Pagination */}
      {showPagination && paginationTotal > 0 && (
        <Pagination
          page={paginationPage}
          pageSize={paginationPageSize}
          total={paginationTotal}
          onPageChange={handlePageChange}
          onPageSizeChange={handlePageSizeChange}
          isLoading={isLoading}
        />
      )}
    </div>
  );
}

export default DataTable;
