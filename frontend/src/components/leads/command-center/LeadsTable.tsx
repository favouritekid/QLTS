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
  flexRender,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
  type ColumnResizeMode,
  type VisibilityState,
  type ColumnSizingState,
  type ColumnSizingInfoState,
  type ColumnOrderState,
  type Header,
} from "@tanstack/react-table";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ChevronLeft,
  ChevronRight,
  GripVertical,
  Zap,
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
import { LeadActionMenu } from "./LeadActionMenu";
import type { Lead } from "@/types/lead.types";
import { getLeadSourceLabel, getLeadScoreTextColor, getDegreeLevelAbbr } from "@/constants";
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
  /** "Gán cho cán bộ" cho lead chưa phân công (mở dialog gán ở parent). */
  onAssignLead: (lead: Lead) => void;
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
  // Server-side sorting
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  onSortChange?: (sortBy: string, sortOrder: "asc" | "desc") => void;
  /**
   * Layout-mode override from the parent (LeadsClient uses `!isDesktop`). Drives
   * the card-vs-table branch WITHOUT touching the shared `useIsMobile()` hook
   * (đổi hook global sẽ regression ResponsiveDialog/DataDisplay/ActionMenu).
   * Fallback về `useIsMobile()` khi undefined để không vỡ caller/test cũ.
   */
  isMobileLayout?: boolean;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const COLUMN_VISIBILITY_STORAGE_KEY = "leads_table_columns";
const DENSITY_MODE_STORAGE_KEY = "leads_table_density";
const COLUMN_SIZING_STORAGE_KEY = "leads_table_sizing";
const COLUMN_ORDER_STORAGE_KEY = "leads_table_order";

/** Cột tiện ích cố định 2 đầu (không kéo đổi thứ tự, không resize). */
const PINNED_START = "select";
const PINNED_END = "actions";

// Mapping between TanStack column IDs and backend sort_by field names
const COLUMN_TO_BACKEND_SORT: Record<string, string> = {
  full_name: "full_name",
  lead_score: "lead_score",
  activity: "last_consultation_at",
  cached_urgency_score: "cached_urgency_score",
};

const BACKEND_TO_COLUMN_SORT: Record<string, string> = {
  full_name: "full_name",
  lead_score: "lead_score",
  last_consultation_at: "activity",
  cached_urgency_score: "cached_urgency_score",
  created_at: "created_at", // no visible column, but valid backend field
};

// Density configuration
const DENSITY_CONFIG: Record<DensityMode, { rowHeight: number; cellPadding: string; headerHeight: string }> = {
  condensed: { rowHeight: 36, cellPadding: 'py-1', headerHeight: 'h-8' },
  regular: { rowHeight: 48, cellPadding: 'py-2', headerHeight: 'h-10' },
  relaxed: { rowHeight: 60, cellPadding: 'py-3', headerHeight: 'h-12' },
};

const columnHelper = createColumnHelper<Lead>();

// =============================================================================
// ROW ACTIONS COMPONENT — dùng chung LeadActionMenu (khớp card + panel)
// =============================================================================

interface RowActionsProps {
  lead: Lead;
  onEdit: (lead: Lead) => void;
  onDelete: (lead: Lead) => void;
  onAssign: (lead: Lead) => void;
}

function RowActions({ lead, onEdit, onDelete, onAssign }: RowActionsProps) {
  // stopPropagation: hàng có onClick chọn lead → không cho click menu chọn hàng.
  // triggerClassName h-8 giữ chiều cao hàng bảng ổn định.
  return (
    <LeadActionMenu
      lead={lead}
      onEdit={onEdit}
      onDelete={onDelete}
      onAssign={onAssign}
      variant="dropdown"
      sheetTitle={lead.full_name}
      triggerClassName="h-8 w-8 sm:h-8 sm:w-8"
      stopPropagation
    />
  );
}

// Thứ tự cột mặc định (khớp định nghĩa `columns` bên dưới). Dùng cho khởi tạo
// columnOrder (SSR-safe: server + client render cùng thứ tự) + nút "Đặt lại".
const DEFAULT_COLUMN_ORDER: ColumnOrderState = [
  "select",
  "full_name",
  "phone",
  "offering",
  "source",
  "pipeline_stage",
  "consultation_status",
  "assigned_officer",
  "lead_score",
  "activity",
  "cached_urgency_score",
  "actions",
];

