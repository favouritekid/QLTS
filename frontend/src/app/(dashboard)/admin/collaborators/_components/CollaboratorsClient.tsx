// src/app/(dashboard)/admin/collaborators/_components/CollaboratorsClient.tsx
"use client";

import { useState, useMemo, useCallback } from "react";
import {
  Plus,
  Search,
  MoreVertical,
  Edit,
  CheckCircle,
  Ban,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ClipboardList,
} from "lucide-react";
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
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { PageContainer } from "@/components/layouts/PageContainer";
import { TableEmptyState } from "@/components/common/EmptyState";

import {
  useCollaborators,
  useClaims,
  useApproveCollaborator,
  useSuspendCollaborator,
} from "@/hooks/useCollaborators";
import { useOrganizationUnits } from "@/hooks/useOrganization";
import { CollaboratorDialog } from "@/components/admin/CollaboratorDialog";
import { ClaimReviewDialog } from "@/components/admin/ClaimReviewDialog";
import type {
  Collaborator,
  CollaboratorsPage,
  LeadClaim,
} from "@/types/collaborator.types";

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
  inactive: { label: "Ngưng HĐ", variant: "outline" },
};

const CLAIM_STATUS_CONFIG: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending: { label: "Chờ duyệt", variant: "secondary" },
  approved: { label: "Đã duyệt", variant: "default" },
  rejected: { label: "Từ chối", variant: "destructive" },
};

// =============================================================================
// PROPS
// =============================================================================

