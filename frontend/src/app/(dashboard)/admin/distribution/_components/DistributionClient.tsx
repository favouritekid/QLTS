// src/app/(dashboard)/admin/distribution/_components/DistributionClient.tsx
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
import {
  useDistributionRules,
  useDeleteDistributionRule,
  useBulkDeleteDistributionRules,
  useToggleDistributionRule,
  type DistributionRule,
} from "@/hooks/useDistributionRules";
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
import { TableEmptyState } from "@/components/common/EmptyState";

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
  BaseCard,
  CardHeader as BaseCardHeader,
  CardBody,
  CardField,
  CardFieldRow,
  CardMeta,
  CardActions,
} from "@/components/ui/base-card";
import { type RowSelectionState } from "@tanstack/react-table";
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

import { DistributionRuleDialog } from "@/components/admin/distribution/DistributionRuleDialog";
import { MobileActionSheet } from "@/components/common/MobileActionSheet";

// =============================================================================
// MOBILE RULE CARD COMPONENT
// =============================================================================

interface MobileRuleCardProps {
  rule: DistributionRule;
  isSelected: boolean;
  onSelect: (checked: boolean) => void;
  onEdit: (rule: DistributionRule) => void;
  onDelete: (rule: DistributionRule) => void;
  onToggle: (rule: DistributionRule) => void;
}

function MobileRuleCard({ rule, isSelected, onSelect, onEdit, onDelete, onToggle }: MobileRuleCardProps) {
  const [actionSheetOpen, setActionSheetOpen] = useState(false);

  return (
    <BaseCard
      selected={isSelected}
      onSelect={onSelect}
      showCheckbox
    >
      <BaseCardHeader
        title={rule.offering_name || `Offering ID: ${rule.offering_id}`}
        subtitle={rule.unit_name || `Unit ID: ${rule.unit_id}`}
        badge={
          <Badge variant={rule.is_active ? "default" : "secondary"}>
            {rule.is_active ? "Hoạt động" : "Tạm dừng"}
          </Badge>
        }
      />
      <CardBody>
        <CardFieldRow>
          <CardField label="Trọng số" value={rule.weight} />
          <CardField label="Ưu tiên" value={rule.priority} />
        </CardFieldRow>
      </CardBody>
      <CardActions>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setActionSheetOpen(true)}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
      </CardActions>

      {/* Mobile Action Sheet */}
      <MobileActionSheet
        open={actionSheetOpen}
        onOpenChange={setActionSheetOpen}
        title={rule.offering_name || `Rule #${rule.id}`}
      >
        <MobileActionSheet.Item
          icon={Pencil}
          onClick={() => {
            setActionSheetOpen(false);
            onEdit(rule);
          }}
        >
          Chỉnh sửa
        </MobileActionSheet.Item>
        <MobileActionSheet.Item
          onClick={() => {
            setActionSheetOpen(false);
            onToggle(rule);
          }}
        >
          {rule.is_active ? "Tạm dừng" : "Kích hoạt"}
        </MobileActionSheet.Item>
        <MobileActionSheet.Item
          icon={Trash2}
          variant="destructive"
          onClick={() => {
            setActionSheetOpen(false);
            onDelete(rule);
          }}
        >
          Xóa
        </MobileActionSheet.Item>
      </MobileActionSheet>
    </BaseCard>
  );
}

// =============================================================================
// CLIENT COMPONENT
// =============================================================================

interface DistributionClientProps {
  initialData?: DistributionRule[];
}

export function DistributionClient({ initialData }: DistributionClientProps) {
  // State management
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<string>("priority");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<DistributionRule | null>(null);
  const [ruleToDelete, setRuleToDelete] = useState<DistributionRule | null>(null);
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false);

  // ⚡ Fetch rules list with initialData support
  const { data: rules = [], isLoading, error } = useDistributionRules({ initialData });
  const deleteMutation = useDeleteDistributionRule();
  const bulkDeleteMutation = useBulkDeleteDistributionRules();
  const toggleMutation = useToggleDistributionRule();

  // Filter and sort rules
  const filteredRules = useMemo(() => {
    let filtered = rules;

    // Filter by search
    if (search) {
      filtered = filtered.filter((rule) =>
        rule.offering_name?.toLowerCase().includes(search.toLowerCase()) ||
        rule.unit_name?.toLowerCase().includes(search.toLowerCase())
      );
    }

    // Filter by status
    if (statusFilter !== "all") {
      filtered = filtered.filter((rule) =>
        statusFilter === "active" ? rule.is_active : !rule.is_active
      );
    }

    // Sort
    filtered = filtered.sort((a, b) => {
      let aVal: string | number;
      let bVal: string | number;

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
                <Button variant="ghost" size="icon" aria-label="Mở menu hành động">
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
    getRowId: (row) => String(row.id),
  });

  const handleCreateRule = () => {
    setEditingRule(null);
    setIsDialogOpen(true);
  };

  const handleDeleteRule = async () => {
    if (ruleToDelete) {
      await deleteMutation.mutateAsync(ruleToDelete.id);
      setRuleToDelete(null);
    }
  };

  const handleBulkDelete = async () => {
    const selectedRows = table.getFilteredSelectedRowModel().rows;
    const ids = selectedRows.map((row) => row.original.id);
    if (ids.length > 0) {
      await bulkDeleteMutation.mutateAsync(ids);
      setRowSelection({});
      setBulkDeleteDialogOpen(false);
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
          ) : filteredRules.length === 0 ? (
            <div className="p-6">
              <TableEmptyState
                title="Chưa có luật phân phối"
                description="Tạo luật phân phối mới để tự động gán lead cho cán bộ"
              />
            </div>
          ) : (
            <>
              {/* Desktop: Table */}
              <div className="hidden md:block rounded-md border">
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
                    {table.getRowModel().rows.map((row) => (
                      <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Mobile: Cards */}
              <div className="md:hidden p-4 space-y-2">
                {/* Select All header */}
                <div className="flex items-center gap-2 px-1 py-2">
                  <Checkbox
                    checked={table.getIsAllPageRowsSelected()}
                    onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
                    aria-label="Chọn tất cả"
                  />
                  <span className="text-sm text-muted-foreground">Chọn tất cả</span>
                </div>

                {/* Rule Cards */}
                {filteredRules.map((rule) => (
                  <MobileRuleCard
                    key={rule.id}
                    rule={rule}
                    isSelected={rowSelection[String(rule.id)] ?? false}
                    onSelect={(checked) => {
                      setRowSelection((prev) => ({
                        ...prev,
                        [String(rule.id)]: checked,
                      }));
                    }}
                    onEdit={(rule) => {
                      setEditingRule(rule);
                      setIsDialogOpen(true);
                    }}
                    onDelete={setRuleToDelete}
                    onToggle={(rule) => toggleMutation.mutate({
                      id: rule.id,
                      isActive: !rule.is_active
                    })}
                  />
                ))}
              </div>
            </>
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
