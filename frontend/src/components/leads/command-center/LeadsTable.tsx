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
import { useQueryClient } from "@tanstack/react-query";
import { leadsKeys } from "@/hooks/useLeads";
import { leadsApi } from "@/lib/api/leads"; // architecture-allow legacy
import { useRouter } from "next/navigation";
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
  Zap,
  Edit,
  Trash2,
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn, sanitizeColorCode } from "@/lib/utils";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { DynamicColorBadge } from "@/components/ui/dynamic-color-badge";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";
import type { Lead } from "@/types/lead.types";
import { LEAD_SOURCE_OPTIONS } from "@/constants";
import { STAGE_COLORS } from "@/types/pipeline.types";
import { TableToolbar, type DensityMode } from "./TableToolbar";
import { BulkActionsBar } from "./BulkActionsBar";
import { CopyableCell } from "@/components/common/CopyableCell";
import { ActivityIndicator } from "@/components/common/ActivityIndicator";
import { UrgencyBadge } from "@/components/common/UrgencyBadge";
import { EmptyLeadsState } from "./EmptyLeadsState";
import { MobileLeadList } from "./MobileLeadCard";

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
  // ✅ Phase 3: Contextual empty state props
  hasFilters?: boolean;
  searchQuery?: string;
  onResetFilters?: () => void;
  onCreateLead?: () => void;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const COLUMN_VISIBILITY_STORAGE_KEY = "leads_table_columns";
const DENSITY_MODE_STORAGE_KEY = "leads_table_density";
const SORTING_STORAGE_KEY = "leads_table_sorting";

// Default sort: urgency_score DESC (most urgent leads first)
const DEFAULT_SORTING: SortingState = [{ id: "cached_urgency_score", desc: true }];

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
// ROW ACTIONS COMPONENT - Responsive (mobile: action sheet, desktop: dropdown)
// =============================================================================

interface RowActionsProps {
  lead: Lead;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
}