interface CollaboratorsClientProps {
  initialData: CollaboratorsPage;
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export function CollaboratorsClient({ initialData }: CollaboratorsClientProps) {
  // ---------------------------------------------------------------------------
  // Tab state
  // ---------------------------------------------------------------------------
  const [activeTab, setActiveTab] = useState("collaborators");

  // ---------------------------------------------------------------------------
  // Collaborators tab state
  // ---------------------------------------------------------------------------
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [unitFilter, setUnitFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<string>("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  // ---------------------------------------------------------------------------
  // Claims tab state
  // ---------------------------------------------------------------------------
  const [claimPage, setClaimPage] = useState(1);
  const [claimStatusFilter, setClaimStatusFilter] = useState<string>("all");

  // ---------------------------------------------------------------------------
  // Dialog state
  // ---------------------------------------------------------------------------
  const [collaboratorDialogOpen, setCollaboratorDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [selectedCollaborator, setSelectedCollaborator] = useState<Collaborator | null>(null);
  const [claimReviewDialogOpen, setClaimReviewDialogOpen] = useState(false);
  const [selectedClaim, setSelectedClaim] = useState<LeadClaim | null>(null);

  // ---------------------------------------------------------------------------
  // Confirm action state
  // ---------------------------------------------------------------------------
  const [approveTarget, setApproveTarget] = useState<Collaborator | null>(null);
  const [suspendTarget, setSuspendTarget] = useState<Collaborator | null>(null);

  // ---------------------------------------------------------------------------
  // Data queries
  // ---------------------------------------------------------------------------
  const isFirstPageNoFilters =
    page === 1 &&
    !search &&
    statusFilter === "all" &&
    unitFilter === "all" &&
    sortBy === "created_at" &&
    sortOrder === "desc";

  const { data, isLoading, error } = useCollaborators({
    skip: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
    search: search || undefined,
    status: statusFilter === "all" ? undefined : statusFilter,
    unit_id: unitFilter === "all" ? undefined : Number(unitFilter),
    sort_by: sortBy,
    order: sortOrder,
  });

  const collaboratorsData = isFirstPageNoFilters && !data ? initialData : data;

  const { data: claimsData, isLoading: claimsLoading } = useClaims({
    skip: (claimPage - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
    status: claimStatusFilter === "all" ? undefined : claimStatusFilter,
  });

  const { data: units } = useOrganizationUnits();
  const approveMutation = useApproveCollaborator();
  const suspendMutation = useSuspendCollaborator();

  // ---------------------------------------------------------------------------
  // Sorting helpers
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
  // Actions
  // ---------------------------------------------------------------------------
  const handleCreate = () => {
    setSelectedCollaborator(null);
    setDialogMode("create");
    setCollaboratorDialogOpen(true);
  };

  const handleEdit = (collaborator: Collaborator) => {
    setSelectedCollaborator(collaborator);
    setDialogMode("edit");
    setCollaboratorDialogOpen(true);
  };

  const handleApprove = async () => {
    if (approveTarget) {
      await approveMutation.mutateAsync(approveTarget.id);
      setApproveTarget(null);
    }
  };

  const handleSuspend = async () => {
    if (suspendTarget) {
      await suspendMutation.mutateAsync(suspendTarget.id);
      setSuspendTarget(null);
    }
  };

  const handleReviewClaim = (claim: LeadClaim) => {
    setSelectedClaim(claim);
    setClaimReviewDialogOpen(true);
  };

  // ---------------------------------------------------------------------------
  // Collaborators table columns
  // ---------------------------------------------------------------------------
  const collaboratorColumns = useMemo<ColumnDef<Collaborator>[]>(
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
        accessorKey: "email",
        header: "Email",
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {row.original.email || "—"}
          </span>
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
        accessorKey: "unit",
        header: "Đơn vị",
        cell: ({ row }) => (
          <span className="text-sm">{row.original.unit?.name ?? "—"}</span>
        ),
      },
      {
        accessorKey: "managed_by_officer",
        header: "NV quản lý",
        cell: ({ row }) => (
          <span className="text-sm">
            {row.original.managed_by_officer?.full_name ?? row.original.managed_by_officer?.username ?? "—"}
          </span>
        ),
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
      {
        id: "actions",
        cell: ({ row }) => {
          const collaborator = row.original;
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Mở menu thao tác">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Thao tác</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => handleEdit(collaborator)}>
                  <Edit className="mr-2 h-4 w-4" aria-hidden="true" />
                  Sửa thông tin
                </DropdownMenuItem>
                {collaborator.status === "pending" && (
                  <DropdownMenuItem onClick={() => setApproveTarget(collaborator)}>
                    <CheckCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                    Duyệt CTV
                  </DropdownMenuItem>
                )}
                {collaborator.status === "active" && (
                  <DropdownMenuItem onClick={() => setSuspendTarget(collaborator)}>
                    <Ban className="mr-2 h-4 w-4" aria-hidden="true" />
                    Đình chỉ
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          );
        },
      },
    ],
    [getSortIcon, handleSort]
  );

  // ---------------------------------------------------------------------------
  // Claims table columns
  // ---------------------------------------------------------------------------
  const claimColumns = useMemo<ColumnDef<LeadClaim>[]>(
    () => [
      {
        accessorKey: "id",
        header: "ID",
        cell: ({ row }) => (
          <span className="font-mono text-sm">#{row.original.id}</span>
        ),
      },
      {
        accessorKey: "collaborator",
        header: "CTV",
        cell: ({ row }) => {
          const ctv = row.original.collaborator;
          if (!ctv) return <span className="text-muted-foreground">—</span>;
          return (
            <div>
              <p className="font-medium text-sm">{ctv.full_name}</p>
              <p className="text-muted-foreground text-xs">{ctv.code}</p>
            </div>
          );
        },
      },
      {
        accessorKey: "lead",
        header: "Lead",
        cell: ({ row }) => {
          const lead = row.original.lead;
          if (!lead) return <span className="text-muted-foreground">—</span>;
          return (
            <div>
              <p className="font-medium text-sm">{lead.full_name}</p>
              <p className="text-muted-foreground text-xs">{lead.phone_masked}</p>
            </div>
          );
        },
      },
      {
        accessorKey: "status",
        header: "Trạng thái",
        cell: ({ row }) => {
          const config = CLAIM_STATUS_CONFIG[row.original.status];
          return (
            <Badge variant={config?.variant ?? "outline"}>
              {config?.label ?? row.original.status}
            </Badge>
          );
        },
      },
      {
        accessorKey: "created_at",
        header: "Ngày tạo",
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {new Date(row.original.created_at).toLocaleDateString("vi-VN")}
          </span>
        ),
      },
      {
        id: "actions",
        cell: ({ row }) => {
          const claim = row.original;
          if (claim.status !== "pending") return null;
          return (
            <Button variant="outline" size="sm" onClick={() => handleReviewClaim(claim)}>
              <ClipboardList className="mr-2 h-4 w-4" aria-hidden="true" />
              Xem/Duyệt
            </Button>
          );
        },
      },
    ],
    []
  );

  // ---------------------------------------------------------------------------
  // TanStack Table instances
  // ---------------------------------------------------------------------------
  const collaboratorTable = useReactTable({
    data: collaboratorsData?.collaborators ?? [],
    columns: collaboratorColumns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: collaboratorsData ? Math.ceil(collaboratorsData.total_count / PAGE_SIZE) : 0,
    getRowId: (row) => String(row.id),
  });

  const claimTable = useReactTable({
    data: claimsData?.claims ?? [],
    columns: claimColumns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: claimsData ? Math.ceil(claimsData.total_count / PAGE_SIZE) : 0,
    getRowId: (row) => String(row.id),
  });

  // ---------------------------------------------------------------------------
  // Flatten units for dropdown (recursive)
  // ---------------------------------------------------------------------------
  const flatUnits = useMemo(() => {
    if (!units) return [];
    const result: { id: number; name: string }[] = [];
    const flatten = (items: typeof units, depth = 0) => {
      for (const u of items) {
        result.push({ id: u.id, name: `${"  ".repeat(depth)}${u.name}` });
        if (u.children && u.children.length > 0) {
          flatten(u.children, depth + 1);
        }
      }
    };
    flatten(units);
    return result;
  }, [units]);

  // ---------------------------------------------------------------------------
  // Total pages
  // ---------------------------------------------------------------------------
  const totalPages = collaboratorsData ? Math.ceil(collaboratorsData.total_count / PAGE_SIZE) : 0;
  const claimTotalPages = claimsData ? Math.ceil(claimsData.total_count / PAGE_SIZE) : 0;

  // ---------------------------------------------------------------------------
  // Error state
  // ---------------------------------------------------------------------------
  if (error) {
    return (
      <PageContainer maxWidth="xl">
        <header>
          <h1 className="text-2xl sm:text-3xl font-bold font-display tracking-tight">
            Quản Lý Cộng Tác Viên
          </h1>
          <p className="text-muted-foreground text-sm sm:text-base">
            Quản lý CTV và yêu cầu claim lead.
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
            Quản Lý Cộng Tác Viên
          </h1>
          <p className="text-muted-foreground text-sm sm:text-base">
            Quản lý CTV và yêu cầu claim lead.
          </p>
        </div>
        <Button size="sm" className="flex-1 sm:flex-none" onClick={handleCreate}>
          <Plus className="mr-2 h-4 w-4" />
          <span className="hidden xs:inline">Thêm CTV</span>
          <span className="xs:hidden">Thêm</span>
        </Button>
      </header>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="collaborators">Cộng tác viên</TabsTrigger>
          <TabsTrigger value="claims">Yêu cầu claim</TabsTrigger>
        </TabsList>

        {/* ================================================================= */}
        {/* TAB 1: Collaborators                                              */}
        {/* ================================================================= */}
        <TabsContent value="collaborators" className="space-y-4">
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
                    placeholder="Tìm theo tên, mã hoặc SĐT…"
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setPage(1);
                    }}
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
                    <SelectItem value="inactive">Ngưng HĐ</SelectItem>
                  </SelectContent>
                </Select>
                <Select
                  value={unitFilter}
                  onValueChange={(v) => {
                    setUnitFilter(v);
                    setPage(1);
                  }}
                >
                  <SelectTrigger className="w-full md:w-[200px]">
                    <SelectValue placeholder="Tất cả đơn vị" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả đơn vị</SelectItem>
                    {flatUnits.map((u) => (
                      <SelectItem key={u.id} value={String(u.id)}>
                        {u.name}
                      </SelectItem>
                    ))}
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
                  <Table className="min-w-[900px]">
                    <TableHeader>
                      {collaboratorTable.getHeaderGroups().map((headerGroup) => (
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
                      {collaboratorTable.getRowModel().rows?.length ? (
                        collaboratorTable.getRowModel().rows.map((row) => (
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
                          <TableCell colSpan={collaboratorColumns.length} className="h-32">
                            <TableEmptyState
                              title={search ? "Không tìm thấy CTV" : "Chưa có cộng tác viên nào"}
                              description={search ? "Thử tìm kiếm với từ khóa khác" : "Thêm CTV mới để bắt đầu"}
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
                <CollaboratorCard
                  key={collaborator.id}
                  collaborator={collaborator}
                  onEdit={() => handleEdit(collaborator)}
                  onApprove={() => setApproveTarget(collaborator)}
                  onSuspend={() => setSuspendTarget(collaborator)}
                />
              ))
            ) : (
              <Card>
                <CardContent className="py-8">
                  <TableEmptyState
                    title={search ? "Không tìm thấy CTV" : "Chưa có cộng tác viên nào"}
                    description={search ? "Thử tìm kiếm với từ khóa khác" : "Thêm CTV mới để bắt đầu"}
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
        </TabsContent>

        {/* ================================================================= */}
        {/* TAB 2: Claims                                                     */}
        {/* ================================================================= */}
        <TabsContent value="claims" className="space-y-4">
          {/* Filters */}
          <Card>
            <CardHeader>
              <CardTitle>Bộ lọc</CardTitle>
              <CardDescription>Lọc yêu cầu claim theo trạng thái</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-4 md:flex-row">
                <Select
                  value={claimStatusFilter}
                  onValueChange={(v) => {
                    setClaimStatusFilter(v);
                    setClaimPage(1);
                  }}
                >
                  <SelectTrigger className="w-full md:w-[200px]">
                    <SelectValue placeholder="Tất cả trạng thái" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tất cả trạng thái</SelectItem>
                    <SelectItem value="pending">Chờ duyệt</SelectItem>
                    <SelectItem value="approved">Đã duyệt</SelectItem>
                    <SelectItem value="rejected">Từ chối</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          {/* Desktop Table */}
          <Card className="hidden md:block">
            <CardContent className="p-0">
              {claimsLoading ? (
                <div className="space-y-2 p-6">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : (
                <div className="overflow-x-auto rounded-md border">
                  <Table className="min-w-[700px]">
                    <TableHeader>
                      {claimTable.getHeaderGroups().map((headerGroup) => (
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
                      {claimTable.getRowModel().rows?.length ? (
                        claimTable.getRowModel().rows.map((row) => (
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
                          <TableCell colSpan={claimColumns.length} className="h-32">
                            <TableEmptyState
                              title="Chưa có yêu cầu claim nào"
                              description="Các yêu cầu claim từ CTV sẽ hiển thị tại đây"
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
            {claimsLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <Card key={i}>
                  <CardContent className="p-4">
                    <div className="space-y-2">
                      <Skeleton className="h-4 w-32" />
                      <Skeleton className="h-3 w-24" />
                    </div>
                  </CardContent>
                </Card>
              ))
            ) : claimsData?.claims && claimsData.claims.length > 0 ? (
              claimsData.claims.map((claim) => (
                <ClaimCard
                  key={claim.id}
                  claim={claim}
                  onReview={() => handleReviewClaim(claim)}
                />
              ))
            ) : (
              <Card>
                <CardContent className="py-8">
                  <TableEmptyState
                    title="Chưa có yêu cầu claim nào"
                    description="Các yêu cầu claim từ CTV sẽ hiển thị tại đây"
                  />
                </CardContent>
              </Card>
            )}
          </div>

          {/* Pagination */}
          {claimsData && claimsData.total_count > PAGE_SIZE && (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-muted-foreground text-xs sm:text-sm text-center sm:text-left">
                Hiển thị {(claimPage - 1) * PAGE_SIZE + 1}-
                {Math.min(claimPage * PAGE_SIZE, claimsData.total_count)} /{" "}
                {claimsData.total_count}
              </div>
              <div className="flex gap-2 justify-center sm:justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setClaimPage((p) => Math.max(1, p - 1))}
                  disabled={claimPage === 1}
                >
                  Trước
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setClaimPage((p) => Math.min(claimTotalPages, p + 1))}
                  disabled={claimPage === claimTotalPages}
                >
                  Sau
                </Button>
              </div>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* ================================================================= */}
      {/* DIALOGS                                                           */}
      {/* ================================================================= */}

      {/* Collaborator Create/Edit Dialog */}
      <CollaboratorDialog
        open={collaboratorDialogOpen}
        onOpenChange={setCollaboratorDialogOpen}
        collaborator={selectedCollaborator}
        mode={dialogMode}
      />

      {/* Claim Review Dialog */}
      {selectedClaim && (
        <ClaimReviewDialog
          open={claimReviewDialogOpen}
          onOpenChange={setClaimReviewDialogOpen}
          claim={selectedClaim}
        />
      )}

      {/* Approve Confirmation */}
      <AlertDialog open={!!approveTarget} onOpenChange={() => setApproveTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Duyệt cộng tác viên?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn duyệt CTV{" "}
              <strong>{approveTarget?.full_name}</strong> ({approveTarget?.code})? CTV sẽ được
              kích hoạt và có thể bắt đầu hoạt động.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleApprove}
              disabled={approveMutation.isPending}
            >
              {approveMutation.isPending ? "Đang duyệt…" : "Duyệt"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Suspend Confirmation */}
      <AlertDialog open={!!suspendTarget} onOpenChange={() => setSuspendTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Đình chỉ cộng tác viên?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn đình chỉ CTV{" "}
              <strong>{suspendTarget?.full_name}</strong> ({suspendTarget?.code})? CTV sẽ không
              thể hoạt động cho đến khi được kích hoạt lại.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleSuspend}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={suspendMutation.isPending}
            >
              {suspendMutation.isPending ? "Đang xử lý…" : "Đình chỉ"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}

// =============================================================================
// MOBILE CARD: Collaborator
// =============================================================================

interface CollaboratorCardProps {
  collaborator: Collaborator;
  onEdit: () => void;
  onApprove: () => void;
  onSuspend: () => void;
}

function CollaboratorCard({ collaborator, onEdit, onApprove, onSuspend }: CollaboratorCardProps) {
  const statusConfig = STATUS_CONFIG[collaborator.status];

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <p className="font-medium truncate">{collaborator.full_name}</p>
              <Badge variant={statusConfig?.variant ?? "outline"} className="shrink-0">
                {statusConfig?.label ?? collaborator.status}
              </Badge>
            </div>
            <p className="text-muted-foreground text-sm font-mono">{collaborator.code}</p>
            <p className="text-muted-foreground text-sm">{collaborator.phone}</p>
            {collaborator.email && (
              <p className="text-muted-foreground text-sm truncate">{collaborator.email}</p>
            )}
            {collaborator.unit && (
              <p className="text-muted-foreground text-xs">{collaborator.unit.name}</p>
            )}
            <p className="text-muted-foreground text-xs">
              {new Date(collaborator.created_at).toLocaleDateString("vi-VN")}
            </p>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-10 w-10 shrink-0" aria-label="Mở menu thao tác">
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Thao tác</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onEdit}>
                <Edit className="mr-2 h-4 w-4" aria-hidden="true" />
                Sửa thông tin
              </DropdownMenuItem>
              {collaborator.status === "pending" && (
                <DropdownMenuItem onClick={onApprove}>
                  <CheckCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                  Duyệt CTV
                </DropdownMenuItem>
              )}
              {collaborator.status === "active" && (
                <DropdownMenuItem onClick={onSuspend}>
                  <Ban className="mr-2 h-4 w-4" aria-hidden="true" />
                  Đình chỉ
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardContent>
    </Card>
  );
}

// =============================================================================
// MOBILE CARD: Claim
// =============================================================================

interface ClaimCardProps {
  claim: LeadClaim;
  onReview: () => void;
}

function ClaimCard({ claim, onReview }: ClaimCardProps) {
  const statusConfig = CLAIM_STATUS_CONFIG[claim.status];

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-muted-foreground">#{claim.id}</span>
              <Badge variant={statusConfig?.variant ?? "outline"} className="shrink-0">
                {statusConfig?.label ?? claim.status}
              </Badge>
            </div>
            {claim.collaborator && (
              <p className="text-sm">
                <span className="font-medium">{claim.collaborator.full_name}</span>{" "}
                <span className="text-muted-foreground">({claim.collaborator.code})</span>
              </p>
            )}
            {claim.lead && (
              <p className="text-sm text-muted-foreground">
                Lead: {claim.lead.full_name} - {claim.lead.phone_masked}
              </p>
            )}
            <p className="text-muted-foreground text-xs">
              {new Date(claim.created_at).toLocaleDateString("vi-VN")}
            </p>
          </div>

          {claim.status === "pending" && (
            <Button variant="outline" size="sm" className="shrink-0" onClick={onReview}>
              <ClipboardList className="mr-2 h-4 w-4" aria-hidden="true" />
              Duyệt
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
