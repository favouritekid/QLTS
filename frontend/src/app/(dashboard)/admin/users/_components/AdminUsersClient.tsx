// src/app/(dashboard)/admin/users/_components/AdminUsersClient.tsx
"use client";

/**
 * ✅ PHASE 1 - WEEK 2 - DAY 1: Admin Users Client Component
 *
 * Complex page with:
 * - TanStack Table with sorting, filtering, pagination
 * - Bulk actions (delete, change status)
 * - Multiple dialogs (create, edit, set password, manage roles)
 * - CSV export
 *
 * Server Component (parent) fetches initial data, this handles all interactivity.
 */

import { useState, useMemo, useCallback, useEffect } from "react";
import Link from "next/link";
import {
  Plus,
  Download,
  Trash2,
  MoreVertical,
  Edit,
  Key,
  Shield,
  CheckSquare,
  Square,
  Eye,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  ColumnDef,
  flexRender,
  type RowSelectionState,
} from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { SearchInput } from "@/components/common/form/SearchInput";
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
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BaseCard,
  CardHeader as BaseCardHeader,
  CardBody,
  CardField,
  CardMeta,
  CardActions,
} from "@/components/ui/base-card";
import { getAvatarUrl } from "@/lib/utils";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

import { useAuth } from "@/hooks/useAuth";
import { useAdminUsersList, useAdminDeleteUser, useAdminBulkAction } from "@/hooks/useAdminUsers";
import { UserDialog } from "@/components/admin/UserDialog";
import { SetPasswordDialog } from "@/components/admin/SetPasswordDialog";
import { ManageRolesDialog } from "@/components/admin/ManageRolesDialog";
import type { User } from "@/types/api.types";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { toast } from "sonner";
import type { UsersPage } from "@/types/api.types";
import { PageContainer } from "@/components/layouts/PageContainer";
import { TableEmptyState } from "@/components/common/EmptyState";

interface AdminUsersClientProps {
  initialData: UsersPage; // ✅ Initial data from server
}

