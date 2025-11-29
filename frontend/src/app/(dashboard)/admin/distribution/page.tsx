"use client";

import { useState, useMemo, useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  ColumnDef,
  flexRender,
} from "@tanstack/react-table";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import {
  Plus,
  Search,
  Trash2,
  MoreVertical,
  Pencil,
  Share2,
  CheckSquare,
  Square,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { toast } from "sonner";

import { DistributionRuleDialog } from "@/components/admin/distribution/DistributionRuleDialog";

// Type definitions
interface DistributionRule {
  id: number;
  offering_id: number;
  unit_id: number;
  weight: number;
  priority: number;
  is_active: boolean;
  offering_name?: string;
  unit_name?: string;
}

export default function DistributionRulesPage() {
  const queryClient = useQueryClient();

  // State management
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<string>("priority");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [rowSelection, setRowSelection] = useState({});
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<DistributionRule | null>(null);
  const [ruleToDelete, setRuleToDelete] = useState<DistributionRule | null>(null);
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false);

  // Fetch rules list
  const { data: rules = [], isLoading, error } = useQuery({
    queryKey: ["admin", "distribution-rules"],
    queryFn: async () => {
      const res = await api.get<DistributionRule[]>("/api/admin/distribution-rules");
      return res.data;
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      return api.delete(`/api/admin/distribution-rules/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "distribution-rules"] });
      toast.success("Đã xóa luật phân phối thành công");
      setRuleToDelete(null);
    },
    onError: () => {
      toast.error("Không thể xóa luật phân phối");
    },
  });

  // Bulk delete mutation
  const bulkDeleteMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      // Delete one by one (or implement a bulk endpoint)
      await Promise.all(ids.map(id => api.delete(`/api/admin/distribution-rules/${id}`)));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "distribution-rules"] });
      toast.success("Đã xóa các luật phân phối đã chọn");
      setRowSelection({});
      setBulkDeleteDialogOpen(false);
    },
    onError: () => {
      toast.error("Không thể xóa các luật phân phối");
    },
  });

  // Toggle active mutation
  const toggleMutation = useMutation({
    mutationFn: async ({ id, isActive }: { id: number; isActive: boolean }) => {
      return api.put(`/api/admin/distribution-rules/${id}`, { is_active: isActive });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "distribution-rules"] });
      toast.success("Đã cập nhật trạng thái thành công");
    },
    onError: () => toast.error("Không thể cập nhật trạng thái"),
  });

  // Filter data based on search and status
  const filteredRules = useMemo(() => {
    let filtered = rules;

    // Filter by search
    if (search) {
      const searchLower = search.toLowerCase();
      filtered = filtered.filter(
        (rule) =>
          rule.offering_name?.toLowerCase().includes(searchLower) ||
          rule.unit_name?.toLowerCase().includes(searchLower)
      );
    }

    // Filter by status
    if (statusFilter !== "all") {
      const isActive = statusFilter === "active";
      filtered = filtered.filter((rule) => rule.is_active === isActive);
    }

    // Sort
    filtered = [...filtered].sort((a, b) => {
      let aVal: number | string = 0;
      let bVal: number | string = 0;

      switch (sortBy) {
        case "priority":
          aVal = a.priority;
          bVal = b.priority;
          break;
        case "weight":
          aVal = a.weight;
          bVal = b.weight;
          break;
        case "offering":
          aVal = a.offering_name || "";
          bVal = b.offering_name || "";
          break;
        case "unit":
          aVal = a.unit_name || "";
          bVal = b.unit_name || "";
          break;
        default:
          aVal = a.id;
          bVal = b.id;
      }

      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortOrder === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }

      return sortOrder === "asc"
        ? (aVal as number) - (bVal as number)
        : (bVal as number) - (aVal as number);
    });

    return filtered;
  }, [rules, search, statusFilter, sortBy, sortOrder]);

  // Handle column sorting
  const handleSort = useCallback((column: string) => {
    if (sortBy === column) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortBy(column);
      setSortOrder("asc");
    }
  }, [sortBy, sortOrder]);

  // Render sort icon
  const getSortIcon = useCallback((column: string) => {
    if (sortBy !== column) {
      return <ArrowUpDown className="ml-2 h-4 w-4" />;
    }
    return sortOrder === "asc" ? (
      <ArrowUp className="ml-2 h-4 w-4" />
    ) : (
      <ArrowDown className="ml-2 h-4 w-4" />
    );
  }, [sortBy, sortOrder]);

  // Table columns
  const columns = useMemo<ColumnDef<DistributionRule>[]>(
    () => [
      {
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={table.getIsAllPageRowsSelected()}
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
            aria-label="Chọn tất cả"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            aria-label="Chọn dòng"
          />
        ),
        enableSorting: false,
        enableHiding: false,
      },
      {
        accessorKey: "offering_name",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("offering")} className="-ml-4 h-8">
            Chương trình đào tạo
            {getSortIcon("offering")}
          </Button>
        ),
        cell: ({ row }) => (
          <div className="font-medium">
            {row.original.offering_name || `ID: ${row.original.offering_id}`}
          </div>
        ),
      },
      {
        accessorKey: "unit_name",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("unit")} className="-ml-4 h-8">
            Đơn vị tiếp nhận
            {getSortIcon("unit")}
          </Button>
        ),
        cell: ({ row }) => (
          <div>{row.original.unit_name || `ID: ${row.original.unit_id}`}</div>
        ),
      },
      {
        accessorKey: "weight",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("weight")} className="-ml-4 h-8">
            Trọng số
            {getSortIcon("weight")}
          </Button>
        ),
        cell: ({ row }) => (
          <Badge variant="secondary" className="px-3 py-1 text-sm">
            {row.original.weight}
          </Badge>
        ),
      },
      {
        accessorKey: "priority",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("priority")} className="-ml-4 h-8">
            Ưu tiên
            {getSortIcon("priority")}
          </Button>
        ),
        cell: ({ row }) => (
          <span className="font-mono text-sm">{row.original.priority}</span>
        ),
      },
      {
        accessorKey: "is_active",
        header: "Trạng thái",
        cell: ({ row }) => {
          const isActive = row.original.is_active;
          return (
            <Badge variant={isActive ? "default" : "secondary"}>
              {isActive ? "Hoạt động" : "Tạm dừng"}
            </Badge>
          );
        },
      },
      {
        id: "actions",
        cell: ({ row }) => {
          const rule = row.original;
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Hành động</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => {
                  setEditingRule(rule);
                  setIsDialogOpen(true);
                }}>
                  <Pencil className="mr-2 h-4 w-4" />
                  Chỉnh sửa
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => toggleMutation.mutate({
                    id: rule.id,
                    isActive: !rule.is_active
                  })}
                >
                  {rule.is_active ? "Tạm dừng" : "Kích hoạt"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() => setRuleToDelete(rule)}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Xóa
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          );
        },
      },
    ],
    [getSortIcon, handleSort, toggleMutation]
  );

  // Setup table
  const table = useReactTable({
    data: filteredRules,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    onRowSelectionChange: setRowSelection,
    state: {
      rowSelection,
    },
  });

  const handleCreateRule = () => {
    setEditingRule(null);
    setIsDialogOpen(true);
  };

  const handleDeleteRule = async () => {
    if (ruleToDelete) {
      await deleteMutation.mutateAsync(ruleToDelete.id);
    }
  };

  const handleBulkDelete = async () => {
    const selectedRows = table.getFilteredSelectedRowModel().rows;
    const ids = selectedRows.map((row) => row.original.id);
    if (ids.length > 0) {
      await bulkDeleteMutation.mutateAsync(ids);
    }
  };

  const selectedCount = table.getFilteredSelectedRowModel().rows.length;

  if (error) {
    return (
      <PageContainer>
        <PageHeader
          title="Phân Phối Tuyển Sinh"
          description="Cấu hình tỷ lệ chia Lead giữa các đơn vị."
          icon={<Share2 className="h-8 w-8" />}
        />
        <Card>
          <CardContent className="pt-6">
            <p className="text-destructive">Lỗi tải dữ liệu: {error.message}</p>
          </CardContent>
        </Card>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      {/* Header */}
      <PageHeader
        title="Phân Phối Tuyển Sinh"
        description="Cấu hình tỷ lệ chia Lead (Weighted Round Robin) giữa các đơn vị."
        icon={<Share2 className="h-8 w-8" />}
        actions={
          <Button onClick={handleCreateRule}>
            <Plus className="mr-2 h-4 w-4" />
            Thêm Luật Mới
          </Button>
        }
      />

      {/* Bulk Actions Bar */}
      {selectedCount > 0 && (
        <Card className="border-primary">
          <CardContent className="flex items-center justify-between p-4">
            <div className="flex items-center gap-2">
              <CheckSquare className="text-primary h-5 w-5" />
              <span className="font-medium">{selectedCount} luật đã chọn</span>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => table.resetRowSelection()}>
                <Square className="mr-2 h-4 w-4" />
                Bỏ chọn
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setBulkDeleteDialogOpen(true)}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Xóa đã chọn
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Bộ lọc</CardTitle>
          <CardDescription>Tìm kiếm và lọc luật phân phối</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 md:flex-row">
            <div className="relative flex-1">
              <Search className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
              <Input
                placeholder="Tìm theo chương trình hoặc đơn vị..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-full md:w-[180px]">
                <SelectValue placeholder="Tất cả trạng thái" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả trạng thái</SelectItem>
                <SelectItem value="active">Hoạt động</SelectItem>
                <SelectItem value="inactive">Tạm dừng</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Distribution Rules Table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-6">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
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
                      <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={columns.length} className="h-24 text-center">
                        Chưa có luật phân phối nào được cấu hình.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {filteredRules.length > 10 && (
        <div className="flex items-center justify-between">
          <div className="text-muted-foreground text-sm">
            Hiển thị {table.getState().pagination.pageIndex * 10 + 1} đến{" "}
            {Math.min((table.getState().pagination.pageIndex + 1) * 10, filteredRules.length)} của{" "}
            {filteredRules.length} luật
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              Trước
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              Sau
            </Button>
          </div>
        </div>
      )}

      {/* Create/Edit Dialog */}
      <DistributionRuleDialog
        open={isDialogOpen}
        onOpenChange={setIsDialogOpen}
        rule={editingRule}
      />

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!ruleToDelete} onOpenChange={() => setRuleToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa luật phân phối cho{" "}
              <strong>{ruleToDelete?.offering_name}</strong>?
              Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteRule}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? "Đang xóa..." : "Xóa"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Delete Confirmation Dialog */}
      <AlertDialog open={bulkDeleteDialogOpen} onOpenChange={setBulkDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa nhiều luật?</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc chắn muốn xóa <strong>{selectedCount} luật phân phối</strong>?
              Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleBulkDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              disabled={bulkDeleteMutation.isPending}
            >
              {bulkDeleteMutation.isPending ? "Đang xóa..." : "Xóa tất cả"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}