// Nhãn hiển thị cho menu ẩn/hiện cột — key = column id (khớp DEFAULT_COLUMN_ORDER).
// KHÔNG hardcode LẠI danh sách cột nào ẩn/hiện được ở TableToolbar (dễ lệch
// contract): TableToolbar nhận thẳng list dẫn xuất từ `table.getAllLeafColumns()`
// đã lọc `getCanHide()`. Map này chỉ cấp NHÃN; thiếu nhãn → fallback về id (lộ
// ra ngay, không im lặng). `select`/`actions` `enableHiding:false` nên không vào
// menu → không cần nhãn.
const COLUMN_LABELS: Record<string, string> = {
  full_name: "Tên Lead",
  phone: "Số điện thoại",
  offering: "Ngành",
  source: "Nguồn",
  pipeline_stage: "Giai đoạn",
  consultation_status: "Trạng thái TĐ",
  assigned_officer: "Cán bộ",
  lead_score: "Điểm",
  activity: "Hoạt động",
  cached_urgency_score: "Độ khẩn cấp",
};

// =============================================================================
// DRAGGABLE HEADER — kéo grip đổi thứ tự (dnd-kit) · mép phải resize ·
// double-click mép = auto-fit. Grip / sort-button / resize-handle tách vùng
// tương tác nên KHÔNG xung đột nhau.
// =============================================================================