export function AdminUsersClient({ initialData }: AdminUsersClientProps) {
  const { user: currentUser } = useAuth();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<string>("id");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [userToDelete, setUserToDelete] = useState<User | null>(null);
  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [setPasswordDialogOpen, setSetPasswordDialogOpen] = useState(false);
  const [setPasswordUser, setSetPasswordUser] = useState<User | null>(null);
  const [manageRolesDialogOpen, setManageRolesDialogOpen] = useState(false);
  const [manageRolesUser, setManageRolesUser] = useState<User | null>(null);
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false);

  // FIX 3: Reset row selection when filters/page change
  useEffect(() => {
    setRowSelection({});
  }, [page, search, roleFilter, statusFilter]);

  // F5: Auto-navigate về trang trước khi xóa user cuối cùng ở trang N
  useEffect(() => {
    if (!isLoading && data && data.users.length === 0 && page > 1) {
      setPage((p) => p - 1);
    }
  }, [data, isLoading, page]);

  // FIX 2: Debounced search handler
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setPage(1);
  }, []);

  // ✅ Fetch users with filters and sorting (with initialData)
  const { data, isLoading, error } = useAdminUsersList(
    {
      page,
      page_size: 10,
      search: search || undefined,
      role: roleFilter === "all" ? undefined : roleFilter,
      status: statusFilter === "all" ? undefined : statusFilter,
      sort: sortBy,
      order: sortOrder,
    },
    {
      // ✅ Use initialData only for first page, no filters
      initialData:
        page === 1 && !search && roleFilter === "all" && statusFilter === "all"
          ? initialData
          : undefined,
    }
  );

  const deleteUserMutation = useAdminDeleteUser();
  const bulkActionMutation = useAdminBulkAction();

  // Handle column sorting
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

  // Render sort icon for column header
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

  const handleEditUser = useCallback((user: User) => {
    setSelectedUser(user);
    setDialogMode("edit");
    setUserDialogOpen(true);
  }, []);

  // Table columns definition
  const columns = useMemo<ColumnDef<User>[]>(
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
        accessorKey: "user",
        header: "Người dùng",
        cell: ({ row }) => {
          const user = row.original;
          return (
            <div className="flex items-center gap-3">
              <Avatar>
                <AvatarImage src={getAvatarUrl(user.avatar_url)} alt={user.username} />
                <AvatarFallback>{user.username.slice(0, 2).toUpperCase()}</AvatarFallback>
              </Avatar>
              <div>
                <p className="font-medium">{user.full_name || user.username}</p>
                <p className="text-muted-foreground text-sm">@{user.username}</p>
              </div>
            </div>
          );
        },
      },
      {
        accessorKey: "email",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("email")} className="-ml-4 h-8">
            Email
            {getSortIcon("email")}
          </Button>
        ),
      },
      {
        accessorKey: "role",
        header: () => (
          <Button variant="ghost" onClick={() => handleSort("role")} className="-ml-4 h-8">
            Vai trò
            {getSortIcon("role")}
          </Button>
        ),
        cell: ({ row }) => {
          const role = row.original.role;
          const variant =
            role === "admin" ? "default" : role === "manager" ? "secondary" : "outline";
          return <Badge variant={variant}>{role}</Badge>;
        },
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
          const status = row.original.status;
          const variant =
            status === "active" ? "default" : status === "pending" ? "secondary" : "destructive";
          return <Badge variant={variant}>{status}</Badge>;
        },
      },
      {
        id: "actions",
        cell: ({ row }) => {
          const user = row.original;
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
                <DropdownMenuItem asChild>
                  <Link href={`/admin/users/${user.id}`}>
                    <Eye className="mr-2 h-4 w-4" />
                    Xem chi tiết
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => handleEditUser(user)}>
                  <Edit className="mr-2 h-4 w-4" />
                  Sửa người dùng
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => {
                    setSetPasswordUser(user);
                    setSetPasswordDialogOpen(true);
                  }}
                >
                  <Key className="mr-2 h-4 w-4" />
                  Đặt mật khẩu
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => {
                    setManageRolesUser(user);
                    setManageRolesDialogOpen(true);
                  }}
                >
                  <Shield className="mr-2 h-4 w-4" />
                  Quản lý vai trò
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() => setUserToDelete(user)}
                  disabled={user.id === currentUser?.id}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Xoá người dùng
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          );
        },
      },
    ],
    [getSortIcon, handleSort, currentUser?.id, handleEditUser]
  );

  // Setup TanStack Table
  // TanStack Table is not yet React Compiler-compatible in this component.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: data?.users || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    onRowSelectionChange: setRowSelection,
    state: {
      rowSelection,
    },
    manualPagination: true,
    pageCount: data ? Math.ceil(data.total_count / 10) : 0,
    getRowId: (row) => String(row.id), // Ensure consistent row ID for mobile/desktop selection
  });

  const handleCreateUser = () => {
    setSelectedUser(null);
    setDialogMode("create");
    setUserDialogOpen(true);
  };

  const handleDeleteUser = async () => {
    if (userToDelete) {
      try {
        await deleteUserMutation.mutateAsync(userToDelete.id);
        setUserToDelete(null); // closes dialog via open={!!userToDelete}
      } catch {
        // Error toast handled by mutation hook. Dialog stays open for retry.
      }
    }
  };

  const handleBulkDelete = async () => {
    const selectedRows = table.getFilteredSelectedRowModel().rows;
    // FIX 7: Filter out self from bulk delete
    const userIds = selectedRows
      .map((row) => row.original.id)
      .filter((id) => id !== currentUser?.id);

    if (userIds.length === 0) {
      toast.info("Không có người dùng nào để xoá.");
      setBulkDeleteDialogOpen(false);
      return;
    }

    try {
      await bulkActionMutation.mutateAsync({
        action: "delete",
        user_ids: userIds,
      });

      setRowSelection({});
      setBulkDeleteDialogOpen(false);
    } catch {
      // Error toast from hook. Dialog stays open.
    }
  };

  const handleOpenBulkDelete = () => {
    const selectedRows = table.getFilteredSelectedRowModel().rows;
    if (selectedRows.length > 0) {
      setBulkDeleteDialogOpen(true);
    }
  };

  const handleBulkChangeStatus = async (newStatus: "active" | "pending" | "banned") => {
    const selectedRows = table.getFilteredSelectedRowModel().rows;
    let userIds = selectedRows.map((row) => row.original.id);

    // FIX 7: Filter out self for dangerous statuses
    if ((newStatus === "banned" || newStatus === "pending") && currentUser?.id) {
      userIds = userIds.filter((id) => id !== currentUser.id);
    }

    if (userIds.length === 0) {
      toast.info("Không có người dùng nào để thay đổi trạng thái.");
      return;
    }

    await bulkActionMutation.mutateAsync({
      action: "change_status",
      user_ids: userIds,
      status: newStatus,
    });

    setRowSelection({});
  };

  const handleExportCSV = async () => {
    toast.info("Đang xuất CSV...");

    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (roleFilter !== "all") params.set("role", roleFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      params.set("sort", sortBy);
      params.set("order", sortOrder);

      const url = `${API_ENDPOINTS.ADMIN.USERS.EXPORT_CSV_STREAM}?${params.toString()}`;

      const response = await api.get(url, {
        responseType: "blob",
      });

      const blob = new Blob([response.data], { type: "text/csv;charset=utf-8;" });
      const link = document.createElement("a");
      const blobUrl = URL.createObjectURL(blob);

      const filename = `users_export_${new Date().toISOString().split("T")[0]}.csv`;

      link.setAttribute("href", blobUrl);
      link.setAttribute("download", filename);
      link.style.visibility = "hidden";
      document.body.appendChild(link);
      link.click();

      document.body.removeChild(link);
      URL.revokeObjectURL(blobUrl);

      toast.success("Xuất CSV thành công.");
    } catch (error) {
      console.error("Error exporting users CSV:", error);
      toast.error("Xuất CSV thất bại");
    }
  };

  const selectedCount = table.getFilteredSelectedRowModel().rows.length;

  if (error) {
    return (
      <PageContainer maxWidth="xl">
        <header>
          <h1 className="text-2xl sm:text-3xl font-bold font-display tracking-tight">Quản Lý Người Dùng</h1>
          <p className="text-muted-foreground text-sm sm:text-base">Quản lý người dùng, vai trò và quyền hạn.</p>
        </header>
        <Card>
          <CardContent className="pt-6">
            <p className="text-destructive">Lỗi tải người dùng: {error.message}</p>
          </CardContent>
        </Card>
      </PageContainer>
    );
  }

  return (
    <PageContainer maxWidth="xl">
      {/* Header - Responsive: stack on mobile */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold font-display tracking-tight">Quản Lý Người Dùng</h1>
          <p className="text-muted-foreground text-sm sm:text-base">Quản lý người dùng, vai trò và quyền hạn.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="flex-1 sm:flex-none" onClick={handleExportCSV} disabled={!data?.users.length}>
            <Download className="mr-2 h-4 w-4" />
            <span className="hidden xs:inline">Xuất CSV</span>
            <span className="xs:hidden">Xuất</span>
          </Button>
          <Button size="sm" className="flex-1 sm:flex-none" onClick={handleCreateUser}>
            <Plus className="mr-2 h-4 w-4" />
            <span className="hidden xs:inline">Thêm Người Dùng</span>
            <span className="xs:hidden">Thêm</span>
          </Button>
        </div>
      </header>

      {/* Bulk Actions Bar - Responsive: wrap on mobile */}
      {selectedCount > 0 && (
        <Card className="border-primary">
          <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-2">
              <CheckSquare className="text-primary h-5 w-5" />
              <span className="font-medium text-sm sm:text-base">{selectedCount} người dùng được chọn</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" className="flex-1 sm:flex-none" onClick={() => table.resetRowSelection()}>
                <Square className="mr-1.5 h-4 w-4" />
                <span className="hidden sm:inline">Bỏ chọn tất cả</span>
                <span className="sm:hidden">Bỏ chọn</span>
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="flex-1 sm:flex-none">
                    <Edit className="mr-1.5 h-4 w-4" />
                    <span className="hidden sm:inline">Đổi trạng thái</span>
                    <span className="sm:hidden">Trạng thái</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>Đặt trạng thái:</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => handleBulkChangeStatus("active")}>
                    Hoạt động
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleBulkChangeStatus("pending")}>
                    Chờ duyệt
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleBulkChangeStatus("banned")}>
                    Bị cấm
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <Button variant="destructive" size="sm" className="flex-1 sm:flex-none" onClick={handleOpenBulkDelete}>
                <Trash2 className="mr-1.5 h-4 w-4" />
                Xoá
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Bộ lọc</CardTitle>
          <CardDescription>Tìm kiếm và lọc người dùng</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 md:flex-row">
            <SearchInput
              value={search}
              onChange={handleSearchChange}
              debounceMs={300}
              placeholder="Tìm theo tên hoặc email..."
              containerClassName="flex-1"
            />
            <Select value={roleFilter} onValueChange={setRoleFilter}>
              <SelectTrigger className="w-full md:w-[180px]">
                <SelectValue placeholder="Tất cả vai trò" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả vai trò</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
                <SelectItem value="manager">Quản lý</SelectItem>
                <SelectItem value="accountant">Kế toán</SelectItem>
                <SelectItem value="officer">Nhân viên</SelectItem>
                <SelectItem value="user">Người dùng</SelectItem>
              </SelectContent>
            </Select>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-full md:w-[180px]">
                <SelectValue placeholder="Tất cả trạng thái" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả trạng thái</SelectItem>
                <SelectItem value="active">Hoạt động</SelectItem>
                <SelectItem value="pending">Chờ duyệt</SelectItem>
                <SelectItem value="banned">Bị cấm</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Users Table - Desktop */}
      <Card className="hidden md:block">
        <CardContent className="p-0">
          {isLoading ? (
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
                      <TableCell colSpan={columns.length} className="h-32">
                        <TableEmptyState
                          title={search ? "Không tìm thấy người dùng" : "Chưa có người dùng nào"}
                          description={search ? "Thử tìm kiếm với từ khóa khác" : "Thêm người dùng mới để bắt đầu"}
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

      {/* Users Cards - Mobile */}
      <div className="md:hidden space-y-3">
        {isLoading ? (
          // Mobile skeleton
          Array.from({ length: 5 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <Skeleton className="h-10 w-10 rounded-full" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        ) : data?.users && data.users.length > 0 ? (
          <>
            {/* Select All header */}
            <div className="flex items-center gap-2 px-1 py-2">
              <Checkbox
                checked={table.getIsAllPageRowsSelected()}
                onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
                aria-label="Chọn tất cả"
              />
              <span className="text-sm text-muted-foreground">Chọn tất cả</span>
            </div>

            {/* User Cards */}
            {data.users.map((user) => (
              <UserCard
                key={user.id}
                user={user}
                currentUserId={currentUser?.id}
                isSelected={rowSelection[String(user.id)] ?? false}
                onSelect={(checked) => {
                  setRowSelection((prev) => ({
                    ...prev,
                    [String(user.id)]: checked,
                  }))
                }}
                onEdit={() => handleEditUser(user)}
                onDelete={() => setUserToDelete(user)}
                onSetPassword={() => {
                  setSetPasswordUser(user);
                  setSetPasswordDialogOpen(true);
                }}
                onManageRoles={() => {
                  setManageRolesUser(user);
                  setManageRolesDialogOpen(true);
                }}
              />
            ))}
          </>
        ) : (
          <Card>
            <CardContent className="py-8">
              <TableEmptyState
                title={search ? "Không tìm thấy người dùng" : "Chưa có người dùng nào"}
                description={search ? "Thử tìm kiếm với từ khóa khác" : "Thêm người dùng mới để bắt đầu"}
              />
            </CardContent>
          </Card>
        )}
      </div>

      {/* Pagination - Responsive: stack on mobile */}
      {data && data.total_count > 10 && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-muted-foreground text-xs sm:text-sm text-center sm:text-left">
            Hiển thị {(page - 1) * 10 + 1}-{Math.min(page * 10, data.total_count)} / {data.total_count}
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
              onClick={() => setPage((p) => Math.min(Math.ceil(data.total_count / 10), p + 1))}
              disabled={page === Math.ceil(data.total_count / 10)}
            >
              Sau
            </Button>
          </div>
        </div>
      )}

      {/* Dialogs */}
      <UserDialog
        open={userDialogOpen}
        onOpenChange={setUserDialogOpen}
        user={selectedUser}
        mode={dialogMode}
      />

      {setPasswordUser && (
        <SetPasswordDialog
          open={setPasswordDialogOpen}
          onOpenChange={setSetPasswordDialogOpen}
          user={setPasswordUser}
        />
      )}

      {manageRolesUser && (
        <ManageRolesDialog
          open={manageRolesDialogOpen}
          onOpenChange={setManageRolesDialogOpen}
          user={manageRolesUser}
        />
      )}

      <AlertDialog open={!!userToDelete} onOpenChange={() => setUserToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Bạn có chắc?</AlertDialogTitle>
            <AlertDialogDescription>
              Thao tác này sẽ xoá vĩnh viễn người dùng <strong>{userToDelete?.username}</strong>. Không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <Button
              onClick={handleDeleteUser}
              disabled={deleteUserMutation.isPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteUserMutation.isPending ? "Đang xoá…" : "Xoá"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={bulkDeleteDialogOpen} onOpenChange={setBulkDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xoá nhiều người dùng?</AlertDialogTitle>
            <AlertDialogDescription>
              Thao tác này sẽ xoá vĩnh viễn <strong>{currentUser?.id && rowSelection[String(currentUser.id)] ? selectedCount - 1 : selectedCount} người dùng</strong>. Không thể hoàn tác.
              {currentUser?.id && rowSelection[String(currentUser.id)] && (
                <span className="block mt-2 text-warning-500 font-medium">
                  Hệ thống sẽ bỏ qua tài khoản của bạn.
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <Button
              onClick={handleBulkDelete}
              disabled={bulkActionMutation.isPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {bulkActionMutation.isPending ? "Đang xoá…" : "Xoá tất cả"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}

// =============================================================================
// MOBILE CARD COMPONENT - Using BaseCard System
// =============================================================================

interface UserCardProps {
  user: User;
  currentUserId?: number;
  isSelected: boolean;
  onSelect: (checked: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
  onSetPassword: () => void;
  onManageRoles: () => void;
}

function UserCard({ user, currentUserId, isSelected, onSelect, onEdit, onDelete, onSetPassword, onManageRoles }: UserCardProps) {
  const roleVariant = user.role === "admin" ? "default" : user.role === "manager" ? "secondary" : "outline";
  const statusVariant = user.status === "active" ? "default" : user.status === "pending" ? "secondary" : "destructive";

  return (
    <BaseCard
      selected={isSelected}
      onSelect={onSelect}
      showCheckbox
    >
      {/* Header: Name with Avatar */}
      <BaseCardHeader
        title={
          <div className="flex items-center gap-2">
            <Avatar className="h-8 w-8 flex-shrink-0">
              <AvatarImage src={getAvatarUrl(user.avatar_url)} alt={user.username} />
              <AvatarFallback>{user.username.slice(0, 2).toUpperCase()}</AvatarFallback>
            </Avatar>
            <Link
              href={`/admin/users/${user.id}`}
              className="hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {user.full_name || user.username}
            </Link>
          </div>
        }
        subtitle={`@${user.username}`}
      />

      {/* Body: Email */}
      <CardBody>
        <CardField label="Email" value={user.email} />
      </CardBody>

      {/* Meta: Role + Status badges */}
      <CardMeta>
        <Badge variant={roleVariant}>{user.role}</Badge>
        <Badge variant={statusVariant}>{user.status}</Badge>
      </CardMeta>

      {/* Actions */}
      <CardActions>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-10 w-10 md:h-8 md:w-8">
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Thao tác</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href={`/admin/users/${user.id}`}>
                <Eye className="mr-2 h-4 w-4" />
                Xem chi tiết
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onEdit}>
              <Edit className="mr-2 h-4 w-4" />
              Sửa người dùng
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onSetPassword}>
              <Key className="mr-2 h-4 w-4" />
              Đặt mật khẩu
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onManageRoles}>
              <Shield className="mr-2 h-4 w-4" />
              Quản lý vai trò
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={onDelete}
              disabled={user.id === currentUserId}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Xoá người dùng
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardActions>
    </BaseCard>
  );
}



