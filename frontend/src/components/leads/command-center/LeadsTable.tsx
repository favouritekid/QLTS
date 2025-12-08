// src/components/leads/command-center/LeadsTable.tsx
/**
 * LeadsTable - Data table for leads with sorting, selection, and animations
 * 
 * Features:
 * - @tanstack/react-table for state management
 * - Row selection with keyboard navigation
 * - Sortable columns
 * - Smooth hover/select animations
 * - Footer with pagination
 */

"use client";

import React, { useMemo, useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
} from "@tanstack/react-table";
import { format } from "date-fns";
import { vi } from "date-fns/locale";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  MoreHorizontal,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableFooter,
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
}

// =============================================================================
// COLUMN HELPER
// =============================================================================

const columnHelper = createColumnHelper<Lead>();

// Get source label
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
}: LeadsTableProps) {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});

  const totalPages = Math.ceil(totalCount / pageSize);

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
          <div className="font-medium">{row.original.full_name || "—"}</div>
        ),
      }),

      // Phone column (no icon)
      columnHelper.accessor("phone", {
        header: "SĐT",
        cell: ({ row }) => (
          <div className="text-muted-foreground font-mono text-sm">
            {row.original.phone || "—"}
          </div>
        ),
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
      }),

      // Consultation Status column
      columnHelper.accessor("consultation_status", {
        header: "Trạng thái TĐ",
        cell: ({ row }) => {
          const status = row.original.consultation_status;
          if (!status) return <span className="text-muted-foreground text-sm">—</span>;
          return (
            <Badge
              variant="secondary"
              className="text-xs font-normal"
              style={{
                backgroundColor: status.color ? `${status.color}20` : undefined,
                color: status.color || undefined,
              }}
            >
              {status.name}
            </Badge>
          );
        },
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
      }),

      // Created at column
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
    },
    enableRowSelection: true,
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // Handle row click
  const handleRowClick = useCallback(
    (lead: Lead) => {
      onSelectLead(lead);
    },
    [onSelectLead]
  );

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
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader className="bg-muted/50 sticky top-0 z-10">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    style={{ width: header.getSize() }}
                    className="h-10 whitespace-nowrap"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-32 text-center">
                  <div className="text-muted-foreground">
                    Không có lead nào phù hợp với bộ lọc
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => {
                const isSelected = row.original.id === selectedLeadId;
                return (
                  <TableRow
                    key={row.id}
                    data-state={isSelected ? "selected" : undefined}
                    onClick={() => handleRowClick(row.original)}
                    className={cn(
                      "cursor-pointer transition-all duration-150",
                      "hover:bg-muted/50",
                      isSelected && "bg-primary/5 border-l-primary border-l-2"
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className="py-3">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {/* Table Footer with Pagination */}
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
    </div>
  );
}

export default LeadsTable;