function RowActions({ lead, onEdit, onDelete }: RowActionsProps) {
  const isMobile = useIsMobile();
  const [actionSheetOpen, setActionSheetOpen] = React.useState(false);

  if (isMobile) {
    return (
      <>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0"
          onClick={(e) => {
            e.stopPropagation();
            setActionSheetOpen(true);
          }}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
        <MobileActionSheet
          open={actionSheetOpen}
          onOpenChange={setActionSheetOpen}
          title={lead.full_name}
        >
          <MobileActionSheet.Item
            icon={Edit}
            onClick={() => {
              setActionSheetOpen(false);
              onEdit(lead);
            }}
          >
            Chỉnh sửa
          </MobileActionSheet.Item>
          <MobileActionSheet.Item
            icon={Trash2}
            variant="destructive"
            onClick={() => {
              setActionSheetOpen(false);
              onDelete(lead);
            }}
          >
            Xóa
          </MobileActionSheet.Item>
          <MobileActionSheet.Cancel onClick={() => setActionSheetOpen(false)} />
        </MobileActionSheet>
      </>
    );
  }

  return (
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
        <DropdownMenuItem onClick={() => onEdit(lead)}>
          Chỉnh sửa
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => onDelete(lead)}
          className="text-destructive"
        >
          Xóa
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

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
  // ✅ Phase 3: Contextual empty state props
  hasFilters = false,
  searchQuery = "",
  onResetFilters,
  onCreateLead,
}: LeadsTableProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const tableContainerRef = useRef<HTMLDivElement>(null);
  
  // ✅ Sorting state with localStorage persistence and default urgency sort
  const [sorting, setSorting] = React.useState<SortingState>(DEFAULT_SORTING);
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [columnResizeMode] = React.useState<ColumnResizeMode>("onChange");
  const [focusedRowIndex, setFocusedRowIndex] = React.useState<number>(-1);
  
  // Load persisted states - START with defaults, then hydrate from localStorage
  const [densityMode, setDensityMode] = React.useState<DensityMode>('regular');
  // Default: hide phone column for privacy protection
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({ phone: false });
  const [isHydrated, setIsHydrated] = React.useState(false);

  // Hydrate from localStorage after mount to avoid SSR mismatch
  useEffect(() => {
    const savedDensity = localStorage.getItem(DENSITY_MODE_STORAGE_KEY);
    if (savedDensity && ['condensed', 'regular', 'relaxed'].includes(savedDensity)) {
      setDensityMode(savedDensity as DensityMode);
    }
    
    try {
      const savedVisibility = localStorage.getItem(COLUMN_VISIBILITY_STORAGE_KEY);
      if (savedVisibility) {
        const parsed = JSON.parse(savedVisibility);
        // Merge with defaults (user preferences override defaults)
        setColumnVisibility({ phone: false, ...parsed });
      }
    } catch {
      // Ignore parse errors
    }

    try {
      const savedSorting = localStorage.getItem(SORTING_STORAGE_KEY);
      if (savedSorting) {
        setSorting(JSON.parse(savedSorting));
      }
    } catch {
      // Ignore parse errors
    }
    
    setIsHydrated(true);
  }, []);

  const totalPages = Math.ceil(totalCount / pageSize);
  const densityConfig = DENSITY_CONFIG[densityMode];

  // Persist density mode (only after hydration)
  useEffect(() => {
    if (isHydrated) {
      localStorage.setItem(DENSITY_MODE_STORAGE_KEY, densityMode);
    }
  }, [densityMode, isHydrated]);

  // Persist column visibility (only after hydration)
  useEffect(() => {
    if (isHydrated) {
      localStorage.setItem(COLUMN_VISIBILITY_STORAGE_KEY, JSON.stringify(columnVisibility));
    }
  }, [columnVisibility, isHydrated]);

  // ✅ Persist sorting preference
  useEffect(() => {
    localStorage.setItem(SORTING_STORAGE_KEY, JSON.stringify(sorting));
  }, [sorting]);

  // Reset row selection when resetSelectionKey changes (after bulk actions)
  useEffect(() => {
    if (resetSelectionKey !== undefined) {
      setRowSelection({});
    }
  }, [resetSelectionKey]);

  // Reset focused row when leads data changes (after create/update/delete)
  useEffect(() => {
    setFocusedRowIndex(-1);
  }, [leads]);

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
            <Badge variant="outline" className="text-[10px] h-5 px-2 font-normal">
              {getSourceLabel(source)}
            </Badge>
          );
        },
        size: 90,
      }),

      // Pipeline Stage column
      columnHelper.accessor("pipeline_stage", {
        header: "Giai đoạn",
        cell: ({ row }) => {
          const stage = row.original.pipeline_stage;
          if (!stage) return <span className="text-muted-foreground">—</span>;
          // Use stage.color_code from database first, fallback to centralized STAGE_COLORS
          const color = sanitizeColorCode(stage.color_code) || STAGE_COLORS[stage.id] || "#6B7280";
          return (
            <Badge
              className="text-[10px] h-5 px-2 font-normal whitespace-nowrap"
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
        size: 110,
      }),

      // Consultation Status column - using DynamicColorBadge
      columnHelper.accessor("consultation_status", {
        header: "Trạng thái TĐ",
        cell: ({ row }) => {
          const status = row.original.consultation_status;
          if (!status) return <span className="text-muted-foreground">—</span>;
          return (
            <DynamicColorBadge
              color={status.color || status.color_code}
              variant="subtle"
              size="sm"
              className="text-[10px] h-5 px-2 whitespace-nowrap"
            >
              {status.name}
            </DynamicColorBadge>
          );
        },
        size: 110,
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

      // Lead Score column - ✅ Now sortable
      columnHelper.accessor("lead_score", {
        header: ({ column }) => (
          <Button
            variant="ghost"
            className="-ml-3 h-8 font-medium"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          >
            Điểm
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
          const score = row.original.lead_score ?? 0;
          // Color coding based on score ranges
          let colorClass = "text-muted-foreground";
          if (score >= 70) colorClass = "text-success-600 font-semibold";
          else if (score >= 50) colorClass = "text-info-600 font-medium";
          else if (score >= 30) colorClass = "text-warning-600";
          return (
            <div className={cn("text-sm text-right tabular-nums pr-2", colorClass)}>
              {score}
            </div>
          );
        },
        size: 80,
      }),

      // Activity column - ✅ FIX: Sort by last_consultation_at || created_at (same as display)
      columnHelper.accessor(
        (row) => row.last_consultation_at || row.created_at,
        {
          id: "activity",
          header: ({ column }) => (
            <Button
              variant="ghost"
              className="-ml-3 h-8 font-medium"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              Hoạt động
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
            <ActivityIndicator
              date={row.original.last_consultation_at || row.original.created_at}
              nextActivityAt={row.original.next_activity_at}
            />
          ),
          sortingFn: (rowA, rowB) => {
            const dateA = new Date(rowA.original.last_consultation_at || rowA.original.created_at).getTime();
            const dateB = new Date(rowB.original.last_consultation_at || rowB.original.created_at).getTime();
            return dateA - dateB;
          },
          size: 100,
        }
      ),

      // Urgency Score column (Lead Insights Upgrade)
      columnHelper.accessor("cached_urgency_score", {
        header: ({ column }) => (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  className="-ml-3 h-8 w-8 p-0"
                  onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
                >
                  <Zap className="h-4 w-4 text-amber-500" />
                  {column.getIsSorted() === "asc" ? (
                    <ArrowUp className="ml-0.5 h-3 w-3" />
                  ) : column.getIsSorted() === "desc" ? (
                    <ArrowDown className="ml-0.5 h-3 w-3" />
                  ) : null}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Độ khẩn cấp</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ),
        cell: ({ row }) => (
          <UrgencyBadge score={row.original.cached_urgency_score} showLabel={false} />
        ),
        size: 50,
      }),

      // Actions column - Responsive (mobile: action sheet, desktop: dropdown)
      columnHelper.display({
        id: "actions",
        cell: ({ row }) => (
          <RowActions
            lead={row.original}
            onEdit={onEditLead}
            onDelete={onDeleteLead}
          />
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
    onSortingChange: (updater) => {
      setSorting(updater);
      setFocusedRowIndex(-1); // Reset focus when sorting changes
    },
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

      // Skip if typing in input/textarea
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") {
        return;
      }

      // If focus is on table or no specific focus (for global shortcuts)
      const isTableFocused = tableContainerRef.current?.contains(document.activeElement);
      
      const rows = table.getRowModel().rows;
      if (rows.length === 0) return;

      switch (e.key) {
        // ✅ Phase 3: Vim-style navigation
        case "j":
        case "ArrowDown":
          e.preventDefault();
          if (focusedRowIndex === -1) {
            setFocusedRowIndex(0);
          } else {
            setFocusedRowIndex((prev) => Math.min(prev + 1, rows.length - 1));
          }
          break;
        case "k":
        case "ArrowUp":
          e.preventDefault();
          if (focusedRowIndex === -1) {
            setFocusedRowIndex(rows.length - 1);
          } else {
            setFocusedRowIndex((prev) => Math.max(prev - 1, 0));
          }
          break;
        case "Enter":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < rows.length) {
            onSelectLead(rows[focusedRowIndex].original);
          }
          break;
        case " ":
          if (isTableFocused) {
            e.preventDefault();
            if (focusedRowIndex >= 0 && focusedRowIndex < rows.length) {
              rows[focusedRowIndex].toggleSelected();
            }
          }
          break;
        // ✅ Phase 3: 'e' to edit focused lead
        case "e":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < rows.length) {
            onEditLead(rows[focusedRowIndex].original);
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
  }, [table, focusedRowIndex, onSelectLead, onEditLead, onSearchFocus, handleClearSelection]);

  // Check if mobile
  const isMobile = useIsMobile();

  // Loading skeleton
  if (isLoading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: isMobile ? 5 : 10 }).map((_, i) => (
          <Skeleton key={i} className={isMobile ? "h-20 w-full rounded-lg" : "h-12 w-full"} />
        ))}
      </div>
    );
  }

  // ==========================================================================
  // MOBILE VIEW - Card-based layout for better touch experience
  // ==========================================================================
  if (isMobile) {
    return (
      <div className="flex h-full flex-col">
        {/* Mobile Header */}
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-muted-foreground text-sm">
            {selectedLeads.length > 0 ? (
              <span className="text-primary font-medium">{selectedLeads.length} đã chọn</span>
            ) : (
              `${totalCount.toLocaleString()} lead`
            )}
          </span>
        </div>

        {/* Mobile List */}
        <div className="flex-1 overflow-y-auto">
          {leads.length === 0 ? (
            <div className="p-4">
              <EmptyLeadsState
                hasFilters={hasFilters}
                searchQuery={searchQuery}
                totalCount={totalCount}
                onResetFilters={onResetFilters}
                onCreateLead={onCreateLead}
              />
            </div>
          ) : (
            <MobileLeadList
              leads={leads}
              selectedLeadId={selectedLeadId}
              onSelectLead={onSelectLead}
              onEditLead={onEditLead}
              onDeleteLead={onDeleteLead}
            />
          )}
        </div>

        {/* Mobile Pagination */}
        <div className="flex items-center justify-between border-t px-3 py-2">
          <span className="text-muted-foreground text-xs">
            {leads.length > 0 ? (page - 1) * pageSize + 1 : 0}-{Math.min(page * pageSize, totalCount)} / {totalCount}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange?.(page - 1)}
              disabled={page <= 1}
              className="h-8 w-8 p-0"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-muted-foreground min-w-[60px] text-center text-xs">
              {page}/{totalPages || 1}
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

  // ==========================================================================
  // DESKTOP VIEW - Table with virtualization
  // ==========================================================================
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
        {/* ✅ Phase 3: ARIA improvements for accessibility */}
        <Table 
          className="w-full"
          role="grid"
          aria-label="Danh sách lead"
          aria-rowcount={totalCount}
        >
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
                <TableCell colSpan={columns.length} className="h-64">
                  {/* ✅ Phase 3: Contextual empty state */}
                  <EmptyLeadsState
                    hasFilters={hasFilters}
                    searchQuery={searchQuery}
                    totalCount={totalCount}
                    onResetFilters={onResetFilters}
                    onCreateLead={onCreateLead}
                  />
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
                      // ✅ Phase 3: ARIA attributes for accessibility
                      role="row"
                      aria-rowindex={(page - 1) * pageSize + virtualRow.index + 1}
                      aria-selected={isSelected}
                      tabIndex={isFocused ? 0 : -1}
                      onClick={() => handleRowClick(row.original, virtualRow.index)}
                      onDoubleClick={() => router.push(`/leads/${row.original.id}`)}
                      // ✅ Phase 1: Prefetch lead detail on hover for instant panel load
                      onMouseEnter={() => {
                        queryClient.prefetchQuery({
                          queryKey: leadsKeys.detail(row.original.id),
                          queryFn: () => leadsApi.getLead(row.original.id),
                          staleTime: 1000 * 30, // 30 seconds
                        });
                      }}
                      className={cn(
                        "cursor-pointer transition-all duration-150",
                        "border-b border-border/50", // Consistent row dividers
                        "hover:bg-muted/50",
                        // Zebra stripes for better readability
                        virtualRow.index % 2 === 1 && !isSelected && !isFocused && "bg-muted/40",
                        // ✅ Phase 2: Enhanced selected row - prominent background, left border, and subtle shadow
                        isSelected && "bg-primary/10 border-l-primary border-l-3 hover:bg-primary/15 shadow-sm",
                        // Focused row (keyboard nav) - visible highlight
                        isFocused && !isSelected && "bg-info-50 dark:bg-info-950/30 border-l-info-500 border-l-2"
                      )}
                      style={{ 
                        height: virtualRow.size,
                        // ✅ Phase 2: Subtle scale on selection for visual pop
                        transform: isSelected ? 'scaleX(1.005)' : 'scaleX(1)',
                        transformOrigin: 'left center',
                      }}
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
