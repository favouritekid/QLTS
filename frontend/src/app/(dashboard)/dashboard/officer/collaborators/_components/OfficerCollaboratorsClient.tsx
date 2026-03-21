// src/app/(dashboard)/dashboard/officer/collaborators/_components/OfficerCollaboratorsClient.tsx
"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { Plus, Search, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import {
  useReactTable,
  getCoreRowModel,
  ColumnDef,
  flexRender,
} from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageContainer } from "@/components/layouts/PageContainer";
import { TableEmptyState } from "@/components/common/EmptyState";

import { useCollaborators } from "@/hooks/useCollaborators";
import { CollaboratorDialog } from "@/components/admin/CollaboratorDialog";
import type { Collaborator, CollaboratorsPage } from "@/types/collaborator.types";

// =============================================================================
// CONSTANTS
// =============================================================================

const PAGE_SIZE = 10;

const STATUS_CONFIG: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending: { label: "Chờ duyệt", variant: "secondary" },
  active: { label: "Hoạt động", variant: "default" },
  suspended: { label: "Đình chỉ", variant: "destructive" },
};

// =============================================================================
// PROPS
// =============================================================================

interface OfficerCollaboratorsClientProps {
  initialData: CollaboratorsPage;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function OfficerCollaboratorsClient({ initialData }: OfficerCollaboratorsClientProps) {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<string>("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);

  // ---------------------------------------------------------------------------
  // Debounce search (300ms)
  // ---------------------------------------------------------------------------
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    };
  }, [searchInput]);

  // ---------------------------------------------------------------------------
  // Data query + SSR initialData fallback
  // ---------------------------------------------------------------------------
  const isFirstPageNoFilters =
    page === 1 &&
    !search &&
    statusFilter === "all" &&
    sortBy === "created_at" &&
    sortOrder === "desc";

  const { data, isLoading, error } = useCollaborators({
    skip: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
    search: search || undefined,
    status: statusFilter === "all" ? undefined : statusFilter,
    sort_by: sortBy,
    order: sortOrder,
  });

  const collaboratorsData = isFirstPageNoFilters && !data ? initialData : data;

  // ---------------------------------------------------------------------------
  // Sorting
  // ---------------------------------------------------------------------------
  const handleSort = useCallback(
    (column: string) => {
      if (sortBy === column) {
        setSortOrder(sortOrder === "asc" ? "desc" : "asc");
      } else {
        setSortBy(column);
        setSortOrder("asc");
      }
      setPage(1);
    },
    [sortBy, sortOrder]
  );

  const getSortIcon = useCallback(
    (column: string) => {
      if (sortBy !== column) {
        return <ArrowUpDown className="ml-2 h-4 w-4" />;
      }
      return sortOrder === "asc" ? (
        <ArrowUp className="ml-2 h-4 w-4" />
      ) : (
        <ArrowDown className="ml-2 h-4 w-4" />
      );
    },
    [sortBy, sortOrder]
  );

  // ---------------------------------------------------------------------------
  // Table columns (5 columns — no actions, no unit, no managed_by)
  // ---------------------------------------------------------------------------
  const columns = useMemo<ColumnDef<Collaborator>[]>(
    () => [
      {
        accessorKey: "code",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("code")} className="-ml-4 h-8">
            Mã CTV
            {getSortIcon("code")}
          </Button>
        ),
        cell: ({ row }) => (
          <span className="font-mono text-sm">{row.original.code}</span>
        ),
      },
      {
        accessorKey: "full_name",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("full_name")} className="-ml-4 h-8">
            Họ tên
            {getSortIcon("full_name")}
          </Button>
        ),
        cell: ({ row }) => (
          <span className="font-medium">{row.original.full_name}</span>
        ),
      },
      {
        accessorKey: "phone",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("phone")} className="-ml-4 h-8">
            SĐT
            {getSortIcon("phone")}
          </Button>
        ),
      },
      {
        accessorKey: "status",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("status")} className="-ml-4 h-8">
            Trạng thái
            {getSortIcon("status")}
          </Button>
        ),
        cell: ({ row }) => {
          const config = STATUS_CONFIG[row.original.status];
          return (
            <Badge variant={config?.variant ?? "outline"}>
              {config?.label ?? row.original.status}
            </Badge>
          );
        },
      },
      {
        accessorKey: "created_at",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("created_at")} className="-ml-4 h-8">
            Ngày tạo
            {getSortIcon("created_at")}
          </Button>
        ),
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {new Date(row.original.created_at).toLocaleDateString("vi-VN")}
          </span>
        ),
      },
    ],
    [getSortIcon, handleSort]
  );

  // ---------------------------------------------------------------------------
  // TanStack Table
  // ---------------------------------------------------------------------------
  const table = useReactTable({
    data: collaboratorsData?.collaborators ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: collaboratorsData ? Math.ceil(collaboratorsData.total_count / PAGE_SIZE) : 0,
    getRowId: (row) => String(row.id),
  });

  const totalPages = collaboratorsData ? Math.ceil(collaboratorsData.total_count / PAGE_SIZE) : 0;

  // ---------------------------------------------------------------------------
  // Error state
  // ---------------------------------------------------------------------------
  if (error) {
    return (
      <PageContainer maxWidth="xl">
        <header>
          <h1 className="text-2xl sm:text-3xl font-bold font-display tracking-tight">
            CTV của tôi
          </h1>
          <p className="text-muted-foreground text-sm sm:text-base">
            Quản lý cộng tác viên do bạn phụ trách.
          </p>
        </header>
        <Card>
          <CardContent className="pt-6">
            <p className="text-destructive">Lỗi tải dữ liệu: {error.message}</p>
          </CardContent>
        </Card>
      </PageContainer>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <PageContainer maxWidth="xl">
      {/* Header */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold font-display tracking-tight">
            CTV của tôi
          </h1>
          <p className="text-muted-foreground text-sm sm:text-base">
            Quản lý cộng tác viên do bạn phụ trách.
          </p>
        </div>
        <Button size="sm" className="flex-1 sm:flex-none" onClick={() => setDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          <span className="hidden xs:inline">Đề xuất CTV mới</span>
          <span className="xs:hidden">Đề xuất</span>
        </Button>
      </header>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Bộ lọc</CardTitle>
          <CardDescription>Tìm kiếm và lọc cộng tác viên</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 md:flex-row">
            <div className="relative flex-1">
              <Search className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
              <Input
                placeholder="Tìm theo tên, mã hoặc SĐT..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select
              value={statusFilter}
              onValueChange={(v) => {
                setStatusFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-full md:w-[180px]">
                <SelectValue placeholder="Tất cả trạng thái" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả trạng thái</SelectItem>
                <SelectItem value="pending">Chờ duyệt</SelectItem>
                <SelectItem value="active">Hoạt động</SelectItem>
                <SelectItem value="suspended">Đình chỉ</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Desktop Table */}
      <Card className="hidden md:block">
        <CardContent className="p-0">
          {isLoading && !collaboratorsData ? (
            <div className="space-y-2 p-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table className="min-w-[700px]">
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
                <TableBody>
                  {table.getRowModel().rows?.length ? (
                    table.getRowModel().rows.map((row) => (
                      <TableRow key={row.id}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={columns.length} className="h-32">
                        <TableEmptyState
                          title={search ? "Không tìm thấy CTV" : "Chưa có cộng tác viên nào"}
                          description={search ? "Thử tìm kiếm với từ khóa khác" : "Đề xuất CTV mới để bắt đầu"}
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Mobile Cards */}
      <div className="md:hidden space-y-3">
        {isLoading && !collaboratorsData ? (
          Array.from({ length: 5 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-4">
                <div className="space-y-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-3 w-20" />
                </div>
              </CardContent>
            </Card>
          ))
        ) : collaboratorsData?.collaborators && collaboratorsData.collaborators.length > 0 ? (
          collaboratorsData.collaborators.map((collaborator) => (
            <CollaboratorCard key={collaborator.id} collaborator={collaborator} />
          ))
        ) : (
          <Card>
            <CardContent className="py-8">
              <TableEmptyState
                title={search ? "Không tìm thấy CTV" : "Chưa có cộng tác viên nào"}
                description={search ? "Thử tìm kiếm với từ khóa khác" : "Đề xuất CTV mới để bắt đầu"}
              />
            </CardContent>
          </Card>
        )}
      </div>

      {/* Pagination */}
      {collaboratorsData && collaboratorsData.total_count > PAGE_SIZE && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-muted-foreground text-xs sm:text-sm text-center sm:text-left">
            Hiển thị {(page - 1) * PAGE_SIZE + 1}-
            {Math.min(page * PAGE_SIZE, collaboratorsData.total_count)} /{" "}
            {collaboratorsData.total_count}
          </div>
          <div className="flex gap-2 justify-center sm:justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              Trước
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
            >
              Sau
            </Button>
          </div>
        </div>
      )}

      {/* Create Dialog (officer mode) */}
      <CollaboratorDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        collaborator={null}
        mode="create"
        isOfficerMode
      />
    </PageContainer>
  );
}

// =============================================================================
// MOBILE CARD (read-only — no actions for officer)
// =============================================================================

function CollaboratorCard({ collaborator }: { collaborator: Collaborator }) {
  const statusConfig = STATUS_CONFIG[collaborator.status];

  return (
    <Card>
      <CardContent className="p-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <p className="font-medium truncate">{collaborator.full_name}</p>
            <Badge variant={statusConfig?.variant ?? "outline"} className="shrink-0">
              {statusConfig?.label ?? collaborator.status}
            </Badge>
          </div>
          <p className="text-muted-foreground text-sm font-mono">{collaborator.code}</p>
          <p className="text-muted-foreground text-sm">{collaborator.phone}</p>
          <p className="text-muted-foreground text-xs">
            {new Date(collaborator.created_at).toLocaleDateString("vi-VN")}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