function DraggableHeader({
  header,
  headerHeightClass,
  onAutoFit,
}: {
  header: Header<Lead, unknown>;
  headerHeightClass: string;
  onAutoFit: (columnId: string) => void;
}) {
  const columnId = header.column.id;
  const reorderable = columnId !== PINNED_START && columnId !== PINNED_END;
  const { attributes, listeners, setNodeRef, transform, isDragging } = useSortable({
    id: columnId,
    disabled: !reorderable,
  });

  const style: React.CSSProperties = {
    width: header.getSize(),
    transform: CSS.Translate.toString(transform),
    transition: isDragging ? "transform 0s" : "transform 150ms ease",
    opacity: isDragging ? 0.65 : 1,
    zIndex: isDragging ? 5 : undefined,
  };

  return (
    <TableHead
      ref={setNodeRef}
      data-column-id={columnId}
      style={style}
      className={cn(
        "group/lh relative overflow-hidden whitespace-nowrap",
        // gutter TRÁI cho grip (chỉ cột kéo được) → grip nằm trong padding, KHÔNG
        // chồng lên nút sort → click sort không bị grip nuốt; nội dung cắt gọn sau.
        reorderable && "pl-4",
        headerHeightClass,
      )}
    >
      <div className="truncate">
        {header.isPlaceholder
          ? null
          : flexRender(header.column.columnDef.header, header.getContext())}
      </div>
      {reorderable && (
        // Overlay grip trong gutter, hiện-khi-hover. pointer-events-none khi ẩn →
        // không chặn hit-test; tabIndex=-1 → không là tab-stop no-op (đã bỏ KeyboardSensor).
        <button
          type="button"
          className={cn(
            "absolute left-0 top-0 z-[1] flex h-full w-4 items-center justify-center",
            "text-muted-foreground/50 hover:text-foreground cursor-grab touch-none",
            "pointer-events-none opacity-0 transition-opacity",
            "group-hover/lh:pointer-events-auto group-hover/lh:opacity-100 active:cursor-grabbing",
          )}
          aria-label="Kéo để đổi thứ tự cột"
          {...attributes}
          {...listeners}
          tabIndex={-1}
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>
      )}
      {/* Resize handle — double-click = auto-fit theo nội dung */}
      {header.column.getCanResize() && (
        <div
          onMouseDown={header.getResizeHandler()}
          onTouchStart={header.getResizeHandler()}
          onDoubleClick={() => onAutoFit(columnId)}
          title="Kéo để đổi rộng · double-click auto-fit"
          className={cn(
            "absolute top-0 right-0 h-full w-1.5 cursor-col-resize touch-none select-none",
            "hover:bg-primary/50 active:bg-primary",
            header.column.getIsResizing() && "bg-primary"
          )}
        />
      )}
    </TableHead>
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
  onAssignLead,
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
  sortBy = "created_at",
  sortOrder = "desc",
  onSortChange,
  isMobileLayout,
}: LeadsTableProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const tableContainerRef = useRef<HTMLDivElement>(null);
  
  // Derive TanStack sorting state from server-side sort props
  const sorting = React.useMemo<SortingState>(() => {
    const columnId = BACKEND_TO_COLUMN_SORT[sortBy];
    if (columnId) {
      return [{ id: columnId, desc: sortOrder === "desc" }];
    }
    return [];
  }, [sortBy, sortOrder]);
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [columnResizeMode] = React.useState<ColumnResizeMode>("onChange");
  const [focusedRowIndex, setFocusedRowIndex] = React.useState<number>(-1);
  
  // Load persisted states - START with defaults, then hydrate from localStorage
  const [densityMode, setDensityMode] = React.useState<DensityMode>('regular');
  // Default: hide phone column for privacy protection
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({ phone: false });
  // Bề rộng cột do người dùng kéo (persist) + thứ tự cột (kéo grip đổi chỗ).
  const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({});
  // Trạng thái đang-kéo-resize (isResizingColumn) → chỉ persist khi kéo XONG,
  // tránh spam localStorage.setItem mỗi tick pointer-move.
  const [columnSizingInfo, setColumnSizingInfo] = React.useState<ColumnSizingInfoState>({
    startOffset: null,
    startSize: null,
    deltaOffset: null,
    deltaPercentage: null,
    isResizingColumn: false,
    columnSizingStart: [],
  });
  const [columnOrder, setColumnOrder] = React.useState<ColumnOrderState>(DEFAULT_COLUMN_ORDER);
  const [isHydrated, setIsHydrated] = React.useState(false);

  // dnd-kit: kéo grip tiêu đề đổi thứ tự cột. PointerSensor có ngưỡng 6px →
  // click thường (sort/resize) KHÔNG kích hoạt drag. (KHÔNG dùng KeyboardSensor:
  // thiếu coordinateGetter nên arrow-reorder không chạy + đụng keydown-nav toàn
  // cục — bỏ để tránh dead-weight/glitch.)
  const dndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

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
      const savedSizing = localStorage.getItem(COLUMN_SIZING_STORAGE_KEY);
      if (savedSizing) {
        const parsed = JSON.parse(savedSizing);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          // CHỈ nhận entry là số hữu-hạn dương (giá trị phi-số như "180px" →
          // getSize() ra NaN → width NaN → sập layout).
          const clean: ColumnSizingState = {};
          for (const [k, v] of Object.entries(parsed)) {
            if (typeof v === "number" && Number.isFinite(v) && v > 0) clean[k] = v;
          }
          setColumnSizing(clean);
        }
      }
    } catch {
      // Ignore parse errors
    }

    try {
      const savedOrder = localStorage.getItem(COLUMN_ORDER_STORAGE_KEY);
      if (savedOrder) {
        const parsed = JSON.parse(savedOrder);
        // Chỉ nhận khi ĐÚNG tập cột hiện tại (chống order cũ/hỏng thiếu-thừa cột)
        // VÀ giữ pin-invariant (select đầu / actions cuối) — permutation lạ để
        // select ra giữa bảng sẽ bị từ chối.
        if (
          Array.isArray(parsed) &&
          parsed.length === DEFAULT_COLUMN_ORDER.length &&
          DEFAULT_COLUMN_ORDER.every((id) => parsed.includes(id)) &&
          parsed[0] === PINNED_START &&
          parsed[parsed.length - 1] === PINNED_END
        ) {
          setColumnOrder(parsed);
        }
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

  // Persist column sizing (only after hydration) — CHỜ kéo resize XONG
  // (isResizingColumn falsy) để không ghi localStorage mỗi tick pointer-move.
  useEffect(() => {
    if (!isHydrated || columnSizingInfo.isResizingColumn) return;
    try {
      localStorage.setItem(COLUMN_SIZING_STORAGE_KEY, JSON.stringify(columnSizing));
    } catch {
      /* ignore quota/serialize errors */
    }
  }, [columnSizing, columnSizingInfo.isResizingColumn, isHydrated]);

  useEffect(() => {
    if (!isHydrated) return;
    try {
      localStorage.setItem(COLUMN_ORDER_STORAGE_KEY, JSON.stringify(columnOrder));
    } catch {
      /* ignore quota/serialize errors */
    }
  }, [columnOrder, isHydrated]);

  // Reset row selection when resetSelectionKey changes (after bulk actions)
  useEffect(() => {
    if (resetSelectionKey !== undefined) {
      setRowSelection({});
    }
  }, [resetSelectionKey]);

  // ✅ T1 FIX: Reset selection when dataset changes (page/filter/sort) — page-scoped selection
  // This prevents selecting leads on page A then performing bulk action on page B's leads
  useEffect(() => {
    setRowSelection({});
  }, [page, sortBy, sortOrder]);

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
        minSize: 40, // ghi đè defaultColumn.minSize=60 (cột checkbox tiện ích)
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
          <div className="truncate text-sm font-medium" title={row.original.full_name || undefined}>
            {row.original.full_name || "—"}
          </div>
        ),
        size: 180,
        minSize: 110,
        maxSize: 340,
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
        minSize: 90,
        maxSize: 180,
      }),

      // Ngành column — đồng bộ với card list (trình độ viết tắt CĐ/TC + tên ngành)
      columnHelper.accessor("offering", {
        id: "offering",
        header: "Ngành",
        enableSorting: false,
        cell: ({ row }) => {
          const offering = row.original.offering;
          const major = offering?.program?.name || offering?.offering_type;
          if (!major) return <span className="text-muted-foreground">—</span>;
          const degreeShort = getDegreeLevelAbbr(offering?.program?.degree_level);
          return (
            <span className="flex min-w-0 items-center gap-1.5 text-sm" title={major}>
              {degreeShort && (
                <span className="bg-muted text-muted-foreground shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold">
                  {degreeShort}
                </span>
              )}
              <span className="min-w-0 flex-1 truncate">{major}</span>
            </span>
          );
        },
        size: 180,
        minSize: 110,
        maxSize: 360,
      }),

      // Source column
      columnHelper.accessor("source", {
        header: "Nguồn",
        cell: ({ row }) => {
          const source = row.original.source;
          if (!source) return <span className="text-muted-foreground">—</span>;
          return (
            <Badge variant="outline" className="text-[10px] h-5 px-2 font-normal whitespace-nowrap">
              {getLeadSourceLabel(source)}
            </Badge>
          );
        },
        size: 90,
        minSize: 72,
        maxSize: 160,
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
              title={stage.name}
              className="text-[10px] h-5 px-2 font-normal max-w-full min-w-0"
              style={{
                backgroundColor: `${color}20`,
                color: color,
                borderColor: color,
              }}
            >
              <span className="truncate">{stage.name}</span>
            </Badge>
          );
        },
        size: 110,
        minSize: 84,
        maxSize: 220,
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
              className="text-[10px] h-5 px-2 max-w-full min-w-0"
            >
              {status.name}
            </DynamicColorBadge>
          );
        },
        size: 110,
        minSize: 84,
        maxSize: 260,
      }),

      // Officer column
      columnHelper.accessor("assigned_officer", {
        header: "Cán bộ",
        cell: ({ row }) => {
          const officer = row.original.assigned_officer;
          if (!officer) return <span className="text-muted-foreground text-sm">Chưa gán</span>;
          return (
            <div className="truncate text-sm" title={officer.full_name}>{officer.full_name}</div>
          );
        },
        size: 140,
        minSize: 90,
        maxSize: 280,
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
          return (
            <div className={cn("text-sm text-right tabular-nums pr-2 font-medium", getLeadScoreTextColor(score).split(" ")[0])}>
              {score}
            </div>
          );
        },
        size: 80,
        minSize: 56,
        maxSize: 120,
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
          minSize: 80,
          maxSize: 180,
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
        minSize: 44,
        maxSize: 90,
      }),

      // Actions column - Responsive (mobile: action sheet, desktop: dropdown)
      columnHelper.display({
        id: "actions",
        cell: ({ row }) => (
          <RowActions
            lead={row.original}
            onEdit={onEditLead}
            onDelete={onDeleteLead}
            onAssign={onAssignLead}
          />
        ),
        size: 50,
        minSize: 48, // ghi đè defaultColumn.minSize=60 (cột hành động tiện ích)
        enableResizing: false,
        enableHiding: false,
      }),
    ],
    [onEditLead, onDeleteLead, onAssignLead]
  );

  // Table instance
  const table = useReactTable({
    data: leads,
    columns,
    // ✅ T1 FIX: Use lead.id as row identity instead of array index
    // This ensures selection maps to actual lead IDs, not positional indices
    getRowId: (row) => String(row.id),
    state: {
      sorting,
      rowSelection,
      columnVisibility,
      columnSizing,
      columnSizingInfo,
      columnOrder,
    },
    defaultColumn: { minSize: 60, maxSize: 400 },
    enableRowSelection: true,
    enableColumnResizing: true,
    columnResizeMode,
    onColumnSizingChange: setColumnSizing,
    onColumnSizingInfoChange: setColumnSizingInfo,
    onColumnOrderChange: setColumnOrder,
    manualSorting: true,
    onSortingChange: (updater) => {
      const newSorting = typeof updater === "function" ? updater(sorting) : updater;
      if (newSorting.length > 0 && onSortChange) {
        const { id, desc } = newSorting[0];
        const backendField = COLUMN_TO_BACKEND_SORT[id] || id;
        onSortChange(backendField, desc ? "desc" : "asc");
      } else if (newSorting.length === 0 && onSortChange) {
        // Reset to default sort when user clears sorting
        onSortChange("created_at", "desc");
      }
      setFocusedRowIndex(-1);
    },
    onRowSelectionChange: setRowSelection,
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
  });

  // Dev-assert: DEFAULT_COLUMN_ORDER phải khớp tập cột thật (const module-level cho
  // SSR-stable nên không derive được từ table). Thêm/xoá/đổi-tên cột mà quên list
  // này → columnOrder lệch + guard hydration reject → fail-loud khi dev.
  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    const actual = table.getAllLeafColumns().map((c) => c.id);
    const drift =
      actual.length !== DEFAULT_COLUMN_ORDER.length ||
      actual.some((id) => !DEFAULT_COLUMN_ORDER.includes(id));
    if (drift) {
      console.error(
        "[LeadsTable] DEFAULT_COLUMN_ORDER lệch với columns — cập nhật hằng.",
        { actual, expected: DEFAULT_COLUMN_ORDER },
      );
    }
    // Mọi cột ẩn/hiện được PHẢI có nhãn trong COLUMN_LABELS, nếu không menu
    // ẩn/hiện cột sẽ hiện id thô (vd "cached_urgency_score"). Fail-loud khi dev.
    const missingLabels = table
      .getAllLeafColumns()
      .filter((c) => c.getCanHide() && !COLUMN_LABELS[c.id])
      .map((c) => c.id);
    if (missingLabels.length) {
      console.error(
        "[LeadsTable] Cột ẩn/hiện được thiếu nhãn COLUMN_LABELS — bổ sung nhãn.",
        { missingLabels },
      );
    }
  }, [table]);

  // Get all rows for virtualization
  const rows = table.getRowModel().rows;

  // ID cột HIỆN (theo order + visibility) cho SortableContext — memo hóa để không
  // tạo mảng mới mỗi render (SortableContext re-derive item-map mỗi drag-move).
  // Derive trực tiếp từ columnOrder + columnVisibility (khớp header đang render).
  const sortableColumnIds = React.useMemo(
    () => columnOrder.filter((id) => columnVisibility[id] !== false),
    [columnOrder, columnVisibility],
  );

  // Danh sách cột cho menu ẩn/hiện — SINGLE SOURCE OF TRUTH từ chính bảng:
  // lấy cột lá lọc `getCanHide()` (loại select/actions enableHiding:false),
  // theo thứ tự định nghĩa (= DEFAULT_COLUMN_ORDER). Không hardcode lại ở
  // TableToolbar để khỏi lệch id/thiếu cột. `table` là ref ổn định của
  // react-table nên memo tính 1 lần (tập cột tĩnh theo runtime).
  const hideableColumns = React.useMemo(
    () =>
      table
        .getAllLeafColumns()
        .filter((col) => col.getCanHide())
        .map((col) => ({ id: col.id, label: COLUMN_LABELS[col.id] ?? col.id })),
    [table],
  );

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

  // ── Cột: kéo grip đổi thứ tự (giữ select đầu / actions cuối) ──
  const handleColumnDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setColumnOrder((prev) => {
      const base = prev.length ? prev : DEFAULT_COLUMN_ORDER;
      const oldIndex = base.indexOf(String(active.id));
      const newIndex = base.indexOf(String(over.id));
      if (oldIndex < 0 || newIndex < 0) return base;
      const moved = arrayMove(base, oldIndex, newIndex).filter(
        (id) => id !== PINNED_START && id !== PINNED_END,
      );
      return [PINNED_START, ...moved, PINNED_END];
    });
  }, []);

  // ── Double-click mép cột = auto-fit theo nội dung ──
  // Đo bề rộng TỰ NHIÊN: các ô đã `overflow-hidden`+`truncate` nên đo `scrollWidth`
  // của chính ô = bề-rộng-ĐÃ-CLIP (chỉ nhích ~6px). Thay bằng clone phần nội dung
  // vào probe đã GỠ overflow/truncate (white-space:nowrap, width:auto) → scrollWidth
  // là bề rộng nội dung thật. (Chỉ đo các hàng đang render — virtualized.)
  const autoFitColumn = useCallback(
    (columnId: string) => {
      const col = table.getColumn(columnId);
      if (!col?.getCanResize()) return;
      const root = tableScrollRef.current;
      if (!root) return;
      const probe = document.createElement("div");
      probe.style.cssText =
        "position:absolute;left:-9999px;top:-9999px;white-space:nowrap;pointer-events:none;";
      document.body.appendChild(probe);
      let maxContent = 0;
      try {
        // `:first-child` = phần nội dung của ô (div.truncate / span.flex / Badge…);
        // KHÔNG dính grip/resize-handle (là các con sau) → không cần loại theo label.
        root
          .querySelectorAll<HTMLElement>(`[data-column-id="${columnId}"] > :first-child`)
          .forEach((content) => {
            const clone = content.cloneNode(true) as HTMLElement;
            // Copy font THẬT (clone rời khỏi ngữ cảnh table → mất inherited text-sm/
            // font-medium → đo sai). Áp computed-font để đo đúng cỡ/đậm chữ.
            const cs = getComputedStyle(content);
            clone.style.fontSize = cs.fontSize;
            clone.style.fontWeight = cs.fontWeight;
            clone.style.fontFamily = cs.fontFamily;
            clone.style.letterSpacing = cs.letterSpacing;
            const strip = (el: HTMLElement) => {
              el.style.maxWidth = "none";
              el.style.width = "auto";
              el.style.overflow = "visible";
              el.style.textOverflow = "clip";
              el.style.whiteSpace = "nowrap";
            };
            strip(clone);
            clone.querySelectorAll<HTMLElement>("*").forEach(strip);
            probe.appendChild(clone);
            maxContent = Math.max(maxContent, clone.scrollWidth);
            probe.removeChild(clone);
          });
      } finally {
        document.body.removeChild(probe);
      }
      if (maxContent <= 0) return;
      const min = col.columnDef.minSize ?? 60;
      const max = col.columnDef.maxSize ?? 400;
      // + padding ô (px-2 = 16) + đệm nhỏ cho grip/handle
      const target = Math.max(min, Math.min(max, Math.round(maxContent) + 22));
      setColumnSizing((prev) => ({ ...prev, [columnId]: target }));
    },
    [table],
  );

  // ── Đặt lại bề rộng + thứ tự cột về mặc định ──
  // (setState kích persist-effect ghi lại '{}'/default ngay → không cần removeItem.)
  const resetColumnLayout = useCallback(() => {
    setColumnSizing({});
    setColumnOrder(DEFAULT_COLUMN_ORDER);
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
  // Layout-mode: prop từ LeadsClient (!isDesktop) ưu tiên; fallback useIsMobile().
  if (isMobileLayout ?? isMobile) {
    return (
      // Document-flow: KHÔNG h-full/scroll riêng — cuộn qua `Main` (single-scroll).
      <div className="flex flex-col">
        {/* Mobile Header */}
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-muted-foreground text-sm tabular-nums" aria-live="polite">
            {selectedLeads.length > 0 ? (
              <span className="text-primary font-medium">{selectedLeads.length} đã chọn</span>
            ) : (
              `${totalCount.toLocaleString("vi-VN")} lead`
            )}
          </span>
        </div>

        {/* Mobile List — flows trong trang (cuộn qua Main), không scroll container riêng */}
        <div className="min-w-0">
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
              onAssignLead={onAssignLead}
            />
          )}
        </div>

        {/* Mobile Pagination */}
        <div className="flex items-center justify-between border-t px-3 py-2">
          <span className="text-muted-foreground text-xs tabular-nums">
            {leads.length > 0 ? (page - 1) * pageSize + 1 : 0}-{Math.min(page * pageSize, totalCount)} / {totalCount}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange?.(page - 1)}
              disabled={page <= 1}
              className="h-11 w-11 md:h-8 md:w-8 p-0"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-muted-foreground min-w-[60px] text-center text-xs tabular-nums">
              {page}/{totalPages || 1}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange?.(page + 1)}
              disabled={page >= totalPages}
              className="h-11 w-11 md:h-8 md:w-8 p-0"
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
        <span className="text-muted-foreground text-sm tabular-nums">
          {selectedLeads.length > 0 ? (
            <span className="text-primary font-medium">{selectedLeads.length} đã chọn</span>
          ) : (
            `${leads.length} lead`
          )}
        </span>
        <TableToolbar
          densityMode={densityMode}
          onDensityChange={setDensityMode}
          columns={hideableColumns}
          columnVisibility={columnVisibility}
          onColumnVisibilityChange={(columnId, isVisible) => {
            setColumnVisibility((prev) => ({
              ...prev,
              [columnId]: isVisible,
            }));
          }}
          onResetColumns={resetColumnLayout}
        />
      </div>

      {/* Table with Virtualization */}
      <div 
        ref={tableScrollRef}
        className="flex-1 overflow-x-auto overflow-y-auto"
      >
        {/* DnD kéo grip tiêu đề đổi thứ tự cột. Chỉ header là sortable item;
            ô body tự theo columnOrder qua getVisibleCells → không cần bọc. */}
        <DndContext
          sensors={dndSensors}
          collisionDetection={closestCenter}
          onDragEnd={handleColumnDragEnd}
        >
        {/* ✅ Phase 3: ARIA improvements for accessibility.
            table-layout: fixed + width = getTotalSize() → bề rộng cột do người
            dùng kiểm soát (resize/auto-fit thật), nội dung dài CẮT GỌN thay vì
            nong cột; minWidth 100% để lấp đầy khi tổng < khung. */}
        <Table
          role="grid"
          aria-label="Danh sách lead"
          aria-rowcount={totalCount}
          style={{ width: table.getTotalSize(), minWidth: "100%", tableLayout: "fixed" }}
        >
          <TableHeader className="bg-muted/50 sticky top-0 z-10">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {/* items = cột HIỆN (memo hóa) — không gồm cột ẩn như phone → tránh
                    lệch animation shift + không tạo mảng mới mỗi render. */}
                <SortableContext items={sortableColumnIds} strategy={horizontalListSortingStrategy}>
                  {headerGroup.headers.map((header) => (
                    <DraggableHeader
                      key={header.id}
                      header={header}
                      headerHeightClass={densityConfig.headerHeight}
                      onAutoFit={autoFitColumn}
                    />
                  ))}
                </SortableContext>
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
                        "cursor-pointer transition duration-150",
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
                          data-column-id={cell.column.id}
                          style={{ width: cell.column.getSize() }}
                          className={cn(densityConfig.cellPadding, "overflow-hidden")}
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
        </DndContext>
      </div>

      {/* Footer with Pagination */}
      <div className="bg-muted/30 flex shrink-0 items-center justify-between border-t px-4 py-2">
        <div className="text-muted-foreground text-sm tabular-nums">
          Hiển thị {leads.length > 0 ? (page - 1) * pageSize + 1 : 0}-
          {Math.min(page * pageSize, totalCount)} / {totalCount.toLocaleString("vi-VN")} lead
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
          <span className="text-muted-foreground min-w-[100px] text-center text-sm tabular-nums">
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
